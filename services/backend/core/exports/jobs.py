import hashlib
from contextlib import closing

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.common.digests import digest
from core.common.errors import ParseFailure
from core.exports.service import RENDERER_VERSION, unavailable_sources
from core.exports.word import ExportStopped, render_word
from core.jobs.service import active, finish, heartbeat, lock_job
from core.materials.service import ensure_bucket, read_and_verify
from core.models import ExportFile, ExportSnapshot, Job
from core.storage.s3 import s3_client

WORD_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def valid_snapshot(snapshot, job):
    return (
        str(snapshot.pk) == job.input_snapshot.get("snapshot_id")
        and snapshot.digest == job.input_snapshot.get("digest") == digest(snapshot.content)
        and snapshot.renderer_version == job.input_snapshot.get("renderer_version")
        and not unavailable_sources(snapshot)
    )


@transaction.atomic
def export_checkpoint(snapshot, generation, progress):
    job = lock_job(snapshot.job_id)
    if not active(job, generation):
        return False
    if not valid_snapshot(snapshot, job):
        finish(job, Job.Status.CANCELLED, "export_source_changed", "快照校验失败或来源状态已变化。")
        return False
    return heartbeat(job.pk, generation, progress)


@transaction.atomic
def prepare_file(snapshot, generation):
    if not export_checkpoint(snapshot, generation, 1):
        return None
    return ExportFile.objects.get_or_create(
        snapshot=snapshot,
        generation=generation,
        defaults={
            "bucket": settings.MATERIAL_BUCKET,
            "object_key": f"exports/{snapshot.project_id}/{snapshot.pk}/{generation}.docx",
        },
    )[0]


@transaction.atomic
def publish_export(file_id, generation, sha256, size):
    artifact = ExportFile.objects.select_related("snapshot").get(pk=file_id)
    snapshot = artifact.snapshot
    job = lock_job(snapshot.job_id)
    if not active(job, generation):
        return False
    if artifact.generation != generation or artifact.published_at:
        return False
    if not valid_snapshot(snapshot, job):
        finish(job, Job.Status.CANCELLED, "export_source_changed", "快照校验失败或来源状态已变化。")
        return False
    artifact.sha256, artifact.size, artifact.published_at = sha256, size, timezone.now()
    artifact.save(update_fields=["sha256", "size", "published_at"])
    job.output = {"snapshot_id": str(snapshot.pk), "file_id": artifact.pk, "sha256": sha256}
    job.progress = 100
    finish(job, Job.Status.SUCCEEDED)
    return True


def execute_export(job):
    snapshot = ExportSnapshot.objects.get(job=job)
    if snapshot.renderer_version != RENDERER_VERSION:
        raise ParseFailure("renderer_changed", "导出器版本已变化，请重新预览并创建导出。")
    artifact = prepare_file(snapshot, job.generation)
    if artifact is None:
        return
    try:
        data = render_word(
            snapshot.content,
            snapshot.created_at,
            lambda progress: export_checkpoint(snapshot, job.generation, progress),
        )
    except ExportStopped:
        return
    store_export(snapshot, job.generation, artifact, data)


@transaction.atomic
def store_export(snapshot, generation, artifact, data):
    # 持有项目锁直到存储和发布结束，删除清单不会遗漏迟到的对象写入。
    if not export_checkpoint(snapshot, generation, 75):
        return
    artifact.sha256, artifact.size = hashlib.sha256(data).hexdigest(), len(data)
    try:
        with closing(s3_client()) as client:
            ensure_bucket(client, artifact.bucket)
            client.put_object(
                Bucket=artifact.bucket, Key=artifact.object_key, Body=data, ContentType=WORD_TYPE
            )
            read_and_verify(client, artifact)
    except ValueError:
        raise ParseFailure("export_integrity", "导出文件校验失败，可重试。", True) from None
    except Exception:
        raise ParseFailure("export_storage", "暂时无法保存导出文件，可重试。", True) from None
    publish_export(artifact.pk, generation, artifact.sha256, artifact.size)
