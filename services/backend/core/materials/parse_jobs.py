from contextlib import closing

from django.db import transaction
from django.utils import timezone

from core.common.errors import ParseFailure
from core.jobs.service import active, finish, heartbeat, lock_job
from core.materials.parsing import PARSER_VERSION, ParsingStopped, parse_document
from core.materials.service import read_and_verify
from core.models import Job, MaterialVersion, ParseRun, SourceChunk
from core.storage.s3 import s3_client


def valid_source(run, job):
    source = MaterialVersion.objects.select_related("material").get(pk=run.source_version_id)
    return (
        source.material.project_id == job.project_id
        and source.status == "available"
        and source.usage_state != "withdrawn"
        and source.material.access_state == "active"
        and source.material.state_version == job.input_snapshot.get("source_state_version")
        and str(source.pk) == job.input_snapshot.get("source_version_id")
        and source.sha256 == job.input_snapshot.get("source_sha256")
        and str(run.pk) == job.input_snapshot.get("parse_run_id")
    )


@transaction.atomic
def parse_checkpoint(run, generation, progress):
    job = lock_job(run.job_id)
    if not active(job, generation):
        return False
    if not valid_source(run, job):
        finish(job, Job.Status.CANCELLED, "source_changed", "材料状态或输入版本已变化。")
        return False
    return heartbeat(job.pk, generation, progress)


@transaction.atomic
def publish_parse(run_id, generation, result):
    run = ParseRun.objects.get(pk=run_id)
    job = lock_job(run.job_id)
    if not active(job, generation):
        return False
    if not valid_source(run, job):
        finish(job, Job.Status.CANCELLED, "source_changed", "材料状态或输入版本已变化。")
        return False
    if run.published_at:
        return False
    SourceChunk.objects.bulk_create([SourceChunk(run=run, **item) for item in result.chunks])
    run.warnings = result.warnings
    run.coverage = result.coverage
    run.published_at = timezone.now()
    run.save()
    job.output = {"parse_run_id": str(run.pk), "chunks": len(result.chunks)}
    job.progress = 100
    finish(job, Job.Status.SUCCEEDED)
    return True


def execute_parse(job):
    run = ParseRun.objects.select_related("source_version").get(job=job)
    if (
        run.parser_version != PARSER_VERSION
        or job.input_snapshot.get("parser_version") != PARSER_VERSION
    ):
        raise ParseFailure("parser_changed", "解析器版本已变化，请创建新的解析记录。")
    if not parse_checkpoint(run, job.generation, 1):
        return
    try:
        with closing(s3_client()) as client:
            data = read_and_verify(client, run.source_version)
    except ValueError:
        raise ParseFailure("source_integrity", "原件校验失败，未发布解析结果。") from None
    except Exception:
        raise ParseFailure("source_unavailable", "暂时无法读取原件，可重试。", True) from None
    try:
        result = parse_document(
            data,
            run.source_version.file_name,
            lambda progress: parse_checkpoint(run, job.generation, progress),
        )
    except ParsingStopped:
        return
    publish_parse(run.pk, job.generation, result)
