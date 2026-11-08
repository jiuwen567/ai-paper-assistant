from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from core.common.serializers import StrictSerializer
from core.feedback.service import unchanged
from core.manuscripts.locations import LocationInput, location_data
from core.models import (
    Feedback,
    FeedbackCandidate,
    FeedbackTask,
    FeedbackTaskRevision,
    MentorReport,
)


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


class SplitInput(LocationInput):
    idempotency_key = serializers.CharField(max_length=128)
    policy_version = serializers.IntegerField(min_value=1)


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


class CandidateDecisionInput(TaskInput):
    action = serializers.ChoiceField(choices=["accepted", "rejected"])
    confirmed = serializers.BooleanField()
    reason = serializers.CharField(max_length=2000, allow_blank=True)
    policy_version = serializers.IntegerField(min_value=1)
