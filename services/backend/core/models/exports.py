import uuid

from django.conf import settings
from django.db import models


class ExportTemplateVersion(models.Model):
    """由管理员登记的排版规则版本；不执行用户上传的宏或任意模板代码。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.SlugField(max_length=80)
    number = models.PositiveIntegerField()
    name = models.CharField(max_length=200)
    layout = models.JSONField()
    rights_note = models.TextField()
    source_label = models.CharField(max_length=500)
    digest = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["code", "number"], name="unique_export_template_version"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="export_template_version_positive"
            ),
            models.CheckConstraint(
                condition=~models.Q(rights_note="") & ~models.Q(source_label=""),
                name="export_template_rights_source",
            ),
        ]


class ExportSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="exports")
    manuscript_revision = models.ForeignKey("ManuscriptRevision", on_delete=models.RESTRICT)
    disclosure_revision = models.ForeignKey("DisclosureRevision", on_delete=models.RESTRICT)
    template_version = models.ForeignKey("ExportTemplateVersion", on_delete=models.RESTRICT)
    job = models.OneToOneField("Job", on_delete=models.CASCADE, related_name="export_snapshot")
    content = models.JSONField()
    digest = models.CharField(max_length=64)
    renderer_version = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "request_key"],
                name="unique_export_snapshot_request",
            ),
        ]


class ExportSource(models.Model):
    """供撤回/删除查询的规范来源关系；导出内容仍来自不可变快照。"""

    snapshot = models.ForeignKey("ExportSnapshot", on_delete=models.CASCADE, related_name="sources")
    source_version = models.ForeignKey("MaterialVersion", on_delete=models.RESTRICT)
    state_version = models.PositiveIntegerField()
    usage_version = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "source_version"], name="unique_export_source"
            ),
            models.CheckConstraint(
                condition=models.Q(state_version__gt=0, usage_version__gt=0),
                name="export_source_versions_positive",
            ),
        ]


class ExportFile(models.Model):
    snapshot = models.ForeignKey("ExportSnapshot", on_delete=models.CASCADE, related_name="files")
    generation = models.PositiveIntegerField()
    bucket = models.CharField(max_length=100)
    object_key = models.CharField(max_length=200, unique=True)
    sha256 = models.CharField(max_length=64, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    published_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "generation"], name="unique_export_file_generation"
            ),
            models.CheckConstraint(
                condition=models.Q(generation__gt=0), name="export_file_generation_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(published_at__isnull=True)
                | (models.Q(size__gt=0) & ~models.Q(sha256="")),
                name="export_file_published_content",
            ),
        ]


class ExportDownload(models.Model):
    file = models.ForeignKey("ExportFile", on_delete=models.CASCADE, related_name="downloads")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
