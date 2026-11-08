import uuid

from django.conf import settings
from django.db import models


class ReviewRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField("Job", on_delete=models.CASCADE, related_name="review_record")
    manuscript_revision = models.ForeignKey("ManuscriptRevision", on_delete=models.RESTRICT)
    previous_review = models.ForeignKey(
        "self", null=True, on_delete=models.RESTRICT, related_name="rechecks"
    )
    summary = models.TextField()
    source_checks = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)


class ReviewFinding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    review = models.ForeignKey("ReviewRecord", on_delete=models.CASCADE, related_name="findings")
    block_version = models.ForeignKey("BlockVersion", on_delete=models.RESTRICT)
    category = models.CharField(max_length=32)
    model_output = models.JSONField()
    status = models.CharField(max_length=16, default="pending")
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "confirmed", "ignored"]),
                name="review_finding_status",
            )
        ]


class ReviewDecision(models.Model):
    finding = models.ForeignKey("ReviewFinding", on_delete=models.CASCADE, related_name="decisions")
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=16)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["finding", "number"], name="unique_review_decision"),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="review_decision_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "confirmed", "ignored"]),
                name="review_decision_status",
            ),
        ]
