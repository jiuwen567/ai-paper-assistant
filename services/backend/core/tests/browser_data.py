"""浏览器验收专用自制数据，只允许在 DEBUG 开发环境创建与清理随机前缀账号。"""

import json
import os
import re
import secrets
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402

from core.models import MaterialVersion, Project, ProjectPolicy, WechatIdentity  # noqa: E402


def main():
    data = json.load(sys.stdin)
    prefix = data["prefix"]
    if not settings.DEBUG or not re.fullmatch(r"e2e-[0-9a-f]{32}", prefix):
        raise ValueError("只允许清理开发环境中带随机验收前缀的专用测试数据。")
    usernames = [f"{prefix}-{role}" for role in ["owner", "reviewer", "outsider"]]
    users = get_user_model()
    with transaction.atomic():
        if data["action"] == "create":
            password = secrets.token_urlsafe(24)
            owner, reviewer, outsider = [
                users.objects.create_user(username=name, password=password) for name in usernames
            ]
            other = Project.objects.create(owner=outsider, name="自制隔离测试项目")
            ProjectPolicy.objects.create(project=other, version=1, created_by=outsider)
            print(
                json.dumps(
                    {
                        "owner": owner.username,
                        "reviewer": reviewer.username,
                        "reviewerId": reviewer.pk,
                        "password": password,
                        "otherId": str(other.pk),
                    }
                )
            )
        elif data["action"] == "binding":
            # 自制身份绕过微信服务，仅验证 Web 绑定交互，不冒充真实微信登录。
            from core.wechat import login_wechat

            print(json.dumps(login_wechat(prefix), default=str))
        elif data["action"] == "ai":
            # 浏览器展示验收走真实 Pi SDK，供应商仅使用本机受控协议样例。
            from unittest.mock import patch
            from uuid import uuid4

            from rest_framework.test import APIClient

            from core.models import Job
            from core.tests.test_ai_jobs import provider
            from worker.tasks import execute_job

            owner = users.objects.get(username=usernames[0])
            project = Project.objects.get(owner=owner)
            source = MaterialVersion.objects.get(material__project=project, status="available")
            chunk = source.parses.get(job__status="succeeded").chunks.order_by("ordinal").first()
            policy = project.policies.order_by("-version").first()
            client = APIClient(HTTP_HOST="localhost")
            client.force_authenticate(owner)
            with provider(
                lambda number, _: (
                    [("read_evidence", {"chunk_id": str(chunk.pk)})]
                    if number == 1
                    else [
                        (
                            "save_note",
                            {"text": "协议样例摘记，等待作者核对。", "chunk_ids": [str(chunk.pk)]},
                        )
                    ]
                )
            ):
                with patch("core.ai_views.dispatch"):
                    response = client.post(
                        f"/api/v1/projects/{project.pk}/ai-tasks/",
                        {
                            "idempotency_key": str(uuid4()),
                            "policy_version": policy.version,
                            "version_ids": [str(source.pk)],
                        },
                        format="json",
                    )
                if response.status_code != 201:
                    raise ValueError("无法创建浏览器测试模型任务。")
                execute_job(response.data["id"])
                if Job.objects.get(pk=response.data["id"]).status != "succeeded":
                    raise ValueError("浏览器测试模型任务失败。")
                print(json.dumps({"job_id": response.data["id"]}))
        elif data["action"] == "cleanup":
            WechatIdentity.objects.filter(open_id=prefix).delete()
            from contextlib import closing

            from core.health import s3_client

            with closing(s3_client()) as storage:
                for version in MaterialVersion.objects.filter(
                    material__project__owner__username__in=usernames
                ):
                    storage.delete_object(Bucket=version.bucket, Key=version.object_key)
            Project.objects.filter(owner__username__in=usernames).delete()
            users.objects.filter(username__in=usernames).delete()
        else:
            raise ValueError("未知操作。")


if __name__ == "__main__":
    main()
