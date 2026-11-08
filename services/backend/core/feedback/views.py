from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.ai.configuration import model_configuration
from core.common.api import paginated, validated
from core.common.errors import ParseFailure
from core.common.request_keys import fingerprint
from core.feedback.operations import candidates, create_task, feedback_query, task_query
from core.feedback.serializers import (
    CandidateDecisionInput,
    CandidateSerializer,
    FeedbackInput,
    FeedbackSerializer,
    MentorInput,
    MentorSerializer,
    ProgressInput,
    ProgressSerializer,
    SplitInput,
    TaskInput,
    TaskSerializer,
)
from core.feedback.service import split_snapshot, unchanged
from core.jobs.serializers import JobSerializer
from core.jobs.service import dispatch
from core.library.service import searchable_chunks
from core.manuscripts.locations import location_data, select_location
from core.models import (
    Feedback,
    FeedbackCandidateDecision,
    FeedbackTaskRevision,
    Job,
    MentorReport,
)
from core.projects.access import VersionConflict, require_ai_action, require_project


class FeedbackListView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        return paginated(
            feedback_query(project_id).order_by("-created_at", "id"), FeedbackSerializer, request
        )

    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(FeedbackInput, request)
        request_digest = fingerprint(data)
        existing = (
            feedback_query(project_id)
            .filter(created_by=request.user, request_key=data["request_key"])
            .first()
        )
        if existing:
            if existing.request_digest != request_digest:
                raise VersionConflict("请求键已用于不同意见。")
            return Response(FeedbackSerializer(existing).data)
        revision, block = select_location(project_id, data)
        chunk = (
            get_object_or_404(searchable_chunks(project_id), pk=data["source_chunk_id"])
            if data["source_chunk_id"]
            else None
        )
        record = Feedback.objects.create(
            project=project,
            text=data["text"],
            source_label=data["source_label"],
            source_chunk=chunk,
            manuscript_revision=revision,
            block_version=block,
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=request_digest,
        )
        return Response(FeedbackSerializer(record).data, status=201)


class FeedbackDetailView(APIView):
    def get(self, request, project_id, feedback_id):
        require_project(request.user, project_id)
        return Response(
            FeedbackSerializer(get_object_or_404(feedback_query(project_id), pk=feedback_id)).data
        )


class FeedbackSplitView(APIView):
    @transaction.atomic
    def post(self, request, project_id, feedback_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        feedback = get_object_or_404(feedback_query(project_id), pk=feedback_id)
        data = validated(SplitInput, request)
        require_ai_action(request.user, project_id, "feedback", data["policy_version"])
        request_digest = fingerprint({**data, "feedback_id": str(feedback_id)})
        existing = project.jobs.filter(
            created_by=request.user, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if (
                existing.ai_action != "feedback"
                or existing.input_snapshot.get("request_digest") != request_digest
            ):
                raise VersionConflict("请求键已用于不同任务。")
            return Response(JobSerializer(existing).data)
        revision, block = select_location(project_id, data)
        try:
            config = model_configuration("feedback")
            snapshot = split_snapshot(feedback, revision, block)
        except ParseFailure as error:
            return Response({"code": error.code, "detail": error.message}, status=400)
        job = Job.objects.create(
            project=project,
            created_by=request.user,
            kind="ai",
            ai_action="feedback",
            policy_version=data["policy_version"],
            idempotency_key=data["idempotency_key"],
            input_snapshot={
                "purpose": "feedback",
                "feedback": snapshot,
                "model": config,
                "request_digest": request_digest,
                "manuscript": snapshot["manuscript"],
                "sources": [],
                "version_ids": [],
            },
        )
        transaction.on_commit(lambda: dispatch(job.pk))
        return Response(JobSerializer(job).data, status=201)


class FeedbackCandidatesView(APIView):
    def get(self, request, project_id, feedback_id):
        require_project(request.user, project_id)
        get_object_or_404(feedback_query(project_id), pk=feedback_id)
        return paginated(
            candidates(project_id).filter(feedback_id=feedback_id).order_by("-created_at", "id"),
            CandidateSerializer,
            request,
        )


class FeedbackTasksView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        query = task_query(project_id)
        if request.query_params.get("feedback_id"):
            value = serializers.UUIDField().run_validation(request.query_params["feedback_id"])
            query = query.filter(feedback_id=value)
        status = request.query_params.get("status")
        if status:
            if status not in ["todo", "doing", "completed", "dropped"]:
                raise ValidationError("任务状态无效。")
            latest = FeedbackTaskRevision.objects.filter(task=OuterRef("pk")).order_by("-number")
            query = query.annotate(latest_status=Subquery(latest.values("status")[:1])).filter(
                latest_status=status
            )
        return paginated(query.order_by("-created_at", "id"), TaskSerializer, request)


class FeedbackTaskCreateView(APIView):
    @transaction.atomic
    def post(self, request, project_id, feedback_id):
        require_project(request.user, project_id, write=True, lock=True)
        feedback = get_object_or_404(feedback_query(project_id), pk=feedback_id)
        data = validated(TaskInput, request)
        request_digest = fingerprint({**data, "feedback_id": str(feedback_id)})
        existing = (
            task_query(project_id)
            .filter(created_by=request.user, request_key=data["request_key"])
            .first()
        )
        if existing:
            if existing.request_digest != request_digest:
                raise VersionConflict("请求键已用于不同任务。")
            return Response(TaskSerializer(existing).data)
        revision, block = select_location(project_id, data)
        task = create_task(feedback, request.user, data, request_digest, revision, block)
        return Response(TaskSerializer(task).data, status=201)


class FeedbackCandidateDecisionView(APIView):
    @transaction.atomic
    def post(self, request, project_id, candidate_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        candidate = get_object_or_404(candidates(project_id), pk=candidate_id)
        data = validated(CandidateDecisionInput, request)
        if project.policies.order_by("-version").first().version != data["policy_version"]:
            raise VersionConflict("项目规则已变化，请重新核对。")
        request_digest = fingerprint({**data, "candidate_id": str(candidate_id)})
        existing = FeedbackCandidateDecision.objects.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.candidate_id != candidate_id or existing.request_digest != request_digest:
                raise VersionConflict("请求键已用于不同决定。")
            return Response(CandidateSerializer(candidate).data)
        if hasattr(candidate, "decision"):
            raise VersionConflict("候选任务已有作者决定。")
        task = None
        if data["action"] == "accepted":
            require_ai_action(request.user, project_id, "feedback", data["policy_version"])
            if not data["confirmed"]:
                raise ValidationError("请先核对任务与原始意见。")
            if not unchanged(candidate.job):
                raise VersionConflict(
                    "拆分时的原稿或来源已变化，请重新拆分，或手动登记核对后的任务。"
                )
            revision, block = select_location(project_id, data)
            task = create_task(
                candidate.feedback, request.user, data, request_digest, revision, block
            )
        FeedbackCandidateDecision.objects.create(
            candidate=candidate,
            task=task,
            action=data["action"],
            reason=data["reason"],
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=request_digest,
        )
        candidate = candidates(project_id).get(pk=candidate_id)
        return Response(CandidateSerializer(candidate).data)


class FeedbackTaskView(APIView):
    def get(self, request, project_id, task_id):
        require_project(request.user, project_id)
        return Response(TaskSerializer(get_object_or_404(task_query(project_id), pk=task_id)).data)

    @transaction.atomic
    def post(self, request, project_id, task_id):
        require_project(request.user, project_id, write=True, lock=True)
        task = get_object_or_404(task_query(project_id), pk=task_id)
        data = validated(ProgressInput, request)
        request_digest = fingerprint(data)
        existing = task.revisions.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.request_digest != request_digest:
                raise VersionConflict("请求键已用于不同进度。")
            return Response(TaskSerializer(task).data)
        latest = task.revisions.order_by("-number").first()
        if data["version"] != latest.number:
            raise VersionConflict("任务处理已有新版本，请刷新后核对，保留当前说明。")
        revision, block = select_location(project_id, data)
        if data["result_kind"] == "modified":
            original = task.revisions.get(number=1)
            if original.block_version_id == block.pk:
                raise ValidationError("所选正文块与任务初始版本相同，不能登记为实际修改。")
        FeedbackTaskRevision.objects.create(
            task=task,
            number=latest.number + 1,
            manuscript_revision=revision,
            block_version=block,
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=request_digest,
            **{key: data[key] for key in ["title", "instruction", "status", "note", "result_kind"]},
        )
        return Response(TaskSerializer(task).data)


class FeedbackTaskHistoryView(APIView):
    def get(self, request, project_id, task_id):
        require_project(request.user, project_id)
        task = get_object_or_404(task_query(project_id), pk=task_id)
        return paginated(
            task.revisions.select_related("manuscript_revision", "block_version").order_by(
                "-number"
            ),
            ProgressSerializer,
            request,
        )


class MentorReportsView(APIView):
    @transaction.atomic
    def post(self, request, project_id, task_id):
        require_project(request.user, project_id, write=True, lock=True)
        task = get_object_or_404(task_query(project_id), pk=task_id)
        data = validated(MentorInput, request)
        request_digest = fingerprint({**data, "task_id": str(task_id)})
        existing = MentorReport.objects.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.revision.task_id != task.pk or existing.request_digest != request_digest:
                raise VersionConflict("请求键已用于不同导师回复。")
            return Response(MentorSerializer(existing).data)
        revision = (
            task.revisions.select_related("manuscript_revision", "block_version")
            .order_by("-number")
            .first()
        )
        if data["version"] != revision.number:
            raise VersionConflict("处理版本已变化，不能把旧回复记在新修改上。")
        if data["status"] == "confirmed" and revision.status != "completed":
            raise ValidationError("请先登记作者处理结果，再转录导师对该结果的确认。")
        location = location_data(revision.manuscript_revision, revision.block_version)
        if location and location["stale"]:
            raise VersionConflict("处理位置已失效，请先重新关联后记录导师回复。")
        report = MentorReport.objects.create(
            revision=revision,
            status=data["status"],
            text=data["text"],
            source_label=data["source_label"],
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=request_digest,
        )
        return Response(MentorSerializer(report).data, status=201)
