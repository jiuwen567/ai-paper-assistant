import uuid

from django.conf import settings
from django.db import models


class Bibliography(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_version = models.OneToOneField(
        "MaterialVersion", on_delete=models.CASCADE, related_name="bibliography"
    )
    revision = models.PositiveIntegerField(default=0)


class BibliographyRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bibliography = models.ForeignKey(
        "Bibliography", on_delete=models.CASCADE, related_name="revisions"
    )
    number = models.PositiveIntegerField()
    snapshot = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["bibliography", "number"], name="unique_bibliography_revision"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="bibliography_positive_revision"
            ),
        ]


class EvidenceCard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chunk = models.ForeignKey(
        "SourceChunk", on_delete=models.CASCADE, related_name="evidence_cards"
    )
    bibliography_revision = models.ForeignKey("BibliographyRevision", on_delete=models.RESTRICT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=128)
    request_snapshot = models.JSONField()
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_evidence_request"
            ),
        ]


class EvidenceNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evidence = models.ForeignKey("EvidenceCard", on_delete=models.CASCADE, related_name="notes")
    number = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    tags = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evidence", "number"], name="unique_evidence_note"),
            models.CheckConstraint(condition=models.Q(number__gt=0), name="note_positive_revision"),
        ]
