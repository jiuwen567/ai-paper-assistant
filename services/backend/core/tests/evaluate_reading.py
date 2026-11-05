"""显式运行真实模型评测，仅创建并清理随机前缀的自制开发数据。"""

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
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.db import transaction  # noqa: E402
from django.test import override_settings  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from core.ai_jobs import AIRun  # noqa: E402
from core.health import s3_client  # noqa: E402
from core.library import default_bibliography  # noqa: E402
from core.models import Job, MaterialVersion, Project, ProjectPolicy, ReadingRecord  # noqa: E402
from core.tests.reading_samples import SAMPLES  # noqa: E402
from worker.tasks import execute_job  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not settings.DEBUG:
        raise SystemExit("评测只允许在 DEBUG 开发环境运行。")
    prefix = "reading-eval-" + uuid4().hex
    user = get_user_model().objects.create_user(username=prefix)
    project = Project.objects.create(owner=user, name=prefix)
    ProjectPolicy.objects.create(
        project=project,
        version=1,
        created_by=user,
        verified=True,
        source="公开自制软件验收",
        source_version="v1",
        allowed_actions=["reading", "comparison"],
    )
    client = APIClient(HTTP_HOST="localhost")
    client.force_authenticate(user)
    base = f"/api/v1/projects/{project.pk}/"
    records = []

    def post(suffix, body, format="json"):
        response = client.post(base + suffix, body, format=format)
        if response.status_code not in [200, 201]:
            raise ValueError(f"评测请求失败：{suffix} / {response.status_code}")
        return response.data

    try:
        with (
            override_settings(AI_MODEL=args.model, AI_BASE_URL=args.base_url),
            patch("core.parse_views.dispatch"),
            patch("core.reading_views.dispatch"),
        ):
            versions = []
            for title, scope, text in SAMPLES:
                content = text.encode()
                data = post(
                    "uploads/",
                    {
                        "title": title,
                        "request_key": str(uuid4()),
                        "file_name": title + ".txt",
                        "size": len(content),
                    },
                )
                post(
                    f"uploads/{data['id']}/",
                    {"file": SimpleUploadedFile(title + ".txt", content)},
                    format="multipart",
                )
                version = MaterialVersion.objects.get(pk=data["id"])
                response = client.put(
                    base + f"files/{version.pk}/bibliography/",
                    {
                        "version": 0,
                        "snapshot": {**default_bibliography(version), "source_scope": scope},
                    },
                    format="json",
                )
                assert response.status_code == 200
                parsed = post(f"files/{version.pk}/parses/", {"idempotency_key": str(uuid4())})
                execute_job(parsed["job"]["id"])
                assert Job.objects.get(pk=parsed["job"]["id"]).status == "succeeded"
                versions.append(str(version.pk))
            for name, purpose, selected in [
                ("single", "reading", versions[:1]),
                ("different_conditions", "comparison", versions[:2]),
                ("abstract_only", "reading", versions[2:]),
            ]:
                start = time.monotonic()
                # 专用任务提交与同步执行共用事务，避免开发 scheduler 抢先领取。
                with transaction.atomic():
                    task = post(
                        "reading/tasks/",
                        {
                            "idempotency_key": str(uuid4()),
                            "purpose": purpose,
                            "policy_version": 1,
                            "version_ids": selected,
                        },
                    )
                    tool_calls = []
                    original_handle = AIRun.handle

                    def traced_handle(run, event):
                        if event.get("type") == "tool":
                            tool_calls.append({"name": event["name"], "args": event.get("args")})
                        return original_handle(run, event)

                    with patch.object(AIRun, "handle", traced_handle):
                        execute_job(task["id"])
                job = Job.objects.get(pk=task["id"])
                result = ReadingRecord.objects.filter(job=job).first()
                record = {
                    "case": name,
                    "model": args.model,
                    "status": job.status,
                    "error_code": job.error_code,
                    "elapsed_seconds": round(time.monotonic() - start, 2),
                    "calls": list(
                        job.model_calls.order_by("number").values(
                            "number", "status", "usage", "elapsed_ms", "error_code"
                        )
                    ),
                    "result": result.model_output if result else None,
                    "tools": tool_calls,
                }
                records.append(record)
                Path(args.output).write_text(json.dumps(records, ensure_ascii=False, indent=2))
                print(
                    json.dumps(
                        {
                            key: record[key]
                            for key in ["case", "status", "error_code", "elapsed_seconds"]
                        }
                    ),
                    flush=True,
                )
    finally:
        # 仅清理由本次随机评测项目拥有的对象与数据。
        with closing(s3_client()) as storage:
            for version in MaterialVersion.objects.filter(material__project=project):
                storage.delete_object(Bucket=version.bucket, Key=version.object_key)
        project.delete()
        user.delete()


if __name__ == "__main__":
    main()
