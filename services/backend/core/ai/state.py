from django.db import transaction

from core.ai.configuration import model_configuration
from core.ai.sources import sources_snapshot
from core.common.errors import ParseFailure
from core.jobs.service import active, finish, heartbeat, lock_job
from core.models import Job


def valid_locked(job, generation):
    if not active(job, generation):
        return False
    try:
        unchanged = (
            model_configuration(job.input_snapshot.get("purpose")) == job.input_snapshot["model"]
            and sources_snapshot(
                job.project_id,
                job.input_snapshot["version_ids"],
                allow_empty=job.input_snapshot.get("purpose")
                in ["review", "expression", "feedback", "impact"],
            )
            == job.input_snapshot["sources"]
        )
        if unchanged and job.input_snapshot.get("purpose") == "impact":
            from core.impacts.ai import unchanged as impact_unchanged

            unchanged = impact_unchanged(job)
        if unchanged and job.input_snapshot.get("purpose") == "feedback":
            from core.feedback.service import unchanged as feedback_unchanged

            unchanged = feedback_unchanged(job)
        if unchanged and job.input_snapshot.get("purpose") in ["review", "expression"]:
            from core.reviews.service import unchanged as manuscript_unchanged

            unchanged = manuscript_unchanged(job)
            if unchanged and job.input_snapshot.get("purpose") == "expression":
                from core.expressions.service import input_changed

                unchanged = not input_changed(job)
    except ParseFailure:
        unchanged = False
    if not unchanged:
        finish(
            job,
            Job.Status.CANCELLED,
            "ai_input_changed",
            "原稿、资料或模型配置已变化，请重新创建任务。",
        )
        return False
    return True


@transaction.atomic
def checkpoint(job_id, generation):
    job = lock_job(job_id)
    return valid_locked(job, generation) and heartbeat(job_id, generation, 10)
