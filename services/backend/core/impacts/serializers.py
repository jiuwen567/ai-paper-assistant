from rest_framework import serializers

from core.common.request_keys import fingerprint
from core.common.serializers import StrictSerializer
from core.impacts.service import change_sources, item_facts
from core.manuscripts.locations import location_data
from core.models import ImpactDecision, ImpactItem, ImpactRun, MaterialChange


class ChangeInput(StrictSerializer):
    request_key = serializers.CharField(max_length=128)
    source_version_id = serializers.UUIDField()
    replacement_id = serializers.UUIDField(allow_null=True)
    kind = serializers.ChoiceField(choices=["supplement", "correction", "withdrawal"])
    note = serializers.CharField(max_length=2000)
    state_version = serializers.IntegerField(min_value=1)
    usage_version = serializers.IntegerField(min_value=1)
    replacement_usage_version = serializers.IntegerField(min_value=1, allow_null=True)
    confirmed = serializers.BooleanField()


class ChangeSerializer(serializers.ModelSerializer):
    sources = serializers.SerializerMethodField()
    sources_token = serializers.SerializerMethodField()

    def get_sources(self, change):
        return change_sources(change)

    def get_sources_token(self, change):
        return fingerprint(self.get_sources(change))

    class Meta:
        model = MaterialChange
        fields = [
            "id",
            "kind",
            "scope",
            "note",
            "state_snapshot",
            "sources",
            "sources_token",
            "created_by",
            "created_at",
        ]


class RunInput(StrictSerializer):
    request_key = serializers.CharField(max_length=128)
    sources_token = serializers.CharField(max_length=64)


class RunSerializer(serializers.ModelSerializer):
    counts = serializers.SerializerMethodField()
    comparison = serializers.SerializerMethodField()
    sources_changed = serializers.SerializerMethodField()
    manuscript_version = serializers.IntegerField(source="manuscript_revision.number", default=None)

    def get_counts(self, run):
        return {
            origin: run.items.filter(origin=origin).count() for origin in ["registered", "model"]
        }

    def get_sources_changed(self, run):
        return run.source_snapshot != change_sources(run.change)

    def get_comparison(self, run):
        previous = run.change.runs.filter(number__lt=run.number).order_by("-number").first()
        if not previous:
            return None
        old = set(previous.items.filter(origin="registered").values_list("key", flat=True))
        new = set(run.items.filter(origin="registered").values_list("key", flat=True))
        return {
            "previous_run_id": str(previous.pk),
            "previous_number": previous.number,
            "remaining": len(old & new),
            "new": len(new - old),
            "no_longer_registered": len(old - new),
        }

    class Meta:
        model = ImpactRun
        fields = [
            "id",
            "change_id",
            "number",
            "manuscript_version",
            "source_snapshot",
            "sources_changed",
            "counts",
            "comparison",
            "created_by",
            "created_at",
        ]


class DecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImpactDecision
        fields = ["number", "state", "note", "facts_snapshot", "created_by", "created_at"]


class ItemSerializer(serializers.ModelSerializer):
    current = serializers.SerializerMethodField()
    facts_token = serializers.SerializerMethodField()
    needs_review = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    facts = serializers.SerializerMethodField()

    def get_facts(self, item):
        if not hasattr(item, "_current_facts"):
            item._current_facts = item_facts(item)
        return item._current_facts

    def get_facts_token(self, item):
        return fingerprint(self.get_facts(item))

    def get_current(self, item):
        latest = max(item.decisions.all(), key=lambda value: value.number, default=None)
        return DecisionSerializer(latest).data if latest else None

    def get_needs_review(self, item):
        latest = max(item.decisions.all(), key=lambda value: value.number, default=None)
        return (
            latest is None
            or latest.state == "pending"
            or latest.facts_snapshot != self.get_facts(item)
        )

    def get_location(self, item):
        if item.block_version_id:
            return location_data(item.run.manuscript_revision, item.block_version)
        return item.snapshot.get("location")

    class Meta:
        model = ImpactItem
        fields = [
            "id",
            "key",
            "origin",
            "job_id",
            "snapshot",
            "location",
            "current",
            "facts",
            "facts_token",
            "needs_review",
        ]


class DecisionInput(StrictSerializer):
    request_key = serializers.CharField(max_length=128)
    version = serializers.IntegerField(min_value=0)
    facts_token = serializers.CharField(max_length=64)
    state = serializers.ChoiceField(choices=["pending", "handled", "retained", "unrelated"])
    note = serializers.CharField(max_length=2000)
    confirmed = serializers.BooleanField()


class ModelInput(StrictSerializer):
    idempotency_key = serializers.CharField(max_length=128)
    policy_version = serializers.IntegerField(min_value=1)
    block_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=20)
