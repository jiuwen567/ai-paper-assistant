from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_ai_action, require_project
from core.ai_jobs import model_configuration, sources_snapshot
from core.job_views import JobSerializer
from core.jobs import dispatch
from core.models import Job, ReviewDecision, ReviewFinding, ReviewRecord
from core.parsing import ParseFailure
from core.projects import paginated, validated
from core.reading import StrictSerializer
from core.reviews import CATEGORIES, manuscript_snapshot, review_changed


class ReviewTaskInput(StrictSerializer):
    idempotency_key = serializers.CharField(max_length=128)
    policy_version = serializers.IntegerField(min_value=1)
    manuscript_version = serializers.IntegerField(min_value=1, max_value=2147483647)
    block_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=20)
    version_ids = serializers.ListField(child=serializers.UUIDField(), max_length=5)
    question = serializers.CharField(
        max_length=500, default="核对证据缺口、结论范围、前后矛盾与引用问题。"
    )
    previous_review_id = serializers.UUIDField(allow_null=True, default=None)

    def validate(self, data):
        for key in ["block_ids", "version_ids"]:
            if len(data[key]) != len(set(data[key])):
                raise ValidationError("审阅范围不能重复。")
            data[key] = sorted(str(pk) for pk in data[key])
        data["previous_review_id"] = (
            str(data["previous_review_id"]) if data["previous_review_id"] else None
        )
        return data


class ReviewTaskView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(ReviewTaskInput, request)
        require_ai_action(request.user, project_id, "review", data["policy_version"])
        keys = ["manuscript_version", "block_ids", "version_ids", "question", "previous_review_id"]
        existing = project.jobs.filter(
            created_by=request.user, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if (
                existing.kind != "ai"
                or existing.ai_action != "review"
                or existing.policy_version != data["policy_version"]
                or any(existing.input_snapshot.get(key) != data[key] for key in keys)
            ):
                raise VersionConflict("请求键已用于不同任务。")
            return Response(JobSerializer(existing).data)
        if data["previous_review_id"]:
            get_object_or_404(ReviewRecord, pk=data["previous_review_id"], job__project=project)
        try:
            config = model_configuration("review")
            manuscript = manuscript_snapshot(
                project.pk, data["manuscript_version"], data["block_ids"]
            )
            sources = sources_snapshot(project.pk, data["version_ids"], allow_empty=True)
        except ParseFailure as error:
            return Response(
                {"code": error.code, "detail": error.message},
                status=409 if error.code == "review_manuscript_changed" else 400,
            )
        job = Job.objects.create(
            project=project,
            created_by=request.user,
            kind="ai",
            ai_action="review",
            policy_version=data["policy_version"],
            idempotency_key=data["idempotency_key"],
            input_snapshot={
                **{key: data[key] for key in keys},
                "purpose": "review",
                "manuscript": manuscript,
                "sources": sources,
                "model": config,
            },
        )
        transaction.on_commit(lambda: dispatch(job.pk))
        return Response(JobSerializer(job).data, status=201)


class ReviewSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField()
    manuscript_version = serializers.IntegerField(source="manuscript_revision.number")
    block_ids = serializers.JSONField(source="job.input_snapshot.block_ids")
    version_ids = serializers.JSONField(source="job.input_snapshot.version_ids")
    question = serializers.CharField(source="job.input_snapshot.question")
    input_changed = serializers.SerializerMethodField()
    findings_count = serializers.SerializerMethodField()
    research_limited = serializers.BooleanField(
        source="job.input_snapshot.manuscript.research_limited"
    )
    recheck_tasks = serializers.SerializerMethodField()

    def get_input_changed(self, record):
        return review_changed(record)

    def get_findings_count(self, record):
        return record.findings.count()

    def get_recheck_tasks(self, record):
        return [
            {"id": str(job.pk), "status": job.status, "output": job.output}
            for job in Job.objects.filter(
                project_id=record.job.project_id, input_snapshot__previous_review_id=str(record.pk)
            ).order_by("-created_at")[:10]
        ]

    class Meta:
        model = ReviewRecord
        fields = [
            "id",
            "job_id",
            "manuscript_version",
            "block_ids",
            "version_ids",
            "question",
            "summary",
            "source_checks",
            "input_changed",
            "findings_count",
            "research_limited",
            "previous_review_id",
            "recheck_tasks",
            "created_at",
        ]


class ReviewListView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        return paginated(
            ReviewRecord.objects.filter(job__project_id=project_id, job__status="succeeded")
            .select_related("job", "manuscript_revision")
            .order_by("-created_at", "id"),
            ReviewSerializer,
            request,
        )


class ReviewDetailView(APIView):
    def get(self, request, project_id, review_id):
        require_project(request.user, project_id)
        record = get_object_or_404(
            ReviewRecord.objects.select_related("job", "manuscript_revision"),
            pk=review_id,
            job__project_id=project_id,
            job__status="succeeded",
        )
        return Response(ReviewSerializer(record).data)


class DecisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewDecision
        fields = ["number", "status", "reason", "created_by", "created_at"]


class FindingSerializer(serializers.ModelSerializer):
    author_decision = serializers.SerializerMethodField()
    manuscript_text = serializers.CharField(source="block_version.text")
    manuscript_version = serializers.IntegerField(source="review.manuscript_revision.number")

    def get_author_decision(self, finding):
        value = finding.decisions.order_by("-number").first()
        return DecisionSerializer(value).data if value else None

    class Meta:
        model = ReviewFinding
        fields = [
            "id",
            "category",
            "model_output",
            "status",
            "revision",
            "author_decision",
            "manuscript_text",
            "manuscript_version",
        ]


class ReviewFindingsView(APIView):
    def get(self, request, project_id, review_id):
        require_project(request.user, project_id)
        record = get_object_or_404(
            ReviewRecord, pk=review_id, job__project_id=project_id, job__status="succeeded"
        )
        query = record.findings.select_related(
            "block_version", "review__manuscript_revision"
        ).order_by("id")
        for key, choices in [
            ("status", ["pending", "confirmed", "ignored"]),
            ("category", CATEGORIES),
        ]:
            value = request.query_params.get(key)
            if value:
                if value not in choices:
                    raise ValidationError("问题筛选条件无效。")
                query = query.filter(**{key: value})
        return paginated(query, FindingSerializer, request)


class DecisionInput(StrictSerializer):
    version = serializers.IntegerField(min_value=0)
    status = serializers.ChoiceField(choices=["pending", "confirmed", "ignored"])
    reason = serializers.CharField(max_length=2000, allow_blank=True)

    def validate(self, data):
        if data["status"] == "ignored" and not data["reason"].strip():
            raise ValidationError("忽略问题时请记录原因。")
        return data


class ReviewFindingView(APIView):
    def get(self, request, project_id, finding_id):
        require_project(request.user, project_id)
        finding = get_object_or_404(
            ReviewFinding.objects.select_related("block_version", "review__manuscript_revision"),
            pk=finding_id,
            review__job__project_id=project_id,
        )
        return Response(FindingSerializer(finding).data)

    @transaction.atomic
    def patch(self, request, project_id, finding_id):
        require_project(request.user, project_id, write=True, lock=True)
        finding = get_object_or_404(
            ReviewFinding.objects.select_related(
                "block_version", "review__job", "review__manuscript_revision"
            ).select_for_update(),
            pk=finding_id,
            review__job__project_id=project_id,
        )
        data = validated(DecisionInput, request)
        if data["status"] == "confirmed" and review_changed(finding.review):
            raise VersionConflict("原稿或依据已变化，请先复查。")
        latest = finding.decisions.order_by("-number").first()
        if finding.revision != data["version"]:
            if (
                latest
                and latest.created_by_id == request.user.pk
                and latest.number == data["version"] + 1
                and latest.status == data["status"]
                and latest.reason == data["reason"]
            ):
                return Response(FindingSerializer(finding).data)
            raise VersionConflict("问题状态已更新，请重新加载。")
        finding.revision += 1
        finding.status = data["status"]
        finding.save(update_fields=["revision", "status"])
        ReviewDecision.objects.create(
            finding=finding,
            number=finding.revision,
            created_by=request.user,
            status=data["status"],
            reason=data["reason"],
        )
        return Response(FindingSerializer(finding).data)
