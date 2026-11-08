from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.ai.configuration import model_configuration
from core.ai.sources import sources_snapshot
from core.common.api import validated
from core.common.errors import ParseFailure
from core.jobs.serializers import JobSerializer
from core.jobs.service import dispatch
from core.models import Job
from core.projects.access import VersionConflict, require_ai_action, require_project


class AIInput(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=128)
    policy_version = serializers.IntegerField(min_value=1)
    version_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=5)


class AITaskView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(AIInput, request)
        # 不允许客户端指定模型、工具、提示词、身份或输出状态。
        if set(request.data) != set(data):
            raise ValidationError("任务包含未支持的字段。")
        require_ai_action(request.user, project_id, "reading", data["policy_version"])
        versions = sorted(set(str(pk) for pk in data["version_ids"]))
        existing = project.jobs.filter(
            created_by=request.user, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if (
                existing.kind != "ai"
                or existing.policy_version != data["policy_version"]
                or existing.input_snapshot["version_ids"] != versions
            ):
                raise VersionConflict("请求键已用于不同任务。")
            return Response(JobSerializer(existing).data)
        try:
            config = model_configuration()
            sources = sources_snapshot(project.pk, versions)
        except ParseFailure as error:
            return Response({"code": error.code, "detail": error.message}, status=400)
        job = Job.objects.create(
            project=project,
            created_by=request.user,
            kind="ai",
            ai_action="reading",
            policy_version=data["policy_version"],
            idempotency_key=data["idempotency_key"],
            input_snapshot={"version_ids": versions, "model": config, "sources": sources},
        )
        transaction.on_commit(lambda: dispatch(job.pk))
        return Response(JobSerializer(job).data, status=201)


class AITraceView(APIView):
    def get(self, request, project_id, job_id):
        require_project(request.user, project_id)
        job = get_object_or_404(Job, project_id=project_id, pk=job_id, kind="ai")
        return Response(
            {
                "calls": list(
                    job.model_calls.order_by("generation", "number").values(
                        "generation",
                        "number",
                        "model",
                        "prompt_version",
                        "input_digest",
                        "status",
                        "usage",
                        "elapsed_ms",
                        "error_code",
                        "started_at",
                        "finished_at",
                    )
                ),
                "events": list(
                    job.ai_events.order_by("id").values(
                        "generation", "kind", "details", "created_at"
                    )
                ),
            }
        )
