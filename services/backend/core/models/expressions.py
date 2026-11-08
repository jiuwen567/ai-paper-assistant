import uuid

from django.conf import settings
from django.db import models


class ExpressionSuggestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey("Job", on_delete=models.CASCADE, related_name="expression_suggestions")
    manuscript_revision = models.ForeignKey("ManuscriptRevision", on_delete=models.RESTRICT)
    block_version = models.ForeignKey("BlockVersion", on_delete=models.RESTRICT)
    model_output = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class ExpressionDecision(models.Model):
    suggestion = models.OneToOneField(
        "ExpressionSuggestion", on_delete=models.CASCADE, related_name="decision"
    )
    action = models.CharField(max_length=16)
    text = models.TextField(blank=True)
    reason = models.TextField(blank=True)
    meaning_confirmed = models.BooleanField(default=False)
    policy_version = models.PositiveIntegerField()
    manuscript_revision = models.ForeignKey(
        "ManuscriptRevision", null=True, on_delete=models.RESTRICT
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_expression_decision_request"
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=["accepted", "edited", "rejected"]),
                name="expression_decision_action",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(action="rejected", manuscript_revision__isnull=True)
                    | models.Q(
                        action__in=["accepted", "edited"],
                        manuscript_revision__isnull=False,
                        meaning_confirmed=True,
                    )
                ),
                name="expression_decision_result",
            ),
        ]


class ManuscriptCitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    block_version = models.ForeignKey(
        "BlockVersion", on_delete=models.CASCADE, related_name="citations"
    )
    chunk = models.ForeignKey("SourceChunk", on_delete=models.RESTRICT)
    bibliography_revision = models.ForeignKey(
        "BibliographyRevision", null=True, on_delete=models.RESTRICT
    )
    snapshot = models.JSONField()
    fingerprint = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["block_version", "fingerprint"], name="unique_manuscript_citation"
            ),
        ]
