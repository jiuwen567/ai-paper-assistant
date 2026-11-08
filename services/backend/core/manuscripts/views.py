from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.common.api import paginated, validated
from core.common.serializers import StrictSerializer
from core.library.service import searchable_chunks
from core.manuscripts.service import (
    compare,
    import_preview,
    manuscript_for,
    prepare_write,
    publish,
    revision_data,
    version_number,
)
from core.models import ManuscriptRevision, ParseRun
from core.projects.access import VersionConflict, require_project


class ResearchInput(StrictSerializer):
    question = serializers.CharField(max_length=10000, allow_blank=True, trim_whitespace=False)
    method = serializers.CharField(max_length=10000, allow_blank=True, trim_whitespace=False)
    result = serializers.CharField(max_length=10000, allow_blank=True, trim_whitespace=False)


class BlockInput(StrictSerializer):
    id = serializers.UUIDField()
    text = serializers.CharField(max_length=20000, allow_blank=True, trim_whitespace=False)
    heading_level = serializers.IntegerField(min_value=0, max_value=9)

    def validate(self, data):
        if data["heading_level"] and not data["text"].strip():
            raise ValidationError("章节标题不能为空。")
        return data


class WriteInput(StrictSerializer):
    version = serializers.IntegerField(min_value=0, max_value=2147483647)
    request_key = serializers.CharField(max_length=128)


class EditInput(WriteInput):
    research = ResearchInput()
    blocks = BlockInput(many=True)


class RestoreInput(WriteInput):
    from_version = serializers.IntegerField(min_value=0, max_value=2147483647)


class ImportInput(WriteInput):
    parse_id = serializers.UUIDField()
    token = serializers.CharField(min_length=64, max_length=64)
    mode = serializers.ChoiceField(choices=["append", "replace"])


def historical(manuscript, number):
    if not 0 <= number <= 2147483647:
        raise ValidationError("版本号不在有效范围内。")
    if number == 0:
        return None
    return get_object_or_404(ManuscriptRevision, manuscript=manuscript, number=number)


class ManuscriptView(APIView):
    def get(self, request, project_id):
        project = require_project(request.user, project_id)
        manuscript = manuscript_for(project)
        return Response(
            revision_data(
                manuscript.current_revision if manuscript else None, version_number(manuscript)
            )
        )

    @transaction.atomic
    def put(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(EditInput, request)
        manuscript, existing, request_digest = prepare_write(project, request.user, data, "edit")
        result = existing or publish(
            manuscript, request.user, data, request_digest, data["research"], data["blocks"]
        )
        return Response(revision_data(result, version_number(manuscript)))


class RevisionListSerializer(serializers.ModelSerializer):
    version = serializers.IntegerField(source="number")

    class Meta:
        model = ManuscriptRevision
        fields = ["version", "origin", "source", "created_by", "created_at"]


class ManuscriptHistoryView(APIView):
    def get(self, request, project_id):
        project = require_project(request.user, project_id)
        return paginated(
            ManuscriptRevision.objects.filter(manuscript__project=project).order_by("-number"),
            RevisionListSerializer,
            request,
        )


class ManuscriptRevisionView(APIView):
    def get(self, request, project_id, number):
        manuscript = manuscript_for(require_project(request.user, project_id))
        return Response(revision_data(historical(manuscript, number), version_number(manuscript)))


class ManuscriptDiffView(APIView):
    def get(self, request, project_id):
        manuscript = manuscript_for(require_project(request.user, project_id))
        try:
            before, after = [int(request.query_params[key]) for key in ["before", "after"]]
        except (ValueError, KeyError):
            raise ValidationError("请选择需要对照的两个版本。") from None
        if min(before, after) < 0:
            raise ValidationError("版本号不能为负数。")
        return Response(
            compare(
                revision_data(historical(manuscript, before)),
                revision_data(historical(manuscript, after)),
            )
        )


class ManuscriptRestoreView(APIView):
    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(RestoreInput, request)
        manuscript, existing, request_digest = prepare_write(project, request.user, data, "restore")
        if existing:
            result = existing
        else:
            old = revision_data(historical(manuscript, data["from_version"]))
            result = publish(
                manuscript,
                request.user,
                data,
                request_digest,
                old["research"],
                old["blocks"],
                origin="restore",
                source={"from_version": data["from_version"]},
            )
        return Response(revision_data(result, version_number(manuscript)))


class ImportSourceSerializer(serializers.ModelSerializer):
    file_name = serializers.CharField(source="source_version.file_name")
    source_number = serializers.IntegerField(source="source_version.number")

    class Meta:
        model = ParseRun
        fields = ["id", "file_name", "source_number", "number", "coverage", "warnings"]


class ManuscriptImportsView(APIView):
    def get(self, request, project_id):
        project = require_project(request.user, project_id)
        ids = (
            searchable_chunks(project.pk)
            .filter(run__source_version__file_name__iendswith=".docx")
            .values("run_id")
        )
        return paginated(
            ParseRun.objects.filter(pk__in=ids)
            .select_related("source_version")
            .order_by("-published_at", "id"),
            ImportSourceSerializer,
            request,
        )

    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(ImportInput, request)
        manuscript, existing, request_digest = prepare_write(project, request.user, data, "import")
        if existing:
            result = existing
        else:
            preview = import_preview(project, data["parse_id"])
            if preview["token"] != data["token"]:
                raise VersionConflict("导入来源已变化，请重新预览。")
            current = revision_data(manuscript.current_revision)
            # 追加保留现有块的固定版本；替换仅替换正文，不覆盖研究说明。
            blocks = (current["blocks"] if data["mode"] == "append" else []) + preview["blocks"]
            result = publish(
                manuscript,
                request.user,
                data,
                request_digest,
                current["research"],
                blocks,
                origin="import",
                source={**preview["source"], "mode": data["mode"]},
            )
        return Response(revision_data(result, version_number(manuscript)))


class ManuscriptImportPreviewView(APIView):
    def get(self, request, project_id, parse_id):
        project = require_project(request.user, project_id)
        return Response(import_preview(project, parse_id))
