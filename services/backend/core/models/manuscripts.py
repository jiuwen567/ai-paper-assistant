import uuid

from django.conf import settings
from django.db import models


class Manuscript(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.OneToOneField("Project", on_delete=models.CASCADE, related_name="manuscript")
    current_revision = models.ForeignKey(
        "ManuscriptRevision", null=True, on_delete=models.SET_NULL, related_name="+"
    )


class ContentBlock(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manuscript = models.ForeignKey("Manuscript", on_delete=models.CASCADE, related_name="blocks")
    imported_from = models.ForeignKey(
        "MaterialVersion", null=True, on_delete=models.CASCADE, related_name="imported_blocks"
    )


class BlockVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    block = models.ForeignKey("ContentBlock", on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    text = models.TextField()
    heading_level = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["block", "number"], name="unique_block_version"),
            models.CheckConstraint(condition=models.Q(number__gt=0), name="block_version_positive"),
            models.CheckConstraint(
                condition=models.Q(heading_level__lte=9), name="block_heading_level"
            ),
        ]


class ManuscriptRevision(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    manuscript = models.ForeignKey("Manuscript", on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    research = models.JSONField(default=dict)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)
    origin = models.CharField(max_length=16, default="edit")
    source = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["manuscript", "number"], name="unique_manuscript_revision"
            ),
            models.UniqueConstraint(
                fields=["manuscript", "created_by", "request_key"], name="unique_manuscript_request"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="manuscript_revision_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(
                    origin__in=["edit", "import", "restore", "expression", "cleanup"]
                ),
                name="manuscript_revision_origin",
            ),
        ]


class RevisionBlock(models.Model):
    revision = models.ForeignKey(
        "ManuscriptRevision", on_delete=models.CASCADE, related_name="items"
    )
    block = models.ForeignKey("ContentBlock", on_delete=models.CASCADE)
    block_version = models.ForeignKey("BlockVersion", on_delete=models.RESTRICT)
    position = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "position"], name="unique_revision_position"
            ),
            models.UniqueConstraint(fields=["revision", "block"], name="unique_revision_block"),
        ]
