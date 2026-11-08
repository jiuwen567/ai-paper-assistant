from django.db.models import Max

from core.common.request_keys import fingerprint
from core.library.service import searchable_chunks
from core.manuscripts.locations import location_data
from core.models import (
    EvidenceLink,
    ExpressionSuggestion,
    FeedbackTask,
    GraphState,
    ImpactItem,
    ImpactRun,
    Manuscript,
    ManuscriptCitation,
    MaterialChange,
    RevisionBlock,
)


def project_id(change):
    return change.source_version.material.project_id


def source_state(source):
    source.refresh_from_db()
    material = source.material
    material.refresh_from_db()
    parse = (
        source.parses.filter(published_at__isnull=False, job__status="succeeded")
        .order_by("-number")
        .first()
    )
    return {
        "id": str(source.pk),
        "number": source.number,
        "file_name": source.file_name,
        "material_id": str(material.pk),
        "title": material.title,
        "access_state": material.access_state,
        "state_version": material.state_version,
        "usage_state": source.usage_state,
        "usage_version": source.usage_version,
        "status": source.status,
        "sha256": source.sha256,
        "parse_id": str(parse.pk) if parse else None,
    }


def change_sources(change):
    return {
        "old": source_state(change.source_version),
        "new": source_state(change.replacement) if change.replacement_id else None,
    }


def record_global_withdrawal(material, user, note):
    # 兼容既有整个材料撤回入口；不覆盖文件的更正状态，恢复材料也不能复活旧依据。
    for source in material.versions.filter(status="available"):
        snapshot = source_state(source)
        MaterialChange.objects.create(
            source_version=source,
            kind="withdrawal",
            scope="material",
            note=note,
            state_snapshot={"old": snapshot, "new": None},
            created_by=user,
            request_key=f"material-state:{material.state_version}",
            request_digest=fingerprint({"state_version": material.state_version, "note": note}),
        )


def current_revision(pid):
    manuscript = (
        Manuscript.objects.select_related("current_revision").filter(project_id=pid).first()
    )
    return manuscript.current_revision if manuscript else None


def registered_dependencies(change, revision):
    """查询 PostgreSQL 中的实际记录，不把图服务缺失/滞后解释为没有影响。"""
    pid, source_id = project_id(change), change.source_version_id
    blocks = (
        {item.block_version_id: item for item in revision.items.select_related("block_version")}
        if revision
        else {}
    )
    refs, alternatives = {}, {}
    valid_ids = set(searchable_chunks(pid).values_list("pk", flat=True))

    def add(block_id, chunk, record, kind):
        source = chunk.run.source_version
        entry = {
            "record_id": str(record.pk),
            "kind": kind,
            "chunk_id": str(chunk.pk),
            "source_version_id": str(source.pk),
        }
        if source.pk == source_id:
            refs.setdefault(block_id, []).append(entry)
        elif chunk.pk in valid_ids:
            alternatives.setdefault(block_id, []).append(entry)

    links = (
        EvidenceLink.objects.filter(project_id=pid, block_version_id__in=blocks)
        .select_related("chunk__run__source_version")
        .prefetch_related("decisions")
    )
    for link in links:
        decision = max(link.decisions.all(), key=lambda item: item.number)
        if decision.state == "confirmed":
            add(link.block_version_id, link.chunk, link, f"author_{decision.kind}")
    for citation in ManuscriptCitation.objects.filter(block_version_id__in=blocks).select_related(
        "chunk__run__source_version"
    ):
        add(citation.block_version_id, citation.chunk, citation, "citation")
    items = []
    affected_blocks = set()
    for block_id, reasons in refs.items():
        block = blocks[block_id].block_version
        affected_blocks.add(block.block_id)
        items.append(
            {
                "key": f"paragraph:{block.block_id}",
                "block_version": block,
                "snapshot": {
                    "kind": "paragraph",
                    "location": location_data(revision, block),
                    "dependencies": reasons,
                    "other_evidence": alternatives.get(block_id, []),
                    "instruction": "核对材料变化对原论述的影响；存在其他依据也须由作者判断。",
                },
            }
        )
    suggestions = ExpressionSuggestion.objects.filter(
        job__project_id=pid,
        job__status="succeeded",
        decision__isnull=True,
        job__input_snapshot__version_ids__contains=[str(source_id)],
    ).select_related("job", "manuscript_revision", "block_version")
    for suggestion in suggestions:
        items.append(
            {
                "key": f"suggestion:{suggestion.pk}",
                "suggestion": suggestion,
                "snapshot": {
                    "kind": "suggestion",
                    "location": location_data(
                        suggestion.manuscript_revision, suggestion.block_version
                    ),
                    "job_id": str(suggestion.job_id),
                    "suggestion_id": str(suggestion.pk),
                    "instruction": (
                        "该待处理建议的生成输入包含此版本，须重新核对或拒绝；不等同于逐句支持关系。"
                    ),
                },
            }
        )
    tasks = (
        FeedbackTask.objects.filter(feedback__project_id=pid)
        .select_related("feedback__source_chunk__run")
        .prefetch_related("revisions__block_version", "revisions__manuscript_revision")
    )
    for task in tasks:
        latest = max(task.revisions.all(), key=lambda item: item.number)
        feedback_source = task.feedback.source_chunk
        source_dependency = (
            feedback_source is not None and feedback_source.run.source_version_id == source_id
        )
        block_dependency = (
            latest.block_version_id and latest.block_version.block_id in affected_blocks
        )
        if not source_dependency and not block_dependency:
            continue
        items.append(
            {
                "key": f"task:{task.pk}",
                "task": task,
                "snapshot": {
                    "kind": "task",
                    "task_id": str(task.pk),
                    "task_version": latest.number,
                    "title": latest.title,
                    "status": latest.status,
                    "location": location_data(latest.manuscript_revision, latest.block_version),
                    "instruction": "意见来源包含变更材料，请复核任务。"
                    if source_dependency
                    else "任务关联了受影响正文，请复核处理结果。",
                },
            }
        )
    return sorted(items, key=lambda item: item["key"])


def create_run(change, user, data):
    revision = current_revision(project_id(change))
    number = (change.runs.aggregate(value=Max("number"))["value"] or 0) + 1
    run = ImpactRun.objects.create(
        change=change,
        number=number,
        manuscript_revision=revision,
        source_snapshot=change_sources(change),
        created_by=user,
        request_key=data["request_key"],
        request_digest=fingerprint(data),
    )
    ImpactItem.objects.bulk_create(
        [
            ImpactItem(run=run, origin="registered", **item)
            for item in registered_dependencies(change, revision)
        ]
    )
    return run


def item_facts(item):
    change = item.run.change
    pid = project_id(change)
    revision = current_revision(pid)
    facts = {
        "sources": change_sources(change),
        "manuscript_revision_id": str(revision.pk) if revision else None,
        "graph_revision": GraphState.objects.filter(project_id=pid)
        .values_list("revision", flat=True)
        .first(),
    }
    if item.block_version_id:
        current = RevisionBlock.objects.filter(
            revision=revision, block_id=item.block_version.block_id
        ).first()
        facts["block_version_id"] = str(current.block_version_id) if current else None
    elif item.suggestion_id:
        decision = getattr(item.suggestion, "decision", None)
        facts["suggestion_decision"] = (
            {"id": decision.pk, "action": decision.action} if decision else None
        )
    else:
        latest = item.task.revisions.order_by("-number").first()
        facts["task_version"] = latest.number
        facts["task_status"] = latest.status
    return facts
