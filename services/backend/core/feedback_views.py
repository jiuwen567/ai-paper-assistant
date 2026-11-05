from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_ai_action, require_project
from core.ai_jobs import model_configuration
from core.feedback import (
    LocationInput,
    fingerprint,
    location_data,
    select_location,
    split_snapshot,
    unchanged,
)
from core.job_views import JobSerializer
from core.jobs import dispatch
from core.library import searchable_chunks
from core.models import (
    Feedback,
    FeedbackCandidate,
    FeedbackCandidateDecision,
    FeedbackTask,
    FeedbackTaskRevision,
    Job,
    MentorReport,
)
from core.parsing import ParseFailure
from core.projects import paginated, validated
from core.reading import StrictSerializer


class FeedbackInput(LocationInput):
    request_key = serializers.CharField(max_length=128)
    text = serializers.CharField(max_length=5000)
    source_label = serializers.CharField(max_length=500)
    source_chunk_id = serializers.UUIDField(allow_null=True)


class FeedbackSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    recording = serializers.SerializerMethodField()

    def get_location(self, record):
        return location_data(record.manuscript_revision, record.block_version)

    def get_recording(self, record):
        return "author_transcription"

    class Meta:
        model = Feedback
        fields = [
            "id",
            "text",
            "source_label",
            "source_chunk_id",
            "location",
            "recording",
            "created_by",
            "created_at",
        ]


def feedback_query(project_id):
    return Feedback.objects.filter(project_id=project_id).select_related(
        "manuscript_revision", "block_version"
    )


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


class SplitInput(LocationInput):
    idempotency_key = serializers.CharField(max_length=128)
    policy_version = serializers.IntegerField(min_value=1)


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


class CandidateSerializer(serializers.ModelSerializer):
    input_changed = serializers.SerializerMethodField()
    decision = serializers.SerializerMethodField()

    def get_input_changed(self, candidate):
        return not unchanged(candidate.job)

    def get_decision(self, candidate):
        decision = getattr(candidate, "decision", None)
        return (
            {
                "action": decision.action,
                "reason": decision.reason,
                "task_id": str(decision.task_id) if decision.task_id else None,
                "created_by": decision.created_by_id,
                "created_at": decision.created_at,
            }
            if decision
            else None
        )

    class Meta:
        model = FeedbackCandidate
        fields = [
            "id",
            "feedback_id",
            "job_id",
            "model_output",
            "input_changed",
            "decision",
            "created_at",
        ]


def candidates(project_id):
    return FeedbackCandidate.objects.filter(
        feedback__project_id=project_id, job__status="succeeded"
    ).select_related("job", "decision")


class FeedbackCandidatesView(APIView):
    def get(self, request, project_id, feedback_id):
        require_project(request.user, project_id)
        get_object_or_404(feedback_query(project_id), pk=feedback_id)
        return paginated(
            candidates(project_id).filter(feedback_id=feedback_id).order_by("-created_at", "id"),
            CandidateSerializer,
            request,
        )


class TaskInput(LocationInput):
    request_key = serializers.CharField(max_length=128)
    title = serializers.CharField(max_length=200)
    instruction = serializers.CharField(max_length=2000)


class ProgressInput(TaskInput):
    version = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=["todo", "doing", "completed", "dropped"])
    note = serializers.CharField(max_length=4000, allow_blank=True)
    result_kind = serializers.ChoiceField(choices=["pending", "modified", "no_change"])

    def validate(self, data):
        data = super().validate(data)
        if data["status"] in ["completed", "dropped"] and not data["note"].strip():
            raise ValidationError("完成或不再处理时须记录处理说明。")
        if data["status"] == "completed":
            if data["result_kind"] == "pending" or (
                data["result_kind"] == "modified" and data["block_id"] is None
            ):
                raise ValidationError("请关联实际修改位置，或说明无需改稿。")
        elif data["result_kind"] != "pending":
            raise ValidationError("尚未完成的任务不能登记完成结果。")
        return data


class MentorInput(StrictSerializer):
    request_key = serializers.CharField(max_length=128)
    version = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=["confirmed", "changes_requested"])
    text = serializers.CharField(max_length=3000)
    source_label = serializers.CharField(max_length=500)


class MentorSerializer(serializers.ModelSerializer):
    task_version = serializers.IntegerField(source="revision.number")
    recording = serializers.CharField(default="author_transcription", read_only=True)

    class Meta:
        model = MentorReport
        fields = [
            "id",
            "task_version",
            "recording",
            "status",
            "text",
            "source_label",
            "created_by",
            "created_at",
        ]


class ProgressSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    mentor_reports = serializers.SerializerMethodField()

    def get_location(self, revision):
        return location_data(revision.manuscript_revision, revision.block_version)

    def get_mentor_reports(self, revision):
        return MentorSerializer(
            revision.mentor_reports.order_by("-created_at", "-id"), many=True
        ).data

    class Meta:
        model = FeedbackTaskRevision
        fields = [
            "number",
            "title",
            "instruction",
            "status",
            "note",
            "result_kind",
            "location",
            "mentor_reports",
            "created_by",
            "created_at",
        ]


class TaskSerializer(serializers.ModelSerializer):
    current = serializers.SerializerMethodField()
    candidate_id = serializers.SerializerMethodField()
    original_location = serializers.SerializerMethodField()

    def get_current(self, task):
        return ProgressSerializer(
            task.revisions.select_related("manuscript_revision", "block_version")
            .order_by("-number")
            .first()
        ).data

    def get_candidate_id(self, task):
        decision = getattr(task, "candidate_decision", None)
        return str(decision.candidate_id) if decision else None

    def get_original_location(self, task):
        first = task.revisions.select_related("manuscript_revision", "block_version").get(number=1)
        return location_data(first.manuscript_revision, first.block_version)

    class Meta:
        model = FeedbackTask
        fields = [
            "id",
            "feedback_id",
            "candidate_id",
            "current",
            "original_location",
            "created_by",
            "created_at",
        ]


def task_query(project_id):
    return FeedbackTask.objects.filter(feedback__project_id=project_id).select_related(
        "candidate_decision"
    )


def create_task(feedback, user, data, request_digest, revision, block):
    if FeedbackTask.objects.filter(created_by=user, request_key=data["request_key"]).exists():
        raise VersionConflict("请求键已用于其他修改任务。")
    task = FeedbackTask.objects.create(
        feedback=feedback,
        created_by=user,
        request_key=data["request_key"],
        request_digest=request_digest,
    )
    FeedbackTaskRevision.objects.create(
        task=task,
        number=1,
        title=data["title"],
        instruction=data["instruction"],
        manuscript_revision=revision,
        block_version=block,
        created_by=user,
        request_key=data["request_key"],
        request_digest=request_digest,
    )
    return task


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


class CandidateDecisionInput(TaskInput):
    action = serializers.ChoiceField(choices=["accepted", "rejected"])
    confirmed = serializers.BooleanField()
    reason = serializers.CharField(max_length=2000, allow_blank=True)
    policy_version = serializers.IntegerField(min_value=1)


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
