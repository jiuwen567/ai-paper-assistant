from uuid import uuid4

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.common.api import paginated, validated
from core.jobs.serializers import JobSerializer
from core.jobs.service import dispatch
from core.materials.parsing import PARSER_VERSION
from core.materials.queries import published_chunks
from core.materials.views import MaterialVersionSerializer
from core.models import Job, MaterialVersion, ParseRun, SourceChunk
from core.projects.access import VersionConflict, require_project


class ParseInputSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=128)


class ParseSerializer(serializers.ModelSerializer):
    job = JobSerializer(read_only=True)

    class Meta:
        model = ParseRun
        fields = [
            "id",
            "number",
            "source_version",
            "parser_version",
            "job",
            "coverage",
            "warnings",
            "published_at",
            "created_at",
        ]


class ChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceChunk
        fields = ["id", "ordinal", "text", "anchor", "heading_level"]


class ParseListView(APIView):
    def get(self, request, project_id, version_id):
        require_project(request.user, project_id)
        source = get_object_or_404(MaterialVersion, pk=version_id, material__project_id=project_id)
        return paginated(
            source.parses.select_related("job")
            .prefetch_related("job__attempts")
            .order_by("-number"),
            ParseSerializer,
            request,
        )

    @transaction.atomic
    def post(self, request, project_id, version_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        source = get_object_or_404(
            MaterialVersion.objects.exclude(usage_state="withdrawn"),
            pk=version_id,
            material__project=project,
            material__access_state="active",
            status="available",
        )
        key = validated(ParseInputSerializer, request)["idempotency_key"]
        existing = project.jobs.filter(created_by=request.user, idempotency_key=key).first()
        if existing:
            run = ParseRun.objects.filter(job=existing, source_version=source).first()
            if existing.kind != "parse" or run is None:
                raise VersionConflict("请求键已用于其他输入，请使用新键。")
            return Response(ParseSerializer(run).data)
        run_id = uuid4()
        policy = project.policies.order_by("-version").first()
        job = Job.objects.create(
            project=project,
            created_by=request.user,
            kind="parse",
            idempotency_key=key,
            policy_version=policy.version,
            input_snapshot={
                "source_version_id": str(source.pk),
                "source_sha256": source.sha256,
                "source_state_version": source.material.state_version,
                "parse_run_id": str(run_id),
                "parser_version": PARSER_VERSION,
            },
        )
        previous = source.parses.order_by("-number").first()
        run = ParseRun.objects.create(
            id=run_id,
            source_version=source,
            number=previous.number + 1 if previous else 1,
            parser_version=PARSER_VERSION,
            job=job,
        )
        transaction.on_commit(lambda: dispatch(job.pk))
        return Response(ParseSerializer(run).data, status=201)




class ChunkListView(APIView):
    def get(self, request, project_id, run_id):
        require_project(request.user, project_id)
        get_object_or_404(
            ParseRun,
            pk=run_id,
            source_version__material__project_id=project_id,
            source_version__status="available",
            published_at__isnull=False,
            job__status=Job.Status.SUCCEEDED,
        )
        return paginated(
            published_chunks(project_id).filter(run_id=run_id).order_by("ordinal"),
            ChunkSerializer,
            request,
        )


class ChunkDetailView(APIView):
    def get(self, request, project_id, chunk_id):
        require_project(request.user, project_id)
        chunk = get_object_or_404(
            published_chunks(project_id).select_related("run__source_version"), pk=chunk_id
        )
        source = chunk.run.source_version
        context = (
            published_chunks(project_id)
            .filter(run=chunk.run, ordinal__range=(max(1, chunk.ordinal - 1), chunk.ordinal + 1))
            .order_by("ordinal")
        )
        base = f"/api/v1/projects/{project_id}/files/{source.pk}/"
        return Response(
            {
                "chunk": ChunkSerializer(chunk).data,
                "context": ChunkSerializer(context, many=True).data,
                "source_version": MaterialVersionSerializer(source).data,
                "parse_run": {
                    "id": str(chunk.run_id),
                    "number": chunk.run.number,
                    "parser_version": chunk.run.parser_version,
                },
                "download_url": base,
                "preview_url": f"{base}preview/#page={chunk.anchor['page']}"
                if chunk.anchor.get("kind") == "pdf"
                else None,
            }
        )
