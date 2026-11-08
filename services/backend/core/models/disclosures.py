from django.conf import settings
from django.db import models


class DisclosureRevision(models.Model):
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="disclosures")
    number = models.PositiveIntegerField()
    text = models.TextField(blank=True)
    external_uses = models.JSONField(default=list)
    verified = models.BooleanField(default=False)
    facts = models.JSONField()
    facts_token = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "number"], name="unique_disclosure_revision"
            ),
            models.UniqueConstraint(
                fields=["project", "created_by", "request_key"], name="unique_disclosure_request"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="disclosure_positive_revision"
            ),
        ]
