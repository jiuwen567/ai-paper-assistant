import uuid

from django.conf import settings
from django.db import models


class MaterialChange(models.Model):
    """作者明确登记的版本关系；上传本身不改变旧版的使用状态。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_version = models.ForeignKey(
        "MaterialVersion", on_delete=models.CASCADE, related_name="changes"
    )
    replacement = models.ForeignKey(
        "MaterialVersion", null=True, on_delete=models.RESTRICT, related_name="replaces"
    )
    kind = models.CharField(max_length=16)
    scope = models.CharField(max_length=16, default="version")
    note = models.TextField()
    state_snapshot = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_version", "created_by", "request_key"],
                name="unique_material_change_request",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        kind__in=["supplement", "correction"],
                        replacement__isnull=False,
                        scope="version",
                    )
                    | models.Q(
                        kind="withdrawal",
                        replacement__isnull=True,
                        scope__in=["version", "material"],
                    )
                ),
                name="material_change_shape",
            ),
            models.CheckConstraint(condition=~models.Q(note=""), name="material_change_note"),
        ]


class ImpactRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change = models.ForeignKey("MaterialChange", on_delete=models.CASCADE, related_name="runs")
    number = models.PositiveIntegerField()
    manuscript_revision = models.ForeignKey(
        "ManuscriptRevision", null=True, on_delete=models.RESTRICT
    )
    source_snapshot = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["change", "number"], name="unique_impact_run_number"),
            models.UniqueConstraint(
                fields=["change", "created_by", "request_key"], name="unique_impact_run_request"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="impact_run_number_positive"
            ),
        ]


class ImpactItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey("ImpactRun", on_delete=models.CASCADE, related_name="items")
    key = models.CharField(max_length=80)
    origin = models.CharField(max_length=16)
    block_version = models.ForeignKey("BlockVersion", null=True, on_delete=models.RESTRICT)
    suggestion = models.ForeignKey("ExpressionSuggestion", null=True, on_delete=models.CASCADE)
    task = models.ForeignKey("FeedbackTask", null=True, on_delete=models.CASCADE)
    job = models.ForeignKey("Job", null=True, on_delete=models.CASCADE)
    snapshot = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "key"], name="unique_impact_item"),
            models.CheckConstraint(
                condition=(
                    models.Q(origin="registered", job__isnull=True)
                    | models.Q(
                        origin="model",
                        job__isnull=False,
                        block_version__isnull=False,
                        suggestion__isnull=True,
                        task__isnull=True,
                    )
                ),
                name="impact_item_origin",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        block_version__isnull=False, suggestion__isnull=True, task__isnull=True
                    )
                    | models.Q(
                        block_version__isnull=True, suggestion__isnull=False, task__isnull=True
                    )
                    | models.Q(
                        block_version__isnull=True, suggestion__isnull=True, task__isnull=False
                    )
                ),
                name="impact_item_target",
            ),
        ]


class ImpactDecision(models.Model):
    item = models.ForeignKey("ImpactItem", on_delete=models.CASCADE, related_name="decisions")
    number = models.PositiveIntegerField()
    state = models.CharField(max_length=16)
    note = models.TextField()
    facts_snapshot = models.JSONField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "number"], name="unique_impact_decision_number"
            ),
            models.UniqueConstraint(
                fields=["item", "created_by", "request_key"], name="unique_impact_decision_request"
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="impact_decision_number_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=["pending", "handled", "retained", "unrelated"]),
                name="impact_decision_state",
            ),
            models.CheckConstraint(condition=~models.Q(note=""), name="impact_decision_note"),
        ]
