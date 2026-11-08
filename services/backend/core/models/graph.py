import uuid

from django.conf import settings
from django.db import models


class GraphState(models.Model):
    project = models.OneToOneField("Project", primary_key=True, on_delete=models.CASCADE)
    revision = models.PositiveBigIntegerField(default=0)
    applied_revision = models.PositiveBigIntegerField(default=0)
    last_error = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class GraphTombstone(models.Model):
    # 不外键依赖项目：项目删除后仍须保留可重试的投影清理事件。
    project_id = models.UUIDField(primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)


class GraphEvent(models.Model):
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="graph_events")
    revision = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=100, blank=True)
    next_attempt_at = models.DateTimeField(null=True)
    request_key = models.CharField(max_length=128, null=True)
    requested_revision = models.PositiveBigIntegerField(null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "revision"], name="unique_graph_event"),
            models.UniqueConstraint(fields=["project", "request_key"], name="unique_graph_rebuild"),
            models.CheckConstraint(condition=models.Q(revision__gt=0), name="graph_event_positive"),
        ]
        indexes = [models.Index(fields=["processed_at", "next_attempt_at"])]


class EvidenceLink(models.Model):
    """固定原稿主张和来源原话；核对决定单独追加，不把模型候选视为作者确认。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="evidence_links")
    manuscript_revision = models.ForeignKey("ManuscriptRevision", on_delete=models.RESTRICT)
    block_version = models.ForeignKey("BlockVersion", on_delete=models.RESTRICT)
    chunk = models.ForeignKey("SourceChunk", on_delete=models.RESTRICT)
    bibliography_revision = models.ForeignKey(
        "BibliographyRevision", null=True, on_delete=models.RESTRICT
    )
    claim = models.TextField()
    claim_start = models.PositiveIntegerField()
    evidence_quote = models.TextField()
    evidence_start = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "request_key"], name="unique_evidence_link_request"
            ),
        ]


class EvidenceLinkRevision(models.Model):
    link = models.ForeignKey("EvidenceLink", on_delete=models.CASCADE, related_name="decisions")
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=16)
    kind = models.CharField(max_length=16)
    note = models.TextField(blank=True)
    source_state_version = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["link", "number"], name="unique_evidence_link_version"),
            models.UniqueConstraint(
                fields=["link", "created_by", "request_key"], name="unique_evidence_link_decision"
            ),
            models.CheckConstraint(condition=models.Q(number__gt=0), name="evidence_link_positive"),
            models.CheckConstraint(
                condition=models.Q(state__in=["confirmed", "withdrawn"]),
                name="evidence_link_state",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=["supports", "contradicts", "context"]),
                name="evidence_link_kind",
            ),
        ]
