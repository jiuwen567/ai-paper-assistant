from django.db import transaction
from django.utils import timezone

from core.ai.configuration import MAX_CALLS
from core.ai.state import valid_locked
from core.ai.tools import handle_tool
from core.common.digests import digest
from core.common.errors import ParseFailure
from core.jobs.service import finish, lock_job
from core.models import Job, ModelCall


class AIRun:
    def __init__(self, job):
        self.job_id, self.generation = job.pk, job.generation
        self.call = None
        self.calls = self.tools = 0
        self.read_ids = set()
        self.read_characters = 0
        self.proposals = []
        self.reading = None
        self.review = None
        self.expression = None
        self.impact = None
        self.impact_read = False
        self.feedback = None
        self.feedback_read = False
        self.manuscript_read = False

    @transaction.atomic
    def handle(self, message):
        job = lock_job(self.job_id)
        if not valid_locked(job, self.generation):
            return None
        kind = message.get("type")
        details = {}
        result = {}
        if kind == "model_start":
            if self.call is not None or self.calls >= MAX_CALLS:
                raise ParseFailure("model_call_limit", "模型调用达到上限。")
            self.calls += 1
            self.call = ModelCall.objects.create(
                job=job,
                generation=self.generation,
                number=self.calls,
                model=job.input_snapshot["model"]["model"],
                prompt_version=job.input_snapshot["model"]["prompt_version"],
                input_digest=digest(job.input_snapshot),
            )
            details = {"number": self.calls}
        elif kind == "model_end":
            if self.call is None:
                raise ParseFailure("runner_protocol", "模型执行协议异常。")
            usage = message.get("usage")
            if usage is not None and (
                not isinstance(usage, dict)
                or set(usage) != {"input", "output", "cache_read", "cache_write"}
                or any(
                    type(value) is not int or not 0 <= value <= 100_000_000
                    for value in usage.values()
                )
            ):
                raise ParseFailure("runner_protocol", "模型用量格式异常。")
            self.call.usage = usage
            self.call.finished_at = timezone.now()
            self.call.elapsed_ms = max(
                0, int((self.call.finished_at - self.call.started_at).total_seconds() * 1000)
            )
            self.call.status = "succeeded" if message.get("ok") is True else "failed"
            self.call.error_code = "" if message.get("ok") is True else "model_failed"
            self.call.save()
            self.call = None
            if message.get("ok") is not True:
                finish(
                    job, Job.Status.FAILED, "model_failed", "模型调用失败，请检查模型服务。", True
                )
                return None
            details = {"number": self.calls}
        elif kind == "tool":
            details, result = handle_tool(self, job, message)
            if details is None:
                return result
        elif kind == "done":
            if (
                message.get("success") is not True
                or self.call
                or not (
                    self.proposals
                    or self.reading
                    or self.review
                    or self.expression
                    or self.feedback
                    or self.impact
                )
            ):
                raise ParseFailure("result_invalid", "模型未提交有效的待核对结果。")
            if self.impact is not None:
                from core.impacts.ai import publish_output

                job.output = publish_output(job, self.impact)
            elif self.feedback is not None:
                from core.feedback.service import publish_split

                job.output = publish_split(job, self.feedback)
            elif self.expression is not None:
                from core.expressions.service import publish_expression

                job.output = publish_expression(job, self.expression)
            elif self.review is not None:
                from core.reviews.service import publish_review

                job.output = publish_review(job, self.review)
            elif self.reading is not None:
                from core.reading.service import publish_reading

                job.output = publish_reading(job, self.reading)
            else:
                job.output = {"status": "pending", "proposals": self.proposals}
            job.progress = 100
            finish(job, Job.Status.SUCCEEDED)
            return {}
        elif kind == "validation_error":
            if message.get("reason") not in (None, "missing_submission"):
                raise ParseFailure("runner_protocol", "模型执行协议异常。")
            if (
                job.input_snapshot.get("purpose")
                not in ["reading", "comparison", "review", "expression", "feedback", "impact"]
                or self.reading is not None
                or self.review is not None
                or self.expression is not None
                or self.feedback is not None
                or self.impact is not None
                or self.call is not None
                or not self.calls
            ):
                raise ParseFailure("tool_rejected", "模型工具调用未通过校验。")
            self.tools += 1
            if self.tools > 32:
                raise ParseFailure("tool_call_limit", "工具调用达到上限。")
            details = {
                "code": "result_unsubmitted"
                if message.get("reason") == "missing_submission"
                else "result_schema_invalid",
                "number": self.tools,
            }
        elif kind == "tool_error":
            raise ParseFailure("tool_rejected", "模型工具调用未通过校验。")
        else:
            raise ParseFailure("runner_protocol", "模型执行协议异常。")
        job.ai_events.create(generation=self.generation, kind=kind, details=details)
        return result
