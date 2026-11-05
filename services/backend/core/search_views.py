from django.db import transaction
from django.db.models import F, OuterRef, Q, Subquery
from pgvector.django import CosineDistance
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_ai_action, require_project
from core.embeddings import configuration, encode
from core.index_jobs import corpus, create_index
from core.library import searchable_chunks
from core.models import BibliographyRevision, EmbeddingIndex, Job
from core.parsing import ParseFailure
from core.projects import paginated, validated


class IndexInput(serializers.Serializer):
    idempotency_key = serializers.CharField(max_length=128)
    policy_version = serializers.IntegerField(min_value=1)


class IndexJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = [
            "id",
            "status",
            "progress",
            "generation",
            "retryable",
            "error_code",
            "error_message",
        ]


class IndexSerializer(serializers.ModelSerializer):
    job = IndexJobSerializer(read_only=True)

    class Meta:
        model = EmbeddingIndex
        fields = [
            "id",
            "model_name",
            "dimension",
            "artifact_digest",
            "pipeline_version",
            "published_at",
            "created_at",
            "job",
        ]


class IndexListView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        return paginated(
            EmbeddingIndex.objects.filter(job__project_id=project_id)
            .select_related("job")
            .prefetch_related("job__attempts")
            .order_by("-created_at", "id"),
            IndexSerializer,
            request,
        )

    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(IndexInput, request)
        require_ai_action(request.user, project_id, "reading", data["policy_version"])
        job = project.jobs.filter(
            created_by=request.user, idempotency_key=data["idempotency_key"]
        ).first()
        if job:
            if job.kind != "index" or job.policy_version != data["policy_version"]:
                raise VersionConflict("请求键已用于其他任务。")
            return Response(IndexSerializer(job.embedding_index).data)
        try:
            index = create_index(
                project, request.user, data["idempotency_key"], data["policy_version"]
            )
        except ParseFailure as error:
            raise ValidationError(error.message) from None
        return Response(IndexSerializer(index).data, status=201)


def result(chunk, excerpt=None, score=None):
    source = chunk.run.source_version
    bibliography = getattr(source, "bibliography", None)
    latest = (
        bibliography.revisions.filter(number=bibliography.revision).first()
        if bibliography
        else None
    )
    return {
        "chunk_id": str(chunk.pk),
        "text": excerpt if excerpt is not None else chunk.text,
        "anchor": chunk.anchor,
        "source_version_id": str(source.pk),
        "source_number": source.number,
        "file_name": source.file_name,
        "material_title": source.material.title,
        "source_scope": latest.snapshot["source_scope"] if latest else "unknown",
        "coverage": chunk.run.coverage,
        "score": score,
    }


class SearchView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        query = request.query_params.get("q", "").strip()
        mode = request.query_params.get("mode", "keyword")
        if not query or len(query) > 200 or mode not in ["keyword", "semantic"]:
            raise ValidationError("请输入 1–200 字的检索词并选择检索方式。")
        chunks = searchable_chunks(project_id).select_related(
            "run__source_version__material", "run__source_version__bibliography"
        )
        if mode == "keyword":
            metadata = BibliographyRevision.objects.filter(
                bibliography__source_version_id=OuterRef("run__source_version_id"),
                number=F("bibliography__revision"),
            ).values("snapshot")[:1]
            found = (
                chunks.annotate(metadata=Subquery(metadata))
                .filter(
                    Q(text__icontains=query)
                    | Q(run__source_version__material__title__icontains=query)
                    | Q(metadata__title__icontains=query)
                    | Q(metadata__abstract__icontains=query)
                    | Q(metadata__note__icontains=query)
                    | Q(metadata__authors__icontains=query)
                )
                .order_by("id")[:21]
            )
            results = [result(chunk) for chunk in found]
            return Response({"results": results[:20], "has_more": len(results) > 20, "index": None})
        with transaction.atomic():
            project = require_project(request.user, project_id, lock=True)
            policy = project.policies.order_by("-version").first()
            require_ai_action(request.user, project_id, "reading", policy.version, write=False)
            try:
                config = configuration()
                sources, _ = corpus(project_id)
            except ParseFailure as error:
                raise ValidationError(error.message) from None
            index = (
                EmbeddingIndex.objects.filter(
                    job__project=project,
                    job__status="succeeded",
                    published_at__isnull=False,
                    job__input_snapshot__embedding=config,
                    job__input_snapshot__sources=sources,
                )
                .order_by("-created_at")
                .first()
            )
            if index is None:
                raise VersionConflict("有效资料或模型已有变化，请先重建检索索引。")
            policy_version = policy.version
        # 推理不占用项目锁；返回前重新检查权限、规则、资料和模型。
        try:
            vector = encode([query], config, query=True)[0]
        except ParseFailure as error:
            raise ValidationError(error.message) from None
        with transaction.atomic():
            require_ai_action(
                request.user, project_id, "reading", policy_version, lock=True, write=False
            )
            current, _ = corpus(project_id)
            if current != sources or config != configuration():
                raise VersionConflict("检索期间资料或模型发生变化，请重试。")
            matches = (
                index.segments.filter(chunk__in=chunks)
                .annotate(distance=CosineDistance("vector", vector))
                .select_related(
                    "chunk__run__source_version__material",
                    "chunk__run__source_version__bibliography",
                )
                .order_by("distance", "id")[:20]
            )
            return Response(
                {
                    "results": [
                        result(
                            item.chunk, item.chunk.text[item.start : item.end], 1 - item.distance
                        )
                        for item in matches
                    ],
                    "has_more": False,
                    "index": {
                        "id": str(index.pk),
                        "model": index.model_name,
                        "dimension": index.dimension,
                    },
                }
            )
