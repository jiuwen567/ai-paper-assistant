import uuid

from django.conf import settings
from django.db import models


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "等待执行"
        RUNNING = "running", "执行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="jobs")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=40)
    idempotency_key = models.CharField(max_length=128)
    input_snapshot = models.JSONField(default=dict)
    ai_action = models.CharField(max_length=32, blank=True)
    policy_version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    generation = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    progress = models.PositiveSmallIntegerField(default=0)
    retryable = models.BooleanField(default=False)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=300, blank=True)
    output = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "idempotency_key"], name="unique_job_request"
            ),
            models.CheckConstraint(
                condition=models.Q(progress__lte=100), name="job_progress_range"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["queued", "running", "succeeded", "failed", "cancelled"]
                ),
                name="job_valid_status",
            ),
        ]
        indexes = [models.Index(fields=["status", "lease_until"])]


class JobAttempt(models.Model):
    job = models.ForeignKey("Job", on_delete=models.CASCADE, related_name="attempts")
    generation = models.PositiveIntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=16, choices=Job.Status.choices, default=Job.Status.RUNNING)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["job", "generation"], name="unique_job_attempt")
        ]


class ModelCall(models.Model):
    job = models.ForeignKey("Job", on_delete=models.CASCADE, related_name="model_calls")
    generation = models.PositiveIntegerField()
    number = models.PositiveIntegerField()
    model = models.CharField(max_length=128)
    prompt_version = models.CharField(max_length=64)
    input_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default="running")
    usage = models.JSONField(null=True)
    elapsed_ms = models.PositiveIntegerField(null=True)
    error_code = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "generation", "number"], name="unique_model_call"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gte=1, number__lte=4), name="model_call_limit"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["running", "succeeded", "failed", "cancelled"]),
                name="model_call_status",
            ),
        ]


class AIEvent(models.Model):
    job = models.ForeignKey("Job", on_delete=models.CASCADE, related_name="ai_events")
    generation = models.PositiveIntegerField()
    kind = models.CharField(max_length=32)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
