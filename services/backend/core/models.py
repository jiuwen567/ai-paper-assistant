import uuid

from django.conf import settings
from django.db import models


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    paper_type = models.CharField(max_length=80, blank=True)
    requirements = models.TextField(blank=True)
    template = models.CharField(max_length=120, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProjectMember(models.Model):
    class Role(models.TextChoices):
        AUTHOR = "author", "作者"
        REVIEWER = "reviewer", "审阅者"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="unique_project_member"),
            models.CheckConstraint(
                condition=models.Q(role__in=["author", "reviewer"]), name="valid_project_role"
            ),
        ]


class ProjectPolicy(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="policies")
    version = models.PositiveIntegerField()
    source = models.CharField(max_length=500, blank=True)
    source_version = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    allowed_actions = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "version"], name="unique_project_policy"),
            models.CheckConstraint(
                condition=models.Q(verified=True) | models.Q(allowed_actions=[]),
                name="unverified_policy_disables_ai",
            ),
            models.CheckConstraint(
                condition=models.Q(verified=False)
                | (~models.Q(source="") & ~models.Q(source_version="")),
                name="verified_policy_has_source",
            ),
        ]


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "等待执行"
        RUNNING = "running", "执行中"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="jobs")
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
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="attempts")
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
