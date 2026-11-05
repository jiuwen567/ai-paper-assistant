import hashlib
from contextlib import closing
from datetime import timedelta

from botocore.exceptions import ClientError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from core.access import VersionConflict, require_project
from core.health import s3_client
from core.material_files import MAX_FILE_SIZE
from core.models import MaterialVersion, Project


class StorageUnavailable(APIException):
    status_code = 503
    default_detail = "文件存储暂不可用，上传记录已保留，可重试。"


def lock_version(version_id):
    project_id = MaterialVersion.objects.values_list("material__project_id", flat=True).get(
        pk=version_id
    )
    Project.objects.select_for_update().get(pk=project_id)
    return (
        MaterialVersion.objects.select_for_update()
        .select_related("material", "created_by")
        .get(pk=version_id)
    )


def set_failure(version, code, message):
    version.status = MaterialVersion.Status.FAILED
    version.lease_until = None
    version.error_code = code
    version.error_message = message
    version.save()


@transaction.atomic
def claim_upload(user, version_id, sha256=None):
    version = lock_version(version_id)
    require_project(user, version.material.project_id, write=True)
    if version.created_by_id != user.pk:
        raise VersionConflict("请由原上传者重试该上传记录。")
    if sha256 and version.sha256 and version.sha256 != sha256:
        raise VersionConflict("此上传记录已对应不同文件，请创建新版本。")
    if version.status == MaterialVersion.Status.AVAILABLE:
        return version
    if version.lease_until and version.lease_until > timezone.now():
        raise VersionConflict("文件正在上传校验，请稍后刷新。")
    version.sha256 = sha256 or version.sha256
    version.generation += 1
    version.status = MaterialVersion.Status.VALIDATING
    version.lease_until = timezone.now() + timedelta(minutes=2)
    version.error_code = version.error_message = ""
    version.save()
    return version


@transaction.atomic
def fail_upload(version_id, generation, code="storage_failed"):
    version = lock_version(version_id)
    if version.generation == generation and version.status != MaterialVersion.Status.AVAILABLE:
        set_failure(version, code, "上传或校验失败，请重试同一文件或执行对账。")


@transaction.atomic
def publish_upload(version_id, generation):
    version = lock_version(version_id)
    if version.status == MaterialVersion.Status.AVAILABLE:
        return True
    if version.generation != generation or not version.lease_until:
        return False
    if version.lease_until <= timezone.now():
        set_failure(version, "lease_expired", "上传校验超时，请重试或执行对账。")
        return False
    try:
        require_project(version.created_by, version.material.project_id, write=True)
    except APIException:
        set_failure(version, "authorization_changed", "上传者权限已变化，文件未发布。")
        return False
    version.status = MaterialVersion.Status.AVAILABLE
    version.lease_until = None
    version.error_code = version.error_message = ""
    version.save()
    return True


def ensure_bucket(client, bucket):
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        try:
            client.create_bucket(Bucket=bucket)
        except ClientError as create_error:
            if create_error.response["Error"]["Code"] not in [
                "BucketAlreadyOwnedByYou",
                "BucketAlreadyExists",
            ]:
                raise
            client.head_bucket(Bucket=bucket)


def read_and_verify(client, version):
    response = client.get_object(Bucket=version.bucket, Key=version.object_key)
    with closing(response["Body"]) as body:
        data = body.read(MAX_FILE_SIZE + 1)
    if len(data) != version.size or hashlib.sha256(data).hexdigest() != version.sha256:
        raise ValueError("stored_file_mismatch")


def store_file(version, data):
    if version.status == MaterialVersion.Status.AVAILABLE:
        return
    try:
        with closing(s3_client()) as client:
            ensure_bucket(client, version.bucket)
            client.put_object(
                Bucket=version.bucket,
                Key=version.object_key,
                Body=data,
                ContentType=version.media_type,
                Metadata={"sha256": version.sha256},
            )
            read_and_verify(client, version)
    except Exception:
        fail_upload(version.pk, version.generation)
        raise StorageUnavailable() from None
    # 数据库发布失败时，已有对象仍通过版本记录、摘要与对象键可对账。
    if not publish_upload(version.pk, version.generation):
        raise VersionConflict("上传者权限或执行状态已变化，文件未发布。")


def reconcile_upload(version_id):
    version = MaterialVersion.objects.select_related("created_by").get(pk=version_id)
    if not version.sha256 or version.status == MaterialVersion.Status.AVAILABLE:
        return
    version = claim_upload(version.created_by, version.pk)
    try:
        with closing(s3_client()) as client:
            read_and_verify(client, version)
    except Exception:
        fail_upload(version.pk, version.generation, "reconciliation_failed")
        return
    publish_upload(version.pk, version.generation)
