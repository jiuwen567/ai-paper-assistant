"""用自制导师意见核对真实模型的拆分；候选不自动加入待办。"""

import argparse
import json
import os
import time
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from django.test import override_settings  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from core.ai_jobs import AIRun  # noqa: E402
from core.models import FeedbackCandidate, FeedbackTask, Job, Project, ProjectPolicy  # noqa: E402
from core.tests.evaluation_cases import FEEDBACK_CASES as CASES  # noqa: E402
from core.tests.evaluation_cases import FEEDBACK_EXTRA_CASES  # noqa: E402
from core.tests.evaluation_cleanup import remove_project  # noqa: E402
from core.tests.test_feedback import create_feedback, create_split  # noqa: E402
from worker.tasks import execute_job  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--expanded", action="store_true", help="补测合法要求后置及只有禁止性约束的意见"
    )
    args = parser.parse_args()
    if not settings.DEBUG:
        raise SystemExit("仅允许在 DEBUG 开发环境运行自制评测。")
    prefix = "feedback-eval-" + uuid4().hex
    user = get_user_model().objects.create_user(username=prefix)
    project = Project.objects.create(owner=user, name=prefix)
    ProjectPolicy.objects.create(project=project, version=1, created_by=user)
    client = APIClient(HTTP_HOST="localhost")
    client.force_authenticate(user)
    context = (client, project, user)
    reports = []
    try:
        with override_settings(AI_MODEL=args.model, AI_BASE_URL=args.base_url):
            for name, text, expected in [*CASES, *(FEEDBACK_EXTRA_CASES if args.expanded else [])]:
                feedback, _ = create_feedback(context, text=text)
                start = time.monotonic()
                with transaction.atomic():
                    with patch("core.feedback_views.dispatch"):
                        job, _ = create_split(context, feedback)
                    tools = []
                    handle = AIRun.handle

                    def trace(run, event):
                        entry = None
                        if event.get("type") in ["tool", "validation_error"]:
                            entry = {"event": event}
                            tools.append(entry)
                        try:
                            result = handle(run, event)
                        except Exception as exc:
                            if entry is not None:
                                entry["error_code"] = getattr(exc, "code", type(exc).__name__)
                            raise
                        if entry is not None:
                            entry["result"] = result
                        return result

                    with patch.object(AIRun, "handle", trace):
                        execute_job(str(job.pk))
                job = Job.objects.get(pk=job.pk)
                report = {
                    "case": name,
                    "tools": tools,
                    "feedback": text,
                    "expected": expected,
                    "model": args.model,
                    "prompt_version": job.input_snapshot["model"]["prompt_version"],
                    "status": job.status,
                    "error_code": job.error_code,
                    "elapsed_seconds": round(time.monotonic() - start, 2),
                    "calls": list(
                        job.model_calls.order_by("number").values(
                            "number", "status", "usage", "elapsed_ms", "error_code"
                        )
                    ),
                    "summary": (job.output or {}).get("summary"),
                    "candidates": list(
                        FeedbackCandidate.objects.filter(job=job).values_list(
                            "model_output", flat=True
                        )
                    ),
                    "confirmed_task_count": FeedbackTask.objects.filter(
                        feedback__project=project
                    ).count(),
                }
                reports.append(report)
                Path(args.output).write_text(json.dumps(reports, ensure_ascii=False, indent=2))
                print(
                    json.dumps(
                        {
                            key: report[key]
                            for key in ("case", "status", "error_code", "elapsed_seconds")
                        }
                    ),
                    flush=True,
                )
    finally:
        remove_project(project, user)


if __name__ == "__main__":
    main()
