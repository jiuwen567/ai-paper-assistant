import io
from contextlib import closing
from uuid import uuid4

from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.common.api import paginated, validated
from core.common.digests import digest
from core.exports.jobs import WORD_TYPE
from core.exports.service import (
    RENDERER_VERSION,
    ExportSelection,
    create_content,
    unavailable_sources,
)
from core.exports.templates import template_data
from core.jobs.serializers import JobSerializer
from core.jobs.service import dispatch
from core.materials.service import read_and_verify
from core.models import ExportDownload, ExportSnapshot, ExportSource, ExportTemplateVersion, Job
from core.projects.access import VersionConflict, require_project
from core.storage.s3 import s3_client


class ExportInput(ExportSelection):
    preview_token = serializers.RegexField(r"^[a-f0-9]{64}$")
    request_key = serializers.CharField(max_length=128)
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value):
        if not value:
            raise ValidationError("请先核对导出预览。")
        return value


def snapshot_data(snapshot, detail=False):
    artifact = snapshot.files.filter(published_at__isnull=False).order_by("-generation").first()
    unavailable = unavailable_sources(snapshot)
    result = {
        "id": str(snapshot.pk),
        "created_at": snapshot.created_at,
        "created_by": snapshot.created_by_id,
        "title": snapshot.content["title"],
        "manuscript_version": snapshot.manuscript_revision.number,
        "disclosure_version": snapshot.disclosure_revision.number,
        "template": snapshot.content["template"],
        "digest": snapshot.digest,
        "renderer_version": snapshot.renderer_version,
        "job": JobSerializer(snapshot.job).data,
        "downloadable": bool(artifact and not unavailable and snapshot.job.status == "succeeded"),
        "sources_changed": unavailable,
        "file": {"id": artifact.pk, "sha256": artifact.sha256, "size": artifact.size}
        if artifact
        else None,
    }
    if detail:
        result["content"] = None if unavailable else snapshot.content
        result["downloads"] = list(
            ExportDownload.objects.filter(file__snapshot=snapshot)
            .order_by("-created_at", "-id")
            .values("id", "file_id", "created_by_id", "created_at")[:100]
        )
    return result


class ExportSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        return snapshot_data(instance)


class ExportTemplatesView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        return Response(
            [template_data(t) for t in ExportTemplateVersion.objects.order_by("code", "-number")]
        )


class ExportPreviewView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        content, *_ = create_content(project, validated(ExportSelection, request))
        return Response({"content": content, "preview_token": digest(content)})


class ExportsView(APIView):
    @transaction.atomic
    def get(self, request, project_id):
        project = require_project(request.user, project_id, lock=True)
        return paginated(project.exports.order_by("-created_at", "id"), ExportSerializer, request)

    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(ExportInput, request)
        fingerprint = digest(ExportInput(data).data)
        existing = project.exports.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.request_digest != fingerprint:
                raise VersionConflict("请求键已用于不同的导出。")
            return Response(snapshot_data(existing, True))
        content, revision, disclosure, template = create_content(project, data)
        if digest(content) != data["preview_token"]:
            raise VersionConflict("正文、题录或披露已变化，请重新预览。")
        snapshot_id = uuid4()
        policy = project.policies.order_by("-version").first()
        job = Job.objects.create(
            project=project,
            created_by=request.user,
            kind="export",
            policy_version=policy.version,
            idempotency_key=f"export:{snapshot_id}",
            input_snapshot={
                "snapshot_id": str(snapshot_id),
                "digest": digest(content),
                "renderer_version": RENDERER_VERSION,
            },
        )
        snapshot = ExportSnapshot.objects.create(
            id=snapshot_id,
            project=project,
            manuscript_revision=revision,
            disclosure_revision=disclosure,
            template_version=template,
            job=job,
            content=content,
            digest=digest(content),
            renderer_version=RENDERER_VERSION,
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=fingerprint,
        )
        ExportSource.objects.bulk_create(
            [
                ExportSource(
                    snapshot=snapshot,
                    **{
                        key: source[key]
                        for key in ["source_version_id", "state_version", "usage_version", "sha256"]
                    },
                )
                for source in content["sources"]
            ]
        )
        transaction.on_commit(lambda: dispatch(job.pk))
        return Response(snapshot_data(snapshot, True), status=201)


class ExportDetailView(APIView):
    @transaction.atomic
    def get(self, request, project_id, snapshot_id):
        require_project(request.user, project_id, lock=True)
        snapshot = get_object_or_404(ExportSnapshot, project_id=project_id, pk=snapshot_id)
        return Response(snapshot_data(snapshot, True))


class ExportDownloadView(APIView):
    @transaction.atomic
    def get(self, request, project_id, snapshot_id):
        require_project(request.user, project_id, lock=True)
        snapshot = get_object_or_404(ExportSnapshot, project_id=project_id, pk=snapshot_id)
        if unavailable_sources(snapshot):
            raise VersionConflict("导出来源状态已变化，不能下载旧文件，请核对后重新导出。")
        artifact = snapshot.files.filter(
            published_at__isnull=False, generation=snapshot.job.generation
        ).first()
        if not artifact or snapshot.job.status != Job.Status.SUCCEEDED:
            raise VersionConflict("导出尚未成功，请查看任务状态。")
        try:
            with closing(s3_client()) as client:
                data = read_and_verify(client, artifact)
        except Exception:
            error = APIException("导出文件暂时不可用或校验失败，请稍后重试并检查存储。")
            error.status_code = 503
            raise error from None
        ExportDownload.objects.create(file=artifact, created_by=request.user)
        response = FileResponse(
            io.BytesIO(data),
            as_attachment=True,
            filename=f"稿件-v{snapshot.manuscript_revision.number}-{str(snapshot.pk)[:8]}.docx",
            content_type=WORD_TYPE,
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
