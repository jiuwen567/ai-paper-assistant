import uuid

from django.conf import settings
from django.db import models


class CleanupRequest(models.Model):
    """独立于项目生命周期的删除清单；不保存标题、原文或模型内容。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project_id = models.UUIDField()
    material_id = models.UUIDField(null=True)
    scope = models.CharField(max_length=16)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)
    manifest = models.JSONField()
    status = models.CharField(max_length=16, default="queued")
    generation = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_cleanup_request"
            ),
            models.CheckConstraint(
                condition=models.Q(scope="project", material_id__isnull=True)
                | models.Q(scope="material", material_id__isnull=False),
                name="cleanup_target_shape",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["queued", "running", "failed", "succeeded"]),
                name="cleanup_valid_status",
            ),
        ]
        indexes = [models.Index(fields=["status", "lease_until"])]


class CleanupItem(models.Model):
    request = models.ForeignKey("CleanupRequest", on_delete=models.CASCADE, related_name="items")
    kind = models.CharField(max_length=16)
    key = models.CharField(max_length=64)
    target = models.JSONField()
    status = models.CharField(max_length=16, default="pending")
    error_code = models.CharField(max_length=100, blank=True)
    completed_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "key"], name="unique_cleanup_item"),
            models.CheckConstraint(
                condition=models.Q(kind__in=["database", "object", "graph"]),
                name="cleanup_item_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "failed", "removed", "shared"]),
                name="cleanup_item_status",
            ),
        ]


class CleanupAttempt(models.Model):
    request = models.ForeignKey("CleanupRequest", on_delete=models.CASCADE, related_name="attempts")
    generation = models.PositiveIntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=16, default="running")
    error_code = models.CharField(max_length=100, blank=True)
    errors = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["request", "generation"], name="unique_cleanup_attempt"
            ),
            models.CheckConstraint(
                condition=models.Q(generation__gt=0), name="cleanup_generation_positive"
            ),
        ]
