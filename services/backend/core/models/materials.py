import uuid

from django.conf import settings
from django.db import models


class Material(models.Model):
    access_state = models.CharField(max_length=16, default="active")
    state_version = models.PositiveIntegerField(default=1)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="materials")
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=24)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(access_state__in=["active", "withdrawn"]),
                name="material_access_state",
            ),
            models.CheckConstraint(
                condition=models.Q(state_version__gt=0), name="material_positive_state_version"
            ),
        ]


class MaterialVersion(models.Model):
    class Status(models.TextChoices):
        UPLOADING = "uploading", "等待上传"
        VALIDATING = "validating", "上传校验中"
        AVAILABLE = "available", "可用"
        FAILED = "failed", "失败"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    material = models.ForeignKey("Material", on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=128)
    request_snapshot = models.JSONField()
    file_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    media_type = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64, blank=True)
    bucket = models.CharField(max_length=100)
    object_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UPLOADING)
    usage_state = models.CharField(max_length=16, default="active")
    usage_version = models.PositiveIntegerField(default=1)
    generation = models.PositiveIntegerField(default=0)
    lease_until = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["material", "number"], name="unique_material_version"),
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_upload_request"
            ),
            models.CheckConstraint(condition=models.Q(size__gt=0), name="material_nonempty_file"),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="material_positive_version"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["uploading", "validating", "available", "failed"]),
                name="material_valid_status",
            ),
            models.CheckConstraint(
                condition=models.Q(usage_state__in=["active", "corrected", "withdrawn"]),
                name="material_version_usage_state",
            ),
            models.CheckConstraint(
                condition=models.Q(usage_version__gt=0), name="material_usage_version_positive"
            ),
        ]


class ParseRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_version = models.ForeignKey(
        "MaterialVersion", on_delete=models.CASCADE, related_name="parses"
    )
    number = models.PositiveIntegerField()
    parser_version = models.CharField(max_length=128)
    job = models.OneToOneField("Job", on_delete=models.CASCADE, related_name="parse_run")
    warnings = models.JSONField(default=list)
    coverage = models.CharField(max_length=16, default="pending")
    published_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_version", "number"], name="unique_parse_version"
            ),
            models.CheckConstraint(condition=models.Q(number__gt=0), name="parse_positive_version"),
        ]


class SourceChunk(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey("ParseRun", on_delete=models.CASCADE, related_name="chunks")
    ordinal = models.PositiveIntegerField()
    text = models.TextField()
    anchor = models.JSONField()
    heading_level = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "ordinal"], name="unique_source_chunk"),
            models.CheckConstraint(
                condition=models.Q(ordinal__gt=0), name="chunk_positive_ordinal"
            ),
            models.CheckConstraint(
                condition=models.Q(heading_level__lte=9), name="chunk_heading_range"
            ),
        ]
