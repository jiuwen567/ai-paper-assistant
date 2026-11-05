"""数据库删除与清单同事务提交；外部存储按清单幂等执行，失败只重试未完成项。"""

from contextlib import closing
from datetime import timedelta

from botocore.exceptions import ClientError
from django.db import transaction
from django.utils import timezone

from core import models as m
from core.cleanup_plan import Plan
from core.health import s3_client

LEASE_SECONDS = 60


def create_cleanup(plan: Plan, user, request_key, fingerprint):
    manifest = plan.manifest()
    record = m.CleanupRequest.objects.create(
        project_id=plan.project.pk,
        material_id=plan.material.pk if plan.material else None,
        scope="material" if plan.material else "project",
        created_by=user,
        request_key=request_key,
        request_digest=fingerprint,
        manifest=manifest,
    )
    plan.delete_database(user, record.pk)
    if plan.material:
        from core.graph import mark_dirty

        mark_dirty(plan.project.pk)
    m.CleanupItem.objects.create(
        request=record,
        key="database",
        kind="database",
        target={"counts": {name: len(ids) for name, ids in manifest["targets"].items()}},
        status="removed",
        completed_at=timezone.now(),
    )
    m.CleanupItem.objects.bulk_create(
        [
            m.CleanupItem(request=record, key=key, kind="object", target=target)
            for key, target in manifest["objects"].items()
        ]
    )
    m.CleanupItem.objects.create(
        request=record, key="graph", kind="graph", target={"project_id": str(record.project_id)}
    )
    transaction.on_commit(lambda: dispatch(record.pk))
    return record


def dispatch(request_id):
    from worker.tasks import execute_cleanup

    try:
        execute_cleanup.apply_async(args=[str(request_id)], retry=False)
    except Exception:
        m.CleanupRequest.objects.filter(pk=request_id, status="queued").update(
            error_code="dispatch_failed"
        )


@transaction.atomic
def claim(request_id):
    record = m.CleanupRequest.objects.select_for_update().filter(pk=request_id).first()
    if record is None or record.status != "queued":
        return None
    record.generation += 1
    record.status = "running"
    record.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
    record.error_code = ""
    record.save(update_fields=["generation", "status", "lease_until", "error_code", "updated_at"])
    m.CleanupAttempt.objects.create(request=record, generation=record.generation)
    return record


def active(record, generation):
    return (
        record.status == "running"
        and record.generation == generation
        and record.lease_until
        and record.lease_until > timezone.now()
    )


def shared_object(target):
    return (
        m.MaterialVersion.objects.filter(**target).exists()
        or m.ExportFile.objects.filter(**target).exists()
    )


def remove_object(target):
    # 当前上传/导出路径按 UUID 分配，不按摘要去重；仍检查跨产物的相同对象引用。
    if shared_object(target):
        return "shared"
    with closing(s3_client()) as client:
        args = {"Bucket": target["bucket"], "Key": target["object_key"]}
        try:
            client.delete_object(**args)
        except ClientError as error:
            if error.response["Error"]["Code"] not in ["NoSuchBucket", "NoSuchKey", "404"]:
                raise
        try:
            client.head_object(**args)
        except ClientError as error:
            if error.response["Error"]["Code"] not in ["NoSuchBucket", "NoSuchKey", "404"]:
                raise
        else:
            raise ValueError("object_still_exists")
    return "removed"


@transaction.atomic
def remove_graph(record):
    from core.graph import GraphUnavailable, delete_projection, sync_project

    project = m.Project.objects.select_for_update().filter(pk=record.project_id).first()
    if project is None:
        delete_projection(record.project_id)
    elif not sync_project(project.pk):
        raise GraphUnavailable("graph_cleanup_pending")
    return "removed"


@transaction.atomic
def execute_item(request_id, generation, item_id):
    record = m.CleanupRequest.objects.select_for_update().get(pk=request_id)
    if not active(record, generation):
        return False
    item = record.items.get(pk=item_id)
    if item.status in ["removed", "shared"]:
        return True
    # 有界外部请求期间持有清理行锁，避免旧代次与人工重试重复确认同一项。
    try:
        status = remove_object(item.target) if item.kind == "object" else remove_graph(record)
    except Exception as error:
        item.status = "failed"
        item.error_code = type(error).__name__[:100]
    else:
        item.status, item.error_code, item.completed_at = status, "", timezone.now()
    item.save(update_fields=["status", "error_code", "completed_at"])
    record.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
    record.save(update_fields=["lease_until", "updated_at"])
    return True


@transaction.atomic
def finish(request_id, generation):
    record = m.CleanupRequest.objects.select_for_update().get(pk=request_id)
    if not active(record, generation):
        return
    record.status = (
        "failed" if record.items.exclude(status__in=["removed", "shared"]).exists() else "succeeded"
    )
    record.error_code = "cleanup_incomplete" if record.status == "failed" else ""
    record.lease_until = None
    record.completed_at = timezone.now() if record.status == "succeeded" else None
    record.save(update_fields=["status", "error_code", "lease_until", "completed_at", "updated_at"])
    record.attempts.filter(generation=generation, finished_at=None).update(
        status=record.status,
        error_code=record.error_code,
        errors=list(record.items.filter(status="failed").values("id", "kind", "error_code")),
        finished_at=timezone.now(),
    )


def execute(request_id):
    record = claim(request_id)
    if record is None:
        return
    for item_id in (
        record.items.exclude(status__in=["removed", "shared"])
        .order_by("id")
        .values_list("pk", flat=True)
    ):
        if not execute_item(record.pk, record.generation, item_id):
            return
    finish(record.pk, record.generation)


@transaction.atomic
def recover_one(request_id):
    record = m.CleanupRequest.objects.select_for_update().filter(pk=request_id).first()
    if record is None:
        return
    if record.status == "queued":
        transaction.on_commit(lambda: dispatch(record.pk))
    elif record.status == "running" and (
        record.lease_until is None or record.lease_until <= timezone.now()
    ):
        record.status, record.error_code, record.lease_until = "failed", "lease_expired", None
        record.save(update_fields=["status", "error_code", "lease_until", "updated_at"])
        record.attempts.filter(generation=record.generation, finished_at=None).update(
            status="failed",
            error_code="lease_expired",
            errors=list(record.items.filter(status="failed").values("id", "kind", "error_code")),
            finished_at=timezone.now(),
        )


def recover():
    for request_id in (
        m.CleanupRequest.objects.filter(status__in=["queued", "running"])
        .order_by("updated_at")
        .values_list("pk", flat=True)[:100]
    ):
        recover_one(request_id)
