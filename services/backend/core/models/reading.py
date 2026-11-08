import uuid

from django.conf import settings
from django.db import models


class ReadingRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField("Job", on_delete=models.CASCADE, related_name="reading_record")
    model_output = models.JSONField()
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class ReadingRevision(models.Model):
    record = models.ForeignKey("ReadingRecord", on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    edits = models.JSONField(default=list)
    note = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["record", "number"], name="unique_reading_revision"),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="reading_positive_revision"
            ),
        ]
