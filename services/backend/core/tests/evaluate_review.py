"""真实模型诊断评测，仅用公开自制数据；不把空结果或请求成功当作判断正确。"""

import argparse
import json
import os
import time
from contextlib import closing
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
from core.health import s3_client  # noqa: E402
from core.library import default_bibliography  # noqa: E402
from core.models import Job, MaterialVersion, Project, ProjectPolicy, ReviewRecord  # noqa: E402
from core.reviews import REVIEW_PROMPT  # noqa: E402
from core.tests.reading_samples import SAMPLES  # noqa: E402
from core.tests.test_manuscripts import payload, save  # noqa: E402
from core.tests.test_materials import intent, path, upload  # noqa: E402
from core.tests.test_parse_jobs import create  # noqa: E402
from worker.tasks import execute_job  # noqa: E402

CASES = [
    (
        "overclaim",
        ["催化剂甲在所有温度与浓度下都保持 0.8 mmol/(L·min) 的速率，可直接用于实际装置。"],
        0,
        "应指出超出单一模拟条件和适用范围。",
    ),
    (
        "contradiction",
        ["本次模拟实验进行了三次重复。", "上述同一次模拟实验仅进行了一次重复。"],
        None,
        "应指出同一实验重复次数的前后矛盾。",
    ),
    (
        "supported_control",
        [
            "在 25 摄氏度、初始底物浓度 1 mmol/L、pH 7 的模拟体系中，"
            "催化剂甲平均速率为 0.8 mmol/(L·min)。"
            "该记录未测试长期稳定性，不外推到实际装置。"
        ],
        0,
        "材料已支持所述范围，不应报结论越界或与原文矛盾。",
    ),
    (
        "abstract_gap",
        ["材料 Q 的相关研究证明，该材料已在实际生产中显著提高了加工效率。"],
        2,
        "仅有摘要的颜色观察，不支持实际生产效率的结论。",
    ),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not settings.DEBUG:
        raise SystemExit("仅允许在 DEBUG 开发环境运行自制评测。")
    prefix = "review-eval-" + uuid4().hex
    user = get_user_model().objects.create_user(username=prefix)
    project = Project.objects.create(owner=user, name=prefix)
    ProjectPolicy.objects.create(
        project=project,
        version=1,
        created_by=user,
        verified=True,
        source="自制公开评测",
        source_version="v1",
        allowed_actions=["review"],
    )
    client = APIClient(HTTP_HOST="localhost")
    client.force_authenticate(user)
    context = (client, project, user)
    reports = []
    try:
        with (
            override_settings(AI_MODEL=args.model, AI_BASE_URL=args.base_url),
            patch("core.parse_views.dispatch"),
            patch("core.review_views.dispatch"),
        ):
            versions = []
            for title, scope, text in SAMPLES:
                data = text.encode()
                version = intent(
                    context, data=data, name=title + ".txt", title=title, request_key=str(uuid4())
                )
                assert upload(context, version, data).status_code == 200
                response = client.put(
                    path(project, f"files/{version.pk}/bibliography/"),
                    {
                        "version": 0,
                        "snapshot": {**default_bibliography(version), "source_scope": scope},
                    },
                    format="json",
                )
                assert response.status_code == 200
                run = create(context, version, key=str(uuid4()))
                execute_job(str(run.job_id))
                assert Job.objects.get(pk=run.job_id).status == "succeeded"
                versions.append(str(version.pk))
            for number, (name, texts, source_index, expected) in enumerate(CASES):
                manuscript = save(
                    context,
                    payload(
                        number,
                        research={"question": "虚构材料的效果范围", "method": "", "result": ""},
                        blocks=[
                            {"id": str(uuid4()), "heading_level": 0, "text": text} for text in texts
                        ],
                    ),
                )
                assert manuscript.status_code == 200
                start = time.monotonic()
                with transaction.atomic():
                    response = client.post(
                        path(project, "reviews/tasks/"),
                        {
                            "idempotency_key": str(uuid4()),
                            "policy_version": 1,
                            "manuscript_version": number + 1,
                            "block_ids": [block["id"] for block in manuscript.data["blocks"]],
                            "version_ids": [versions[source_index]]
                            if source_index is not None
                            else [],
                        },
                        format="json",
                    )
                    assert response.status_code == 201
                    tool_calls = []
                    original = AIRun.handle

                    def trace(run, event):
                        if event.get("type") == "tool":
                            tool_calls.append({"name": event["name"], "args": event.get("args")})
                        return original(run, event)

                    with patch.object(AIRun, "handle", trace):
                        execute_job(response.data["id"])
                job = Job.objects.get(pk=response.data["id"])
                result = ReviewRecord.objects.filter(job=job).first()
                report = {
                    "case": name,
                    "tools": tool_calls,
                    "expected": expected,
                    "model": args.model,
                    "prompt_version": job.input_snapshot["model"]["prompt_version"],
                    "prompt_characters": len(REVIEW_PROMPT),
                    "status": job.status,
                    "error_code": job.error_code,
                    "elapsed_seconds": round(time.monotonic() - start, 2),
                    "calls": list(
                        job.model_calls.order_by("number").values(
                            "number", "status", "usage", "elapsed_ms", "error_code"
                        )
                    ),
                    "summary": result.summary if result else None,
                    "source_checks": result.source_checks if result else None,
                    "findings": [finding.model_output for finding in result.findings.all()]
                    if result
                    else None,
                }
                reports.append(report)
                Path(args.output).write_text(json.dumps(reports, ensure_ascii=False, indent=2))
                print(
                    json.dumps(
                        {
                            key: report[key]
                            for key in ["case", "status", "error_code", "elapsed_seconds"]
                        }
                    ),
                    flush=True,
                )
    finally:
        with closing(s3_client()) as storage:
            for version in MaterialVersion.objects.filter(material__project=project):
                storage.delete_object(Bucket=version.bucket, Key=version.object_key)
        project.delete()
        user.delete()


if __name__ == "__main__":
    main()
