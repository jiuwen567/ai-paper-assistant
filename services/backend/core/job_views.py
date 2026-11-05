from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import AI_ACTIONS, VersionConflict, require_ai_action, require_project
from core.jobs import MAX_ATTEMPTS, dispatch, finish
from core.models import Job, JobAttempt
from core.projects import paginated, validated


class SampleInputSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=10000)
    source_version = serializers.IntegerField(min_value=1)
    steps = serializers.IntegerField(min_value=1, max_value=10, default=3)


class JobInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["sample"])
    idempotency_key = serializers.CharField(max_length=128)
    input_snapshot = SampleInputSerializer()
    ai_action = serializers.ChoiceField(choices=["", *AI_ACTIONS], default="")
    policy_version = serializers.IntegerField(min_value=1)


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobAttempt
        fields = [
            "generation",
            "started_at",
            "finished_at",
            "status",
            "error_code",
            "error_message",
        ]


class JobSerializer(serializers.ModelSerializer):
    attempts = AttemptSerializer(many=True, read_only=True)

    class Meta:
        model = Job
        fields = [
            "id",
            "kind",
            "input_snapshot",
            "ai_action",
            "policy_version",
            "status",
            "generation",
            "lease_until",
            "progress",
            "retryable",
            "error_code",
            "error_message",
            "output",
            "created_at",
            "updated_at",
            "attempts",
        ]


class JobListView(APIView):
    def get(self, request, project_id):
        project = require_project(request.user, project_id)
        return paginated(
            project.jobs.prefetch_related("attempts").order_by("-created_at", "id"),
            JobSerializer,
            request,
        )

    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(JobInputSerializer, request)
        existing = project.jobs.filter(
            created_by=request.user, idempotency_key=data["idempotency_key"]
        ).first()
        if existing:
            if any(getattr(existing, key) != value for key, value in data.items()):
                raise VersionConflict("幂等键已用于不同输入，请使用新键。")
            return Response(JobSerializer(existing).data)
        policy = project.policies.order_by("-version").first()
        if policy.version != data["policy_version"]:
            raise VersionConflict("规则已更新，请重新加载。")
        if data["ai_action"]:
            require_ai_action(request.user, project_id, data["ai_action"], data["policy_version"])
        job = Job.objects.create(project=project, created_by=request.user, **data)
        transaction.on_commit(lambda: dispatch(job.pk))
        return Response(JobSerializer(job).data, status=201)


class JobDetailView(APIView):
    def get(self, request, project_id, job_id):
        require_project(request.user, project_id)
        job = get_object_or_404(Job, pk=job_id, project_id=project_id)
        return Response(JobSerializer(job).data)


class JobControlSerializer(serializers.Serializer):
    generation = serializers.IntegerField(min_value=0)


class JobControlView(APIView):
    @transaction.atomic
    def post(self, request, project_id, job_id, action):
        require_project(request.user, project_id, write=True, lock=True)
        job = get_object_or_404(Job.objects.select_for_update(), pk=job_id, project_id=project_id)
        if action not in ["cancel", "retry"]:
            raise ValidationError("未知任务操作。")
        generation = validated(JobControlSerializer, request)["generation"]
        if generation != job.generation:
            raise VersionConflict("执行代次已变化，请重新加载。")
        if action == "cancel":
            if job.status in [Job.Status.QUEUED, Job.Status.RUNNING]:
                finish(job, Job.Status.CANCELLED, "user_cancelled", "作者已取消。")
        elif action == "retry":
            if job.status == Job.Status.QUEUED:
                return Response(JobSerializer(job).data)
            if job.status != Job.Status.FAILED or not job.retryable:
                raise ValidationError("此任务不能重试。")
            if job.generation >= MAX_ATTEMPTS:
                raise ValidationError("已达到尝试上限，请检查故障后创建新任务。")
            # 重试保留原创建者的授权边界，不能借他人身份继续运行。
            from core.jobs import authorized

            if authorized(job):
                job.status = Job.Status.QUEUED
                job.progress = 0
                job.error_code = job.error_message = ""
                job.retryable = False
                job.save()
                transaction.on_commit(lambda: dispatch(job.pk))
        return Response(JobSerializer(job).data)
