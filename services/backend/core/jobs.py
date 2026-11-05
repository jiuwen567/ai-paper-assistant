"""PostgreSQL 任务状态；Redis 仅负责唤醒，所有执行代次都经过租约检查。"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from core.access import VersionConflict, require_ai_action, require_project
from core.models import Job, JobAttempt, Project

LEASE_SECONDS = 30
MAX_ATTEMPTS = 3


def lock_job(job_id):
    # 所有路径统一先锁项目，和成员、规则写入使用同一个串行化边界。
    project_id = Job.objects.values_list("project_id", flat=True).get(pk=job_id)
    Project.objects.select_for_update().get(pk=project_id)
    return Job.objects.select_for_update().select_related("created_by").get(pk=job_id)


def finish(job, status, code="", message="", retryable=False):
    job.status = status
    job.lease_until = None
    job.retryable = retryable and job.generation < MAX_ATTEMPTS
    job.error_code = code
    job.error_message = message
    job.save()
    job.attempts.filter(generation=job.generation, finished_at=None).update(
        status=status, error_code=code, error_message=message, finished_at=timezone.now()
    )
    # 取消、租约回收和 Worker 异常也结束未返回的模型调用，不留下永久 running。
    if job.kind == "ai":
        now = timezone.now()
        for call in job.model_calls.filter(generation=job.generation, finished_at=None):
            call.status = "cancelled" if status == Job.Status.CANCELLED else "failed"
            call.error_code = code or "call_interrupted"
            call.finished_at = now
            call.elapsed_ms = max(0, int((now - call.started_at).total_seconds() * 1000))
            call.save()
        job.ai_events.create(generation=job.generation, kind=status, details={"code": code})


def authorized(job):
    try:
        project = require_project(job.created_by, job.project_id, write=True)
        policy = project.policies.order_by("-version").first()
        if policy is None or policy.version != job.policy_version:
            raise VersionConflict()
        if job.ai_action:
            require_ai_action(job.created_by, job.project_id, job.ai_action, job.policy_version)
    except APIException:
        finish(
            job, Job.Status.CANCELLED, "authorization_changed", "权限或规则已变化，请重新创建任务。"
        )
        return False
    return True


def active(job, generation):
    if job.status != Job.Status.RUNNING or job.generation != generation:
        return False
    if job.lease_until is None or job.lease_until <= timezone.now():
        finish(job, Job.Status.FAILED, "lease_expired", "执行租约超时，可重试。", True)
        return False
    return authorized(job)


@transaction.atomic
def claim(job_id):
    job = lock_job(job_id)
    if job.status != Job.Status.QUEUED or not authorized(job):
        return None
    if job.generation >= MAX_ATTEMPTS:
        finish(job, Job.Status.FAILED, "attempt_limit", "已达到尝试上限，请检查故障后创建新任务。")
        return None
    job.generation += 1
    job.status = Job.Status.RUNNING
    job.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
    job.error_code = job.error_message = ""
    job.retryable = False
    job.save()
    JobAttempt.objects.create(job=job, generation=job.generation)
    return job


@transaction.atomic
def heartbeat(job_id, generation, progress):
    job = lock_job(job_id)
    if not active(job, generation):
        return False
    job.progress = max(job.progress, min(99, max(0, progress)))
    job.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
    job.save()
    return True


@transaction.atomic
def publish(job_id, generation, output):
    job = lock_job(job_id)
    if not active(job, generation):
        return False
    job.output = output
    job.progress = 100
    finish(job, Job.Status.SUCCEEDED)
    return True


@transaction.atomic
def fail(
    job_id,
    generation,
    *,
    retryable=False,
    code="execution_failed",
    message="执行失败，请按错误代码检查任务。",
):
    job = lock_job(job_id)
    if active(job, generation):
        finish(job, Job.Status.FAILED, code, message, retryable)


def dispatch(job_id):
    from worker.tasks import execute_job

    try:
        execute_job.apply_async(args=[str(job_id)], retry=False)
    except Exception:
        # 队列故障不能把已提交的业务任务变成 HTTP 500 或丢失任务。
        Job.objects.filter(pk=job_id, status=Job.Status.QUEUED).update(
            error_code="dispatch_failed", error_message="任务已保存，等待队列恢复。"
        )


@transaction.atomic
def recover_one(job_id):
    job = lock_job(job_id)
    if job.status not in [Job.Status.RUNNING, Job.Status.QUEUED] or not authorized(job):
        return
    if job.status == Job.Status.RUNNING:
        if job.lease_until is None or job.lease_until <= timezone.now():
            finish(job, Job.Status.FAILED, "lease_expired", "Worker 中断或租约超时，可重试。", True)
    else:
        transaction.on_commit(lambda: dispatch(job.pk))


def recover_jobs():
    # 每次有界扫描；稳定排序使前次处理过的任务移到后面，避免饥饿。
    ids = list(
        Job.objects.filter(status__in=["queued", "running"])
        .order_by("updated_at")
        .values_list("id", flat=True)[:100]
    )
    for job_id in ids:
        try:
            recover_one(job_id)
            Job.objects.filter(pk=job_id).update(updated_at=timezone.now())
        except Job.DoesNotExist:
            pass  # 项目已由业务删除。
    return len(ids)
