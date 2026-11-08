import uuid

from django.conf import settings
from django.db import models


class Feedback(models.Model):
    """首版仅保存作者录入的原始意见，不代表导师本人提交。"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="feedback")
    text = models.TextField()
    source_label = models.CharField(max_length=500)
    source_chunk = models.ForeignKey("SourceChunk", null=True, on_delete=models.RESTRICT)
    manuscript_revision = models.ForeignKey(
        "ManuscriptRevision", null=True, on_delete=models.RESTRICT
    )
    block_version = models.ForeignKey("BlockVersion", null=True, on_delete=models.RESTRICT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "created_by", "request_key"], name="unique_feedback_request"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(manuscript_revision__isnull=True, block_version__isnull=True)
                    | models.Q(manuscript_revision__isnull=False, block_version__isnull=False)
                ),
                name="feedback_location_pair",
            ),
        ]


class FeedbackCandidate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feedback = models.ForeignKey("Feedback", on_delete=models.CASCADE, related_name="candidates")
    job = models.ForeignKey("Job", on_delete=models.CASCADE, related_name="feedback_candidates")
    model_output = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class FeedbackTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    feedback = models.ForeignKey("Feedback", on_delete=models.CASCADE, related_name="tasks")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_feedback_task_request"
            )
        ]


class FeedbackCandidateDecision(models.Model):
    candidate = models.OneToOneField(
        "FeedbackCandidate", on_delete=models.CASCADE, related_name="decision"
    )
    task = models.OneToOneField(
        "FeedbackTask", null=True, on_delete=models.CASCADE, related_name="candidate_decision"
    )
    action = models.CharField(max_length=16)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_feedback_decision_request"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(action="accepted", task__isnull=False)
                    | models.Q(action="rejected", task__isnull=True)
                ),
                name="feedback_decision_result",
            ),
        ]


class FeedbackTaskRevision(models.Model):
    task = models.ForeignKey("FeedbackTask", on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    instruction = models.TextField()
    status = models.CharField(max_length=16, default="todo")
    note = models.TextField(blank=True)
    result_kind = models.CharField(max_length=16, default="pending")
    manuscript_revision = models.ForeignKey(
        "ManuscriptRevision", null=True, on_delete=models.RESTRICT
    )
    block_version = models.ForeignKey("BlockVersion", null=True, on_delete=models.RESTRICT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "number"], name="unique_feedback_task_revision"
            ),
            models.UniqueConstraint(
                fields=["task", "created_by", "request_key"],
                name="unique_feedback_progress_request",
            ),
            models.CheckConstraint(
                condition=models.Q(number__gt=0), name="feedback_task_positive_revision"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["todo", "doing", "completed", "dropped"]),
                name="feedback_task_status",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(manuscript_revision__isnull=True, block_version__isnull=True)
                    | models.Q(manuscript_revision__isnull=False, block_version__isnull=False)
                ),
                name="feedback_task_location_pair",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="completed", result_kind="modified", block_version__isnull=False
                    )
                    | models.Q(status="completed", result_kind="no_change")
                    | (~models.Q(status="completed") & models.Q(result_kind="pending"))
                ),
                name="feedback_task_completion",
            ),
        ]


class MentorReport(models.Model):
    """作者转录的导师回复，仅对明确的任务处理版本有效。"""

    revision = models.ForeignKey(
        "FeedbackTaskRevision", on_delete=models.CASCADE, related_name="mentor_reports"
    )
    status = models.CharField(max_length=24)
    text = models.TextField()
    source_label = models.CharField(max_length=500)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    request_key = models.CharField(max_length=128)
    request_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "request_key"], name="unique_mentor_report_request"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["confirmed", "changes_requested"]),
                name="mentor_report_status",
            ),
        ]
