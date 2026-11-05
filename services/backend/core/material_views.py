import hashlib

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_project
from core.health import s3_client
from core.material_files import MAX_FILE_SIZE, media_type, validate_file
from core.materials import StorageUnavailable, claim_upload, set_failure, store_file
from core.models import Material, MaterialVersion
from core.projects import paginated, validated

CATEGORIES = ["literature", "research", "manuscript"]


class UploadIntentSerializer(serializers.Serializer):
    request_key = serializers.CharField(max_length=128)
    title = serializers.CharField(max_length=200, allow_blank=True, default="")
    category = serializers.ChoiceField(choices=CATEGORIES, default="literature")
    material_id = serializers.UUIDField(required=False)
    base_revision = serializers.IntegerField(min_value=0, default=0)
    file_name = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1, max_value=MAX_FILE_SIZE)

    def validate_file_name(self, value):
        media_type(value)
        return value

    def validate(self, data):
        if "material_id" not in data and not data["title"]:
            raise ValidationError("请填写材料名称。")
        return data


class MaterialVersionSerializer(serializers.ModelSerializer):
    material_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = MaterialVersion
        fields = [
            "id",
            "material_id",
            "created_by",
            "number",
            "file_name",
            "size",
            "media_type",
            "sha256",
            "status",
            "error_code",
            "error_message",
            "created_at",
        ]


class MaterialSerializer(serializers.ModelSerializer):
    latest_version = serializers.SerializerMethodField()

    def get_latest_version(self, material):
        version = material.versions.order_by("-number").first()
        return MaterialVersionSerializer(version).data if version else None

    class Meta:
        model = Material
        fields = ["id", "title", "category", "revision", "created_at", "latest_version"]


class MaterialListView(APIView):
    def get(self, request, project_id):
        project = require_project(request.user, project_id)
        return paginated(
            project.materials.order_by("-created_at", "id"), MaterialSerializer, request
        )


class MaterialVersionsView(APIView):
    def get(self, request, project_id, material_id):
        require_project(request.user, project_id)
        material = get_object_or_404(Material, pk=material_id, project_id=project_id)
        return paginated(material.versions.order_by("-number"), MaterialVersionSerializer, request)


class UploadIntentView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        data = validated(UploadIntentSerializer, request)
        # 转成与 JSONField 完全一致的输入快照，避免 UUID/string 比较造成假冲突。
        if "material_id" in data:
            data["material_id"] = str(data["material_id"])
        existing = (
            MaterialVersion.objects.filter(created_by=request.user, request_key=data["request_key"])
            .select_related("material")
            .first()
        )
        if existing:
            if existing.material.project_id != project.pk or existing.request_snapshot != data:
                raise VersionConflict("请求键已用于其他上传，请创建新的请求。")
            return Response(MaterialVersionSerializer(existing).data)
        if "material_id" in data:
            material = get_object_or_404(Material, pk=data["material_id"], project=project)
            if data["base_revision"] != material.revision:
                raise VersionConflict("材料已有新上传，请刷新后再创建版本。")
        else:
            material = Material.objects.create(
                project=project,
                title=data["title"],
                category=data["category"],
            )
        material.revision += 1
        material.save()
        version = MaterialVersion(
            material=material,
            number=material.revision,
            created_by=request.user,
            request_key=data["request_key"],
            request_snapshot=data,
            file_name=data["file_name"],
            size=data["size"],
            media_type=media_type(data["file_name"]),
            bucket=settings.MATERIAL_BUCKET,
        )
        version.object_key = f"materials/{material.pk}/{version.pk}"
        version.save()
        return Response(MaterialVersionSerializer(version).data, status=201)


class UploadFileView(APIView):
    def post(self, request, project_id, version_id):
        require_project(request.user, project_id, write=True)
        version = get_object_or_404(
            MaterialVersion,
            pk=version_id,
            material__project_id=project_id,
            created_by=request.user,
        )
        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            raise ValidationError("无效的上传长度。") from None
        if content_length > MAX_FILE_SIZE + 1024 * 1024:
            raise ValidationError("上传请求超过大小限制。")
        uploaded = request.FILES.get("file")
        try:
            if uploaded is None or uploaded.size != version.size:
                raise ValidationError("文件大小与上传登记不一致。")
            data = uploaded.read(MAX_FILE_SIZE + 1)
            validate_file(data, version.file_name)
        except ValidationError:
            with transaction.atomic():
                require_project(request.user, project_id, write=True, lock=True)
                version.refresh_from_db()
                if version.status in ["uploading", "failed"] and not version.sha256:
                    set_failure(version, "invalid_file", "文件大小、类型或内容校验失败。")
            raise
        version = claim_upload(request.user, version.pk, hashlib.sha256(data).hexdigest())
        store_file(version, data)
        version.refresh_from_db()
        return Response(MaterialVersionSerializer(version).data)


class MaterialDownloadView(APIView):
    inline = False

    def get(self, request, project_id, version_id):
        require_project(request.user, project_id)
        version = get_object_or_404(
            MaterialVersion,
            pk=version_id,
            material__project_id=project_id,
            status="available",
        )
        if self.inline and version.media_type != "application/pdf":
            raise Http404
        client = s3_client()
        try:
            stored = client.get_object(Bucket=version.bucket, Key=version.object_key)
        except Exception:
            client.close()
            raise StorageUnavailable("原文件暂时无法读取，请稍后重试。") from None
        response = ObjectResponse(
            stored["Body"],
            client,
            as_attachment=not self.inline,
            filename=version.file_name,
            content_type=version.media_type,
        )
        response["Content-Length"] = str(version.size)
        response["Cache-Control"] = "no-store"
        response["X-Content-Type-Options"] = "nosniff"
        if self.inline:
            response["Content-Security-Policy"] = "sandbox; frame-ancestors 'self'"
            response["X-Frame-Options"] = "SAMEORIGIN"
        return response


class MaterialPreviewView(MaterialDownloadView):
    inline = True


class ObjectResponse(FileResponse):
    def __init__(self, body, client, **kwargs):
        self.storage_client = client
        super().__init__(body, **kwargs)

    def close(self):
        try:
            super().close()
        finally:
            self.storage_client.close()
