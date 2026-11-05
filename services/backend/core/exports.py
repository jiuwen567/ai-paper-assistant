"""导出确认时冻结业务事实；后台只读取快照，不追随当前稿件或题录。"""

import re

import docx
from django.db.models import F, OuterRef, Subquery
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from core.access import VersionConflict
from core.ai_jobs import digest
from core.disclosures import facts_for
from core.export_templates import template_data
from core.library import default_bibliography, searchable_chunks
from core.manuscripts import manuscript_for, revision_data
from core.models import (
    BibliographyRevision,
    ExportTemplateVersion,
    ManuscriptCitation,
    MaterialVersion,
    RevisionBlock,
)
from core.reading import StrictSerializer

RENDERER_VERSION = f"word-export-v1/docx-{docx.__version__}"
MAX_REFERENCES = 1000


class CaptionInput(StrictSerializer):
    block_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=["figure", "table"])


class ExportSelection(StrictSerializer):
    manuscript_version = serializers.IntegerField(min_value=1)
    disclosure_version = serializers.IntegerField(min_value=1)
    template_version_id = serializers.UUIDField()
    title = serializers.CharField(max_length=200)
    author = serializers.CharField(max_length=200, allow_blank=True)
    captions = CaptionInput(many=True, max_length=500)


def format_reference(value):
    # 仅使用登记字段，不补造作者、年份、期刊、卷期或页码。
    pieces = []
    if value.get("authors"):
        pieces.append("，".join(value["authors"]))
    pieces.append(value["title"])
    if value.get("year"):
        pieces.append(str(value["year"]))
    if value.get("doi"):
        pieces.append("DOI: " + value["doi"])
    if value.get("url"):
        pieces.append(value["url"])
    return ". ".join(pieces)


def create_content(project, data):
    manuscript = manuscript_for(project)
    revision = manuscript.current_revision if manuscript else None
    if not revision or revision.number != data["manuscript_version"]:
        raise VersionConflict("原稿已变化，请刷新后重新预览导出。")
    disclosure = project.disclosures.order_by("-number").first()
    if not disclosure or not disclosure.verified or disclosure.number != data["disclosure_version"]:
        raise VersionConflict("请先由作者核实当前 AI 使用说明，再创建导出快照。")
    if disclosure.facts_token != digest(facts_for(project)):
        raise VersionConflict("使用记录或原稿已变化，请重新核实 AI 使用说明。")
    template = ExportTemplateVersion.objects.filter(pk=data["template_version_id"]).first()
    if template is None:
        raise ValidationError("所选模板版本不存在。")
    body = revision_data(revision)["blocks"]
    if not body or not any(block["text"].strip() for block in body):
        raise ValidationError("原稿为空，不能导出。")
    captions = {str(c["block_id"]): c["kind"] for c in data["captions"]}
    if len(captions) != len(data["captions"]) or not set(captions) <= {b["id"] for b in body}:
        raise ValidationError("题注位置重复或不属于当前稿件。")
    counters = {"figure": 0, "table": 0}
    for block in body:
        kind = captions.get(block["id"])
        block["caption"] = None
        block["references"] = []
        if kind:
            if (
                block["heading_level"]
                or not block["text"].strip()
                or "\n" in block["text"]
                or re.match(r"\s*[图表]\s*[0-9一二三四五六七八九十]", block["text"])
            ):
                raise ValidationError(
                    "题注请选择单行、非章节标题的正文块；标题内不预填图表编号，导出会按顺序编号。"
                )
            counters[kind] += 1
            block["caption"] = {"kind": kind, "number": counters[kind]}
    by_version = {block["version_id"]: block for block in body}
    citations = list(
        ManuscriptCitation.objects.filter(block_version_id__in=by_version)
        .select_related("chunk__run__source_version__material")
        .order_by("created_at", "id")
    )
    valid_ids = set(
        searchable_chunks(project.pk)
        .filter(pk__in=[c.chunk_id for c in citations])
        .values_list("pk", flat=True)
    )
    if any(c.chunk_id not in valid_ids for c in citations):
        raise VersionConflict("正文引用含已更正、撤回或失效的来源，请先核对并更新正文引用。")
    if any(
        c.snapshot.get("state_version") != c.chunk.run.source_version.material.state_version
        or c.snapshot.get("sha256") != c.chunk.run.source_version.sha256
        for c in citations
    ):
        raise VersionConflict("正文引用登记后来源已变化，请先重新核对引用。")
    # 以正文首次出现顺序确定参考文献编号；同一块中的引用按登记时间、ID固定排序。
    order = {block["version_id"]: i for i, block in enumerate(body)}
    citations.sort(key=lambda c: order[str(c.block_version_id)])
    source_ids = {c.chunk.run.source_version_id for c in citations}
    if len(source_ids) > MAX_REFERENCES:
        raise ValidationError("单次导出最多支持 1000 个引用来源，请缩小交付范围。")
    # 保留当前稳定正文块的导入来源，后续撤回/删除可定位到派生导出。
    first_revision = (
        RevisionBlock.objects.filter(block_id=OuterRef("block_id"))
        .order_by("revision__number")
        .values("revision_id")[:1]
    )
    imported = (
        RevisionBlock.objects.filter(block_id__in=[b["id"] for b in body])
        .annotate(first_revision=Subquery(first_revision))
        .filter(revision_id=F("first_revision"), revision__origin="import")
        .values_list("revision__source", flat=True)
        .distinct()
    )
    source_ids |= {
        source["source_version_id"] for source in imported if source.get("source_version_id")
    }
    sources = list(
        MaterialVersion.objects.filter(pk__in=source_ids, material__project=project)
        .select_related("material")
        .order_by("id")
    )
    if {str(v.pk) for v in sources} != {str(pk) for pk in source_ids} or any(
        v.status != "available" or v.material.access_state != "active" or v.usage_state != "active"
        for v in sources
    ):
        raise VersionConflict("稿件的已登记来源存在更正、撤回或不可用状态，请核对后再导出。")
    bibliography = {
        r.bibliography.source_version_id: r
        for r in BibliographyRevision.objects.filter(
            bibliography__source_version_id__in=source_ids, number=F("bibliography__revision")
        )
        .select_related("bibliography")
        .order_by("number")
    }
    references, numbers, warnings = [], {}, []
    for citation in citations:
        source = citation.chunk.run.source_version
        sid = str(source.pk)
        if sid not in numbers:
            number = len(numbers) + 1
            numbers[sid] = number
            bib = bibliography.get(source.pk)
            metadata = bib.snapshot if bib else default_bibliography(source)
            if not bib or not metadata.get("authors") or not metadata.get("year"):
                warnings.append(f"参考文献 [{number}] 的作者、年份或题录登记不完整，请核对。")
            references.append(
                {
                    "number": number,
                    "source_version_id": sid,
                    "bibliography_revision_id": str(bib.pk) if bib else None,
                    "bibliography_number": bib.number if bib else 0,
                    "metadata": metadata,
                    "text": format_reference(metadata),
                }
            )
        block = by_version[str(citation.block_version_id)]
        block["references"].append(
            {
                "number": numbers[sid],
                "citation_id": str(citation.pk),
                "chunk_id": str(citation.chunk_id),
                "registered_bibliography_revision_id": str(citation.bibliography_revision_id)
                if citation.bibliography_revision_id
                else None,
            }
        )
    source_values = [
        {
            "source_version_id": str(v.pk),
            "state_version": v.material.state_version,
            "usage_version": v.usage_version,
            "sha256": v.sha256,
            "file_name": v.file_name,
            "number": v.number,
        }
        for v in sources
    ]
    content = {
        "schema": 1,
        "title": data["title"],
        "author": data["author"],
        "manuscript_revision_id": str(revision.pk),
        "manuscript_version": revision.number,
        "blocks": body,
        "references": references,
        "sources": source_values,
        "template": template_data(template),
        "warnings": warnings,
        "disclosure": {
            "id": disclosure.pk,
            "number": disclosure.number,
            "text": disclosure.text,
            "external_uses": disclosure.external_uses,
            "facts_token": disclosure.facts_token,
            "verified_by": disclosure.created_by_id,
            "verified_at": disclosure.created_at.isoformat(),
        },
    }
    return content, revision, disclosure, template


def unavailable_sources(snapshot):
    return any(
        item.source_version.status != "available"
        or item.source_version.material.access_state != "active"
        or item.source_version.usage_state != "active"
        or item.source_version.material.state_version != item.state_version
        or item.source_version.usage_version != item.usage_version
        or item.source_version.sha256 != item.sha256
        for item in snapshot.sources.select_related("source_version__material")
    )
