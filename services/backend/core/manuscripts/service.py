import hashlib
import json
from uuid import uuid5

from django.db.models import Max
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from core.library.service import searchable_chunks
from core.models import (
    BlockVersion,
    ContentBlock,
    Manuscript,
    ManuscriptRevision,
    ParseRun,
    RevisionBlock,
)
from core.projects.access import VersionConflict

RESEARCH_FIELDS = ("question", "method", "result")


MAX_BLOCKS = 500


MAX_CHARACTERS = 200_000


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def manuscript_for(project):
    return Manuscript.objects.select_related("current_revision").filter(project=project).first()


def version_number(manuscript):
    return manuscript.current_revision.number if manuscript and manuscript.current_revision else 0


def revision_data(revision, current_version=0):
    if revision is None:
        return {
            "version": 0,
            "current_version": current_version,
            "research": dict.fromkeys(RESEARCH_FIELDS, ""),
            "blocks": [],
            "origin": "edit",
            "source": {},
            "created_at": None,
            "created_by": None,
        }
    return {
        "version": revision.number,
        "current_version": current_version,
        "research": revision.research,
        "origin": revision.origin,
        "source": revision.source,
        "created_at": revision.created_at,
        "created_by": revision.created_by_id,
        "blocks": [
            {
                "id": str(item.block_id),
                "version_id": str(item.block_version_id),
                "number": item.block_version.number,
                "text": item.block_version.text,
                "heading_level": item.block_version.heading_level,
            }
            for item in revision.items.select_related("block_version").order_by("position")
        ],
    }


def check_size(blocks):
    if len(blocks) > MAX_BLOCKS or sum(len(item["text"]) for item in blocks) > MAX_CHARACTERS:
        raise ValidationError("原稿最多 500 个正文块、20 万字符，请拆分后处理。")


def prepare_write(project, user, data, action):
    manuscript, _ = Manuscript.objects.select_related("current_revision").get_or_create(
        project=project
    )
    request_digest = digest({"action": action, **data})
    existing = manuscript.revisions.filter(created_by=user, request_key=data["request_key"]).first()
    if existing:
        if existing.request_digest != request_digest:
            raise VersionConflict("请求键已用于不同的原稿操作。")
        return manuscript, existing, request_digest
    if version_number(manuscript) != data["version"]:
        raise VersionConflict("原稿已更新，草稿未保存，请查看最新版本后再修改。")
    return manuscript, None, request_digest


def publish(manuscript, user, data, request_digest, research, blocks, origin="edit", source=None):
    check_size(blocks)
    identifiers = [str(item["id"]) for item in blocks]
    if len(identifiers) != len(set(identifiers)):
        raise ValidationError("正文块标识重复。")
    known = {str(block.pk): block for block in ContentBlock.objects.filter(pk__in=identifiers)}
    if any(block.manuscript_id != manuscript.pk for block in known.values()):
        raise ValidationError("正文块不属于当前原稿。")
    revision = ManuscriptRevision.objects.create(
        manuscript=manuscript,
        number=version_number(manuscript) + 1,
        research=research,
        created_by=user,
        request_key=data["request_key"],
        request_digest=request_digest,
        origin=origin,
        source=source or {},
    )
    current = (
        {
            str(item.block_id): item.block_version
            for item in manuscript.current_revision.items.select_related("block_version").all()
        }
        if manuscript.current_revision
        else {}
    )
    items = []
    for position, value in enumerate(blocks):
        pk = str(value["id"])
        block = known.get(pk) or ContentBlock.objects.create(
            id=pk,
            manuscript=manuscript,
            imported_from_id=source["source_version_id"] if origin == "import" else None,
        )
        previous = current.get(pk)
        if "version_id" in value:
            # 恢复只传数据库中的历史块版本，客户端编辑接口不接收此字段。
            block_version = BlockVersion.objects.get(pk=value["version_id"], block=block)
        elif (
            previous
            and previous.text == value["text"]
            and previous.heading_level == value["heading_level"]
        ):
            block_version = previous
        else:
            last = block.versions.aggregate(number=Max("number"))["number"] or 0
            block_version = BlockVersion.objects.create(
                block=block,
                number=last + 1,
                text=value["text"],
                heading_level=value["heading_level"],
            )
        items.append(
            RevisionBlock(
                revision=revision, block=block, block_version=block_version, position=position
            )
        )
    RevisionBlock.objects.bulk_create(items)
    manuscript.current_revision = revision
    manuscript.save(update_fields=["current_revision"])
    return revision


def import_preview(project, parse_id):
    run = get_object_or_404(
        ParseRun.objects.select_related("source_version__material", "job"),
        pk=parse_id,
        source_version__material__project=project,
    )
    source = run.source_version
    if not source.file_name.lower().endswith(".docx"):
        raise ValidationError("原稿导入仅支持已解析的 DOCX 正文。")
    chunks = list(searchable_chunks(project.pk).filter(run=run).order_by("ordinal"))
    if not chunks:
        raise VersionConflict("该解析已失效或材料已撤回，请重新选择。")
    paragraphs = {}
    for chunk in chunks:
        anchor = chunk.anchor
        if anchor.get("kind") != "docx":
            raise ValidationError("DOCX 段落定位不完整，不能导入。")
        paragraph = anchor["paragraph"]
        value = paragraphs.setdefault(
            paragraph,
            {
                "id": str(uuid5(run.pk, str(paragraph))),
                "text": "",
                "heading_level": chunk.heading_level,
            },
        )
        if anchor["start"] != len(value["text"]) or value["heading_level"] != chunk.heading_level:
            raise ValidationError("DOCX 段落片段不连续，不能导入。")
        value["text"] += chunk.text
    blocks = list(paragraphs.values())
    check_size(blocks)
    if any(len(item["text"]) > 20000 for item in blocks):
        raise ValidationError("单个 DOCX 段落超过 2 万字符，请拆分后导入。")
    snapshot = {
        "parse_id": str(run.pk),
        "source_version_id": str(source.pk),
        "sha256": source.sha256,
        "state_version": source.material.state_version,
        "file_name": source.file_name,
        "source_number": source.number,
        "coverage": run.coverage,
        "warnings": run.warnings,
    }
    return {"token": digest({**snapshot, "blocks": blocks}), "source": snapshot, "blocks": blocks}


def compare(before, after):
    left = {item["id"]: (index, item) for index, item in enumerate(before["blocks"])}
    right = {item["id"]: (index, item) for index, item in enumerate(after["blocks"])}
    changes = []
    for pk in dict.fromkeys([*left, *right]):
        old, new = left.get(pk), right.get(pk)
        old_item, new_item = old[1] if old else None, new[1] if new else None
        kinds = []
        if not old:
            kinds.append("added")
        elif not new:
            kinds.append("removed")
        else:
            if any(old_item[key] != new_item[key] for key in ["text", "heading_level"]):
                kinds.append("modified")
            if old[0] != new[0]:
                kinds.append("moved")
        if kinds:
            changes.append(
                {
                    "id": pk,
                    "kinds": kinds,
                    "before": old_item,
                    "after": new_item,
                    "before_position": old[0] + 1 if old else None,
                    "after_position": new[0] + 1 if new else None,
                }
            )
    return {
        "before": before["version"],
        "after": after["version"],
        "blocks": changes,
        "research": {
            key: {"before": before["research"][key], "after": after["research"][key]}
            for key in RESEARCH_FIELDS
            if before["research"][key] != after["research"][key]
        },
    }
