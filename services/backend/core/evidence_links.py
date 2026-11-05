"""作者核对的依据关系，主张和证据都固定到现有原文，不生成研究内容。"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.access import VersionConflict, require_project
from core.feedback import fingerprint, location_data, select_location
from core.library import searchable_chunks
from core.models import EvidenceLink, EvidenceLinkRevision
from core.projects import paginated, validated
from core.reading import StrictSerializer

KINDS = ["supports", "contradicts", "context"]


def locate(text, quote, occurrence):
    offset = -1
    for _ in range(occurrence):
        offset = text.find(quote, offset + 1)
        if offset < 0:
            raise ValidationError("引文或出现次序与原文不符，请重新核对。")
    return offset


class LinkInput(StrictSerializer):
    request_key = serializers.CharField(max_length=128)
    manuscript_version = serializers.IntegerField(min_value=1)
    block_id = serializers.UUIDField()
    chunk_id = serializers.UUIDField()
    claim = serializers.CharField(max_length=2000, trim_whitespace=False)
    claim_occurrence = serializers.IntegerField(min_value=1, max_value=1000)
    evidence_quote = serializers.CharField(max_length=2000, trim_whitespace=False)
    evidence_occurrence = serializers.IntegerField(min_value=1, max_value=1000)
    kind = serializers.ChoiceField(choices=KINDS)
    note = serializers.CharField(max_length=2000, allow_blank=True)
    confirmed = serializers.BooleanField()


class LinkDecisionInput(StrictSerializer):
    request_key = serializers.CharField(max_length=128)
    version = serializers.IntegerField(min_value=1)
    state = serializers.ChoiceField(choices=["confirmed", "withdrawn"])
    kind = serializers.ChoiceField(choices=KINDS)
    note = serializers.CharField(max_length=2000, allow_blank=True)
    confirmed = serializers.BooleanField()


def links(project_id):
    return (
        EvidenceLink.objects.filter(project_id=project_id)
        .select_related(
            "manuscript_revision", "block_version", "chunk__run__source_version__material"
        )
        .prefetch_related("decisions")
    )


class LinkRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidenceLinkRevision
        fields = [
            "number",
            "state",
            "kind",
            "note",
            "source_state_version",
            "created_by",
            "created_at",
        ]


def link_changed(link, decision):
    location = location_data(link.manuscript_revision, link.block_version)
    source = link.chunk.run.source_version
    return (
        location["stale"]
        or source.material.state_version != decision.source_state_version
        or not searchable_chunks(link.project_id).filter(pk=link.chunk_id).exists()
    )


class LinkSerializer(serializers.ModelSerializer):
    current = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    needs_review = serializers.SerializerMethodField()
    evidence_quote = serializers.SerializerMethodField()
    source_available = serializers.SerializerMethodField()

    def get_current(self, link):
        return LinkRevisionSerializer(max(link.decisions.all(), key=lambda item: item.number)).data

    def get_location(self, link):
        return location_data(link.manuscript_revision, link.block_version)

    def get_needs_review(self, link):
        return link_changed(link, max(link.decisions.all(), key=lambda item: item.number))

    def get_evidence_quote(self, link):
        return link.evidence_quote if self.get_source_available(link) else ""

    def get_source_available(self, link):
        source = link.chunk.run.source_version
        return source.material.access_state == "active" and source.usage_state != "withdrawn"

    class Meta:
        model = EvidenceLink
        fields = [
            "id",
            "claim",
            "claim_start",
            "evidence_quote",
            "evidence_start",
            "chunk_id",
            "bibliography_revision_id",
            "location",
            "current",
            "needs_review",
            "source_available",
            "created_by",
            "created_at",
        ]


class EvidenceLinksView(APIView):
    def get(self, request, project_id):
        require_project(request.user, project_id)
        return paginated(links(project_id).order_by("-created_at", "id"), LinkSerializer, request)

    @transaction.atomic
    def post(self, request, project_id):
        project = require_project(request.user, project_id, write=True, lock=True)
        data = validated(LinkInput, request)
        request_digest = fingerprint(data)
        existing = (
            links(project_id)
            .filter(created_by=request.user, request_key=data["request_key"])
            .first()
        )
        if existing:
            if existing.request_digest != request_digest:
                raise VersionConflict("请求键已用于其他依据关系。")
            return Response(LinkSerializer(existing).data)
        if not data["confirmed"]:
            raise ValidationError("请核对原稿主张、来源原话与关系。")
        revision, block = select_location(project_id, data)
        chunk = get_object_or_404(
            searchable_chunks(project_id).select_related("run__source_version__material"),
            pk=data["chunk_id"],
        )
        bibliography = getattr(chunk.run.source_version, "bibliography", None)
        bib_revision = (
            bibliography.revisions.filter(number=bibliography.revision).first()
            if bibliography
            else None
        )
        link = EvidenceLink.objects.create(
            project=project,
            manuscript_revision=revision,
            block_version=block,
            chunk=chunk,
            bibliography_revision=bib_revision,
            claim=data["claim"],
            claim_start=locate(block.text, data["claim"], data["claim_occurrence"]),
            evidence_quote=data["evidence_quote"],
            evidence_start=locate(chunk.text, data["evidence_quote"], data["evidence_occurrence"]),
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=request_digest,
        )
        EvidenceLinkRevision.objects.create(
            link=link,
            number=1,
            state="confirmed",
            kind=data["kind"],
            note=data["note"],
            source_state_version=chunk.run.source_version.material.state_version,
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=request_digest,
        )
        return Response(LinkSerializer(links(project_id).get(pk=link.pk)).data, status=201)


class EvidenceLinkView(APIView):
    def get(self, request, project_id, link_id):
        require_project(request.user, project_id)
        return Response(LinkSerializer(get_object_or_404(links(project_id), pk=link_id)).data)

    @transaction.atomic
    def post(self, request, project_id, link_id):
        require_project(request.user, project_id, write=True, lock=True)
        link = get_object_or_404(links(project_id), pk=link_id)
        data = validated(LinkDecisionInput, request)
        request_digest = fingerprint(data)
        existing = link.decisions.filter(
            created_by=request.user, request_key=data["request_key"]
        ).first()
        if existing:
            if existing.request_digest != request_digest:
                raise VersionConflict("请求键已用于其他核对决定。")
            return Response(LinkSerializer(link).data)
        latest = max(link.decisions.all(), key=lambda item: item.number)
        if latest.number != data["version"]:
            raise VersionConflict("依据关系已有新决定，请刷新后核对。")
        if data["state"] == "confirmed":
            if not data["confirmed"]:
                raise ValidationError("请先核对依据关系。")
            if location_data(link.manuscript_revision, link.block_version)["stale"]:
                raise VersionConflict("原稿主张已变化，请为新稿登记关系，不沿用旧核对。")
            if not searchable_chunks(project_id).filter(pk=link.chunk_id).exists():
                raise VersionConflict("来源已变化，请为最新来源登记关系。")
        elif not data["note"].strip():
            raise ValidationError("撤回关系时请记录原因。")
        EvidenceLinkRevision.objects.create(
            link=link,
            number=latest.number + 1,
            state=data["state"],
            kind=data["kind"],
            note=data["note"],
            source_state_version=link.chunk.run.source_version.material.state_version,
            created_by=request.user,
            request_key=data["request_key"],
            request_digest=request_digest,
        )
        return Response(LinkSerializer(links(project_id).get(pk=link.pk)).data)


class EvidenceLinkHistoryView(APIView):
    def get(self, request, project_id, link_id):
        require_project(request.user, project_id)
        link = get_object_or_404(links(project_id), pk=link_id)
        return paginated(link.decisions.order_by("-number"), LinkRevisionSerializer, request)
