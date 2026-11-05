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

from core.models import ExportFile, MaterialVersion, Project, ProjectPolicy, WechatIdentity  # noqa: E402


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
        elif data["action"] in ["ai", "reading", "review", "expression", "feedback", "impact"]:
            # 浏览器展示验收走真实 Pi SDK，供应商仅使用本机受控协议样例。
            from unittest.mock import patch
            from uuid import uuid4

            from rest_framework.test import APIClient

            from core.models import Job
            from core.tests.test_ai_jobs import provider
            from worker.tasks import execute_job

            owner = users.objects.get(username=usernames[0])
            project = Project.objects.get(owner=owner)
            available = list(
                MaterialVersion.objects.filter(
                    material__project=project, status="available"
                ).order_by("created_at")
            )
            policy = project.policies.order_by("-version").first()
            client = APIClient(HTTP_HOST="localhost")
            client.force_authenticate(owner)
            endpoint = "ai-tasks/"
            body = {
                "idempotency_key": str(uuid4()),
                "policy_version": policy.version,
                "version_ids": [str(source.pk) for source in available],
            }
            if data["action"] == "impact":

                def respond(number, _):
                    return (
                        [("read_impact", {})]
                        if number == 1
                        else [("submit_impact", data["output"])]
                    )

                endpoint = f"impact-runs/{data['run_id']}/model/"
                body = data["payload"]
            elif data["action"] == "feedback":
                from core.tests.test_feedback import output

                def respond(number, _):
                    return (
                        [("read_feedback", {})] if number == 1 else [("submit_feedback", output())]
                    )

                endpoint = f"feedback/{data['feedback_id']}/split/"
                body = data["payload"]
            elif data["action"] == "expression":
                from core.manuscripts import revision_data
                from core.models import Manuscript
                from core.tests.test_expressions import output_for, respond_with

                manuscript = revision_data(Manuscript.objects.get(project=project).current_revision)
                source = (
                    (available[0], available[0].parses.get(job__status="succeeded"))
                    if available
                    else None
                )
                respond = respond_with(output_for(manuscript, source), source)
                endpoint = "expressions/tasks/"
                body = data["payload"]
            elif data["action"] == "review":
                from core.manuscripts import revision_data
                from core.tests.test_reviews import finding_output, respond_with

                manuscript = revision_data(project.manuscript.current_revision)
                source = (
                    (available[0], available[0].parses.get(job__status="succeeded"))
                    if available
                    else None
                )
                result = (
                    finding_output(manuscript, source)
                    if not data.get("recheck")
                    else {
                        "findings": [],
                    }
                )
                respond = respond_with(result, source)
                endpoint = "reviews/tasks/"
                body = data["payload"]
            elif data["action"] == "reading":
                from core.tests.test_reading import extraction, respond_with

                sources = [
                    (source, source.parses.get(job__status="succeeded")) for source in available
                ]
                respond = respond_with(sources, extraction(sources))
                endpoint = "reading/tasks/"
                body["purpose"] = "comparison" if len(sources) > 1 else "reading"
            else:
                chunk = (
                    available[0]
                    .parses.get(job__status="succeeded")
                    .chunks.order_by("ordinal")
                    .first()
                )

                def respond(number, _):
                    return (
                        [("read_evidence", {"chunk_id": str(chunk.pk)})]
                        if number == 1
                        else [
                            (
                                "save_note",
                                {
                                    "text": "协议样例摘记，等待作者核对。",
                                    "chunk_ids": [str(chunk.pk)],
                                },
                            )
                        ]
                    )

            with provider(respond):
                with (
                    patch("core.ai_views.dispatch"),
                    patch("core.reading_views.dispatch"),
                    patch("core.review_views.dispatch"),
                    patch("core.expression_views.dispatch"),
                    patch("core.feedback_views.dispatch"),
                    patch("core.jobs.dispatch"),
                ):
                    response = client.post(
                        f"/api/v1/projects/{project.pk}/{endpoint}", body, format="json"
                    )
                if response.status_code != 201:
                    raise ValueError("无法创建浏览器测试模型任务。")
                execute_job(response.data["id"])
                job = Job.objects.get(pk=response.data["id"])
                if job.status != "succeeded":
                    raise ValueError(f"浏览器测试模型任务失败：{job.status}/{job.error_code}。")
                print(
                    json.dumps({"job_id": response.data["id"], "task": response.data}, default=str)
                )
        elif data["action"] == "cleanup":
            WechatIdentity.objects.filter(open_id=prefix).delete()
            from contextlib import closing

            from core.health import s3_client

            with closing(s3_client()) as storage:
                for version in MaterialVersion.objects.filter(
                    material__project__owner__username__in=usernames
                ):
                    storage.delete_object(Bucket=version.bucket, Key=version.object_key)
                for artifact in ExportFile.objects.filter(
                    snapshot__project__owner__username__in=usernames
                ):
                    storage.delete_object(Bucket=artifact.bucket, Key=artifact.object_key)
            from core.graph import purge_projection
            from core.models import CleanupRequest, GraphTombstone

            project_ids = list(
                Project.objects.select_for_update()
                .filter(owner__username__in=usernames)
                .values_list("pk", flat=True)
            )
            Project.objects.filter(pk__in=project_ids).delete()
            cleanups = CleanupRequest.objects.filter(created_by__username__in=usernames)
            project_ids = list(
                set(project_ids) | set(cleanups.values_list("project_id", flat=True))
            )
            for project_id in project_ids:
                purge_projection(project_id)
            GraphTombstone.objects.filter(project_id__in=project_ids).delete()
            with closing(s3_client()) as storage:
                for cleanup in cleanups:
                    for item in cleanup.items.filter(kind="object"):
                        storage.delete_object(
                            Bucket=item.target["bucket"], Key=item.target["object_key"]
                        )
            cleanups.delete()
            users.objects.filter(username__in=usernames).delete()
        else:
            raise ValueError("未知操作。")


if __name__ == "__main__":
    main()
