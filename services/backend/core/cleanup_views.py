from django.db import connection, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_active_user, require_project
from core.ai_jobs import digest
from core.cleanup import create_cleanup, dispatch
from core.cleanup_plan import Plan
from core.models import CleanupRequest, Material
from core.projects import paginated, validated
from core.reading import StrictSerializer


class Selection(StrictSerializer):
    scope = serializers.ChoiceField(choices=["project", "material"])
    material_id = serializers.UUIDField(allow_null=True)

    def validate(self, data):
        if (data["scope"] == "project") != (data["material_id"] is None):
            raise ValidationError("请明确选择整个项目或单项材料。")
        return data


class Confirmation(Selection):
    preview_token = serializers.RegexField(r"^[a-f0-9]{64}$")
    request_key = serializers.CharField(max_length=128)
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if not value:
            raise ValidationError("请核对删除范围和不可撤销的影响。")
        return value


class Retry(StrictSerializer):
    generation = serializers.IntegerField(min_value=0)


class CleanupSerializer(serializers.ModelSerializer):
    counts = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    attempts = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = CleanupRequest
        fields = [
            "id",
            "project_id",
            "material_id",
            "scope",
            "status",
            "generation",
            "error_code",
            "created_at",
            "completed_at",
            "counts",
            "items",
            "progress",
            "attempts",
        ]

    def get_counts(self, value):
        return {name: len(ids) for name, ids in value.manifest["targets"].items()}

    def get_items(self, value):
        # 不向客户端暴露存储凭据、内部桶名或对象路径，也不保留原文/文件名。
        return list(
            value.items.order_by("status", "id").values(
                "id", "kind", "status", "error_code", "completed_at"
            )[:100]
        )

    def get_progress(self, value):
        return {
            row["status"]: row["count"]
            for row in value.items.values("status").annotate(count=Count("id"))
        }

    def get_attempts(self, value):
        return list(
            value.attempts.order_by("-generation").values(
                "generation", "status", "error_code", "errors", "started_at", "finished_at"
            )[:100]
        )


def make_plan(request, project_id, data):
    project = require_project(request.user, project_id, write=True, lock=True)
    if data["scope"] == "project" and project.owner_id != request.user.pk:
        raise PermissionDenied("仅项目创建者可以删除整个项目。")
    material = (
        get_object_or_404(Material, project=project, pk=data["material_id"])
        if data["scope"] == "material"
        else None
    )
    return Plan(project, material)


class CleanupPreviewView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        plan = make_plan(request, project_id, validated(Selection, request))
        return Response(plan.preview())


class CleanupCreateView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        require_active_user(request.user)
        data = validated(Confirmation, request)
        fingerprint = digest({"project_id": str(project_id), **Confirmation(data).data})
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                [f"cleanup:{request.user.pk}:{data['request_key']}"],
            )
        # 项目可能已经删除；同一发起者的原始请求仍返回原清理记录。
        existing = CleanupRequest.objects.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.request_digest != fingerprint:
                raise VersionConflict("请求键已用于不同的删除操作。")
            return Response(CleanupSerializer(existing).data)
        plan = make_plan(request, project_id, data)
        if plan.preview()["token"] != data["preview_token"]:
            raise VersionConflict("删除范围已变化，请重新预览并核对。")
        record = create_cleanup(plan, request.user, data["request_key"], fingerprint)
        return Response(CleanupSerializer(record).data, status=201)


class CleanupListView(APIView):
    def get(self, request):
        require_active_user(request.user)
        return paginated(
            CleanupRequest.objects.filter(created_by=request.user).order_by("-created_at", "id"),
            CleanupSerializer,
            request,
        )


class CleanupDetailView(APIView):
    def get(self, request, request_id):
        require_active_user(request.user)
        record = get_object_or_404(CleanupRequest, pk=request_id, created_by=request.user)
        return Response(CleanupSerializer(record).data)

    @transaction.atomic
    def post(self, request, request_id):
        require_active_user(request.user)
        record = get_object_or_404(
            CleanupRequest.objects.select_for_update(), pk=request_id, created_by=request.user
        )
        data = validated(Retry, request)
        if data["generation"] != record.generation:
            raise VersionConflict("清理执行代次已变化，请刷新记录。")
        if record.status == "failed":
            record.status, record.error_code = "queued", ""
            record.save(update_fields=["status", "error_code", "updated_at"])
            transaction.on_commit(lambda: dispatch(record.pk))
        return Response(CleanupSerializer(record).data)
