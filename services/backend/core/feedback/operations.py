from core.models import (
    Feedback,
    FeedbackCandidate,
    FeedbackTask,
    FeedbackTaskRevision,
)
from core.projects.access import VersionConflict


def feedback_query(project_id):
    return Feedback.objects.filter(project_id=project_id).select_related(
        "manuscript_revision", "block_version"
    )


def candidates(project_id):
    return FeedbackCandidate.objects.filter(
        feedback__project_id=project_id, job__status="succeeded"
    ).select_related("job", "decision")


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
