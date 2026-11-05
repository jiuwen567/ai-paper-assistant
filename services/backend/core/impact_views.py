from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_project
from core.feedback import fingerprint, location_data
from core.impacts import change_sources, create_run, item_facts
from core.models import ImpactDecision, ImpactItem, ImpactRun, MaterialChange, MaterialVersion
from core.projects import paginated, validated
from core.reading import StrictSerializer


def changes(pid):
    return MaterialChange.objects.filter(source_version__material__project_id=pid).select_related(
        "source_version__material", "replacement__material"
    )


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


class ChangesView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        return paginated(
            changes(project_id).order_by("-created_at", "id"), ChangeSerializer, request
        )

    @transaction.atomic
    def post(self, request, project_id):
        require_project(request.user, project_id, write=True, lock=True)
        data = validated(ChangeInput, request)
        existing = (
            changes(project_id)
            .filter(
                source_version_id=data["source_version_id"],
                created_by=request.user,
                request_key=data["request_key"],
            )
            .first()
        )
        request_digest = fingerprint(data)
        if existing:
            if existing.request_digest != request_digest:
                raise VersionConflict("请求键已用于其他材料变更。")
            return Response(ChangeSerializer(existing).data)
        if not data["confirmed"]:
            raise ValidationError("请核对变更类型、文件版本和说明。")
        source = get_object_or_404(
            MaterialVersion.objects.select_related("material"),
            pk=data["source_version_id"],
            material__project_id=project_id,
            status="available",
        )
        if (
            source.material.access_state != "active"
            or source.material.state_version != data["state_version"]
            or source.usage_version != data["usage_version"]
        ):
            raise VersionConflict("材料状态已变化，请刷新后核对。")
        if source.usage_state == "withdrawn" or (
            data["kind"] != "withdrawal" and source.usage_state != "active"
        ):
            raise VersionConflict("此版本已更正或撤回，请选择当前有效版本。")
        replacement = None
        if data["kind"] == "withdrawal":
            if data["replacement_id"] or data["replacement_usage_version"]:
                raise ValidationError("撤回不指定替代版本。")
        else:
            replacement = get_object_or_404(
                MaterialVersion,
                pk=data["replacement_id"],
                material=source.material,
                number__gt=source.number,
                status="available",
            )
            if (
                replacement.usage_state != "active"
                or replacement.usage_version != data["replacement_usage_version"]
            ):
                raise VersionConflict("新版状态已变化，请刷新后核对。")
        if data["kind"] != "supplement":
            source.usage_state = "corrected" if data["kind"] == "correction" else "withdrawn"
            source.usage_version += 1
            source.save(update_fields=["usage_state", "usage_version", "updated_at"])
        change = MaterialChange(
            source_version=source,
            replacement=replacement,
            kind=data["kind"],
            note=data["note"],
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=request_digest,
        )
        change.state_snapshot = change_sources(change)
        change.save()
        return Response(ChangeSerializer(change).data, status=201)


class ChangeView(APIView):
    def get(self, request, project_id, change_id):
        require_project(request.user, project_id)
        return Response(ChangeSerializer(get_object_or_404(changes(project_id), pk=change_id)).data)


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


class RunsView(APIView):
    def get(self, request, project_id, change_id):
        require_project(request.user, project_id)
        change = get_object_or_404(changes(project_id), pk=change_id)
        return paginated(
            change.runs.select_related("manuscript_revision").order_by("-number"),
            RunSerializer,
            request,
        )

    @transaction.atomic
    def post(self, request, project_id, change_id):
        require_project(request.user, project_id, write=True, lock=True)
        change = get_object_or_404(changes(project_id), pk=change_id)
        data = validated(RunInput, request)
        existing = change.runs.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.request_digest != fingerprint(data):
                raise VersionConflict("请求键已用于其他影响查询。")
            return Response(RunSerializer(existing).data)
        if fingerprint(change_sources(change)) != data["sources_token"]:
            raise VersionConflict("材料已有新状态，请刷新后生成清单。")
        return Response(RunSerializer(create_run(change, request.user, data)).data, status=201)


def runs(pid):
    return ImpactRun.objects.filter(
        change__source_version__material__project_id=pid
    ).select_related(
        "manuscript_revision", "change__source_version__material", "change__replacement__material"
    )


class RunView(APIView):
    def get(self, request, project_id, run_id):
        require_project(request.user, project_id)
        return Response(RunSerializer(get_object_or_404(runs(project_id), pk=run_id)).data)


def items(pid):
    return (
        ImpactItem.objects.filter(run__change__source_version__material__project_id=pid)
        .select_related(
            "run__change__source_version__material",
            "run__change__replacement__material",
            "run__manuscript_revision",
            "block_version",
            "suggestion__decision",
            "task",
            "job",
        )
        .prefetch_related("decisions")
    )


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


class ItemsView(APIView):
    def get(self, request, project_id, run_id):
        require_project(request.user, project_id)
        get_object_or_404(runs(project_id), pk=run_id)
        return paginated(
            items(project_id)
            .filter(run_id=run_id)
            .order_by("-origin", "snapshot__location__position", "key"),
            ItemSerializer,
            request,
        )


class DecisionInput(StrictSerializer):
    request_key = serializers.CharField(max_length=128)
    version = serializers.IntegerField(min_value=0)
    facts_token = serializers.CharField(max_length=64)
    state = serializers.ChoiceField(choices=["pending", "handled", "retained", "unrelated"])
    note = serializers.CharField(max_length=2000)
    confirmed = serializers.BooleanField()


class ItemView(APIView):
    def get(self, request, project_id, item_id):
        require_project(request.user, project_id)
        return Response(ItemSerializer(get_object_or_404(items(project_id), pk=item_id)).data)

    @transaction.atomic
    def post(self, request, project_id, item_id):
        require_project(request.user, project_id, write=True, lock=True)
        item = get_object_or_404(items(project_id), pk=item_id)
        data = validated(DecisionInput, request)
        existing = item.decisions.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.request_digest != fingerprint(data):
                raise VersionConflict("请求键已用于其他处理决定。")
            return Response(ItemSerializer(item).data)
        latest = max(item.decisions.all(), key=lambda value: value.number, default=None)
        facts = item_facts(item)
        if (latest.number if latest else 0) != data["version"] or fingerprint(facts) != data[
            "facts_token"
        ]:
            raise VersionConflict(
                "原稿、材料或处理记录已变化，请刷新后重新核对，填写内容不会自动提交。"
            )
        if not data["confirmed"]:
            raise ValidationError("处理结果须由作者核对确认。")
        if item.origin == "model" and item.job.status != "succeeded":
            raise VersionConflict("模型任务未成功，不能处理候选。")
        ImpactDecision.objects.create(
            item=item,
            number=data["version"] + 1,
            state=data["state"],
            note=data["note"],
            facts_snapshot=facts,
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=fingerprint(data),
        )
        return Response(ItemSerializer(items(project_id).get(pk=item.pk)).data)


class ItemHistoryView(APIView):
    def get(self, request, project_id, item_id):
        require_project(request.user, project_id)
        item = get_object_or_404(items(project_id), pk=item_id)
        return paginated(item.decisions.order_by("-number"), DecisionSerializer, request)


class ModelInput(StrictSerializer):
    idempotency_key = serializers.CharField(max_length=128)
    policy_version = serializers.IntegerField(min_value=1)
    block_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=20)


class ImpactModelView(APIView):
    def get(self, request, project_id, run_id):
        from core.job_views import JobSerializer
        from core.models import Job

        require_project(request.user, project_id)
        get_object_or_404(runs(project_id), pk=run_id)
        return paginated(
            Job.objects.filter(
                project_id=project_id,
                input_snapshot__purpose="impact",
                input_snapshot__impact__run_id=str(run_id),
            ).order_by("-created_at", "id"),
            JobSerializer,
            request,
        )

    @transaction.atomic
    def post(self, request, project_id, run_id):
        from core.access import require_ai_action
        from core.ai_jobs import model_configuration
        from core.impact_ai import model_snapshot
        from core.job_views import JobSerializer
        from core.jobs import dispatch
        from core.models import Job
        from core.parsing import ParseFailure

        project = require_project(request.user, project_id, write=True, lock=True)
        run = get_object_or_404(runs(project_id), pk=run_id)
        data = validated(ModelInput, request)
        require_ai_action(request.user, project_id, "review", data["policy_version"])
        if len(set(data["block_ids"])) != len(data["block_ids"]):
            raise ValidationError("正文块不能重复选择。")
        request_digest = fingerprint({**data, "run_id": str(run_id)})
        existing = project.jobs.filter(
            created_by=request.user, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if (
                existing.input_snapshot.get("purpose") != "impact"
                or existing.input_snapshot.get("request_digest") != request_digest
            ):
                raise VersionConflict("请求键已用于不同任务。")
            return Response(JobSerializer(existing).data)
        try:
            config = model_configuration("impact")
            snapshot, _ = model_snapshot(run, data["block_ids"])
        except ParseFailure as error:
            return Response({"code": error.code, "detail": error.message}, status=400)
        job = Job.objects.create(
            project=project,
            created_by=request.user,
            kind="ai",
            ai_action="review",
            policy_version=data["policy_version"],
            idempotency_key=data["idempotency_key"],
            input_snapshot={
                "purpose": "impact",
                "impact": snapshot,
                "model": config,
                "request_digest": request_digest,
                "manuscript": snapshot["manuscript"],
                "sources": [],
                "version_ids": [],
            },
        )
        transaction.on_commit(lambda: dispatch(job.pk))
        return Response(JobSerializer(job).data, status=201)
