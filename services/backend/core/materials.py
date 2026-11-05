import hashlib
from contextlib import closing
from datetime import timedelta

from botocore.exceptions import ClientError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound

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
    try:
        Project.objects.select_for_update().get(pk=project_id)
    except Project.DoesNotExist:
        raise MaterialVersion.DoesNotExist from None
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
    try:
        version = lock_version(version_id)
    except MaterialVersion.DoesNotExist:
        raise NotFound("上传记录已删除。") from None
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
    try:
        version = lock_version(version_id)
    except MaterialVersion.DoesNotExist:
        return
    if version.generation == generation and version.status != MaterialVersion.Status.AVAILABLE:
        set_failure(version, code, "上传或校验失败，请重试同一文件或执行对账。")


@transaction.atomic
def publish_upload(version_id, generation):
    try:
        version = lock_version(version_id)
    except MaterialVersion.DoesNotExist:
        return False
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
    return data


@transaction.atomic
def store_current_file(submitted, data):
    # 删除与写入共用项目锁，防止清理后迟到的上传再次写回对象。
    try:
        version = lock_version(submitted.pk)
    except MaterialVersion.DoesNotExist:
        raise NotFound("上传记录已删除。") from None
    require_project(version.created_by, version.material.project_id, write=True)
    if version.status == MaterialVersion.Status.AVAILABLE:
        return ""
    if (
        version.generation != submitted.generation
        or version.status != MaterialVersion.Status.VALIDATING
        or version.sha256 != submitted.sha256
        or not version.lease_until
        or version.lease_until <= timezone.now()
    ):
        return "changed"
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
        set_failure(version, "storage_failed", "上传或校验失败，请重试同一文件或执行对账。")
        return "storage_failed"
    return "" if publish_upload(version.pk, version.generation) else "changed"


def store_file(version, data):
    # 在事务提交后报告失败，保留数据库诊断状态。
    result = store_current_file(version, data)
    if result == "storage_failed":
        raise StorageUnavailable()
    if result:
        raise VersionConflict("上传者权限或执行状态已变化，文件未发布。")


def reconcile_upload(version_id):
    version = MaterialVersion.objects.select_related("created_by").filter(pk=version_id).first()
    if version is None:
        return
    if not version.sha256 or version.status == MaterialVersion.Status.AVAILABLE:
        return
    try:
        version = claim_upload(version.created_by, version.pk)
    except NotFound:
        return
    try:
        with closing(s3_client()) as client:
            read_and_verify(client, version)
    except Exception:
        fail_upload(version.pk, version.generation, "reconciliation_failed")
        return
    publish_upload(version.pk, version.generation)
