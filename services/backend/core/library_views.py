from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_project
from core.library import active_chunks, current_bibliography, default_bibliography
from core.models import (
    Bibliography,
    BibliographyRevision,
    EvidenceCard,
    EvidenceNote,
    Material,
    MaterialVersion,
)
from core.projects import paginated, validated


class TagsSerializer(serializers.Serializer):
    tags = serializers.ListField(
        child=serializers.CharField(max_length=30), max_length=12, default=list
    )

    def validate_tags(self, value):
        return list(dict.fromkeys(value))


class BibliographyInput(TagsSerializer):
    title = serializers.CharField(max_length=300)
    authors = serializers.ListField(
        child=serializers.CharField(max_length=100), max_length=40, default=list
    )
    year = serializers.RegexField(r"^([12][0-9]{3})?$", allow_blank=True, default="")
    doi = serializers.CharField(max_length=200, allow_blank=True, default="")
    url = serializers.URLField(max_length=500, allow_blank=True, default="")
    source_scope = serializers.ChoiceField(
        choices=["unknown", "abstract", "full_text", "research"], default="unknown"
    )
    abstract = serializers.CharField(max_length=10000, allow_blank=True, default="")
    note = serializers.CharField(max_length=10000, allow_blank=True, default="")


class BibliographyUpdate(serializers.Serializer):
    version = serializers.IntegerField(min_value=0)
    snapshot = BibliographyInput()


class BibliographyView(APIView):
    def get(self, request, project_id, version_id):
        require_project(request.user, project_id)
        source = get_object_or_404(
            MaterialVersion.objects.select_related("material"),
            pk=version_id,
            material__project_id=project_id,
        )
        record = Bibliography.objects.filter(source_version=source).first()
        latest = record.revisions.filter(number=record.revision).first() if record else None
        return Response(
            {
                "version": latest.number if latest else 0,
                "snapshot": latest.snapshot if latest else default_bibliography(source),
            }
        )

    @transaction.atomic
    def put(self, request, project_id, version_id):
        require_project(request.user, project_id, write=True, lock=True)
        source = get_object_or_404(
            MaterialVersion,
            pk=version_id,
            material__project_id=project_id,
            material__access_state="active",
            status="available",
        )
        data = validated(BibliographyUpdate, request)
        record, _ = Bibliography.objects.get_or_create(source_version=source)
        if data["version"] != record.revision:
            previous = record.revisions.filter(number=record.revision).first()
            if (
                previous
                and previous.number == data["version"] + 1
                and previous.snapshot == data["snapshot"]
                and previous.created_by_id == request.user.pk
            ):
                return Response({"version": previous.number, "snapshot": previous.snapshot})
            raise VersionConflict("题录已更新，请重新加载后提交。")
        record.revision += 1
        record.save()
        latest = BibliographyRevision.objects.create(
            bibliography=record,
            number=record.revision,
            snapshot=data["snapshot"],
            created_by=request.user,
        )
        return Response({"version": latest.number, "snapshot": latest.snapshot})


class EvidenceInput(TagsSerializer):
    chunk_id = serializers.UUIDField()
    request_key = serializers.CharField(max_length=128)
    note = serializers.CharField(max_length=10000, allow_blank=True, default="")


class NoteInput(TagsSerializer):
    version = serializers.IntegerField(min_value=1)
    note = serializers.CharField(max_length=10000, allow_blank=True)


class EvidenceSerializer(serializers.ModelSerializer):
    quote = serializers.CharField(source="chunk.text", read_only=True)
    anchor = serializers.JSONField(source="chunk.anchor", read_only=True)
    bibliography = serializers.JSONField(source="bibliography_revision.snapshot", read_only=True)
    source = serializers.SerializerMethodField()
    note = serializers.SerializerMethodField()

    def get_source(self, card):
        source = card.chunk.run.source_version
        return {
            "id": str(source.pk),
            "number": source.number,
            "file_name": source.file_name,
            "material_id": str(source.material_id),
            "access_state": source.material.access_state,
            "coverage": card.chunk.run.coverage,
            "parse_run_id": str(card.chunk.run_id),
        }

    def get_note(self, card):
        note = card.notes.get(number=card.revision)
        return {"text": note.text, "tags": note.tags, "created_by": note.created_by_id}

    class Meta:
        model = EvidenceCard
        fields = [
            "id",
            "chunk",
            "quote",
            "anchor",
            "bibliography",
            "source",
            "note",
            "revision",
            "created_at",
        ]


def evidence_cards(project_id):
    return EvidenceCard.objects.filter(
        chunk__run__source_version__material__project_id=project_id
    ).select_related("chunk__run__source_version__material", "bibliography_revision")


class EvidenceListView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        query = request.query_params.get("q", "").strip()[:200]
        tag = request.query_params.get("tag", "").strip()[:30]
        latest = EvidenceNote.objects.filter(
            evidence_id=OuterRef("pk"), number=OuterRef("revision")
        )
        cards = evidence_cards(project_id).annotate(
            note_text=Subquery(latest.values("text")[:1]),
            note_tags=Subquery(latest.values("tags")[:1]),
        )
        if query:
            cards = cards.filter(
                Q(chunk__text__icontains=query)
                | Q(note_text__icontains=query)
                | Q(bibliography_revision__snapshot__title__icontains=query)
            )
        if tag:
            cards = cards.filter(note_tags__contains=[tag])
        return paginated(cards.order_by("-created_at", "id"), EvidenceSerializer, request)

    @transaction.atomic
    def post(self, request, project_id):
        require_project(request.user, project_id, write=True, lock=True)
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        data = validated(EvidenceInput, request)
        data["chunk_id"] = str(data["chunk_id"])
        existing = EvidenceCard.objects.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if (
                existing.chunk.run.source_version.material.project_id != project_id
                or existing.request_snapshot != data
            ):
                raise VersionConflict("请求键已用于其他摘录。")
            return Response(EvidenceSerializer(existing).data)
        chunk = get_object_or_404(
            active_chunks(project_id).select_related("run__source_version__material"),
            pk=data["chunk_id"],
        )
        _, bibliography = current_bibliography(chunk.run.source_version, request.user)
        card = EvidenceCard.objects.create(
            chunk=chunk,
            bibliography_revision=bibliography,
            created_by=request.user,
            request_key=data["request_key"],
            request_snapshot=data,
            revision=1,
        )
        EvidenceNote.objects.create(
            evidence=card, number=1, text=data["note"], tags=data["tags"], created_by=request.user
        )
        return Response(EvidenceSerializer(card).data, status=201)


class EvidenceDetailView(APIView):
    def get(self, request, project_id, evidence_id):
        require_project(request.user, project_id)
        return Response(
            EvidenceSerializer(get_object_or_404(evidence_cards(project_id), pk=evidence_id)).data
        )

    @transaction.atomic
    def patch(self, request, project_id, evidence_id):
        require_project(request.user, project_id, write=True, lock=True)
        card = get_object_or_404(
            evidence_cards(project_id),
            pk=evidence_id,
            chunk__run__source_version__material__access_state="active",
        )
        data = validated(NoteInput, request)
        previous = card.notes.get(number=card.revision)
        if data["version"] != card.revision:
            if (
                data["version"] + 1 == card.revision
                and previous.text == data["note"]
                and previous.tags == data["tags"]
                and previous.created_by_id == request.user.pk
            ):
                return Response(EvidenceSerializer(card).data)
            raise VersionConflict("笔记已更新，请重新加载后提交。")
        card.revision += 1
        card.save()
        EvidenceNote.objects.create(
            evidence=card,
            number=card.revision,
            text=data["note"],
            tags=data["tags"],
            created_by=request.user,
        )
        return Response(EvidenceSerializer(card).data)

    def put(self, request, project_id, evidence_id):
        return self.patch(request, project_id, evidence_id)


class MaterialStateInput(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    access_state = serializers.ChoiceField(choices=["active", "withdrawn"])


class MaterialStateView(APIView):
    @transaction.atomic
    def patch(self, request, project_id, material_id):
        require_project(request.user, project_id, write=True, lock=True)
        material = get_object_or_404(Material, pk=material_id, project_id=project_id)
        data = validated(MaterialStateInput, request)
        if data["version"] != material.state_version:
            if (
                data["version"] + 1 == material.state_version
                and data["access_state"] == material.access_state
            ):
                return Response(
                    {"access_state": material.access_state, "version": material.state_version}
                )
            raise VersionConflict("材料状态已变化，请重新加载。")
        if data["access_state"] != material.access_state:
            material.access_state = data["access_state"]
            material.state_version += 1
            material.save()
        return Response({"access_state": material.access_state, "version": material.state_version})
