"""从业务事实生成使用清单；不向模型请求自述，也不推算原创比例。"""

from collections import Counter

from django.db.models import Prefetch

from core.access import AI_ACTIONS
from core.ai_jobs import digest
from core.models import ExpressionSuggestion, Job, Manuscript, ModelCall, ReviewFinding


def pick(value, fields):
    return {field: value[field] for field in fields if field in value}


def usage_jobs(project_id):
    return (
        Job.objects.filter(project_id=project_id, kind__in=["ai", "index"])
        .select_related("reading_record", "review_record", "embedding_index")
        .prefetch_related(
            Prefetch("model_calls", queryset=ModelCall.objects.order_by("generation", "number")),
            Prefetch(
                "expression_suggestions",
                queryset=ExpressionSuggestion.objects.select_related(
                    "manuscript_revision", "block_version", "decision__manuscript_revision"
                ).order_by("id"),
            ),
            Prefetch("review_record__findings", queryset=ReviewFinding.objects.order_by("id")),
        )
        .order_by("created_at", "id")
    )


def call_data(call):
    return {
        "generation": call.generation,
        "number": call.number,
        "model": call.model,
        "prompt_version": call.prompt_version,
        "status": call.status,
        # 缺失用量保持未知，不折算成零；只输出运行器已支持的 token 字段。
        "usage": pick(call.usage, ["input", "output", "cache_read", "cache_write"])
        if call.usage is not None
        else None,
        "elapsed_ms": call.elapsed_ms,
        "error_code": call.error_code,
        "started_at": call.started_at.isoformat(),
        "finished_at": call.finished_at.isoformat() if call.finished_at else None,
    }


def job_data(job):
    snapshot = job.input_snapshot
    manuscript = snapshot.get("manuscript", {})
    reading = getattr(job, "reading_record", None)
    review = getattr(job, "review_record", None)
    index = getattr(job, "embedding_index", None)
    suggestions = []
    for suggestion in job.expression_suggestions.all():
        decision = getattr(suggestion, "decision", None)
        result = decision.manuscript_revision if decision else None
        suggestions.append(
            {
                "id": str(suggestion.pk),
                "block_id": str(suggestion.block_version.block_id),
                "block_version_id": str(suggestion.block_version_id),
                "manuscript_version": suggestion.manuscript_revision.number,
                "decision": {
                    "id": decision.pk,
                    "action": decision.action,
                    "created_by": decision.created_by_id,
                    "created_at": decision.created_at.isoformat(),
                    "manuscript_version": result.number if result else None,
                    "manuscript_revision_id": str(result.pk) if result else None,
                }
                if decision
                else None,
            }
        )
    findings = (
        [
            {
                "id": str(finding.pk),
                "status": finding.status,
                "revision": finding.revision,
                "block_version_id": str(finding.block_version_id),
            }
            for finding in review.findings.all()
        ]
        if review
        else []
    )
    # 旧摘记入口只有任务输出；结构化入口通过正式业务表计数，避免重复计数。
    notes = (
        len((job.output or {}).get("proposals", []))
        if (job.kind == "ai" and job.status == "succeeded" and not snapshot.get("purpose"))
        else 0
    )
    return {
        "id": str(job.pk),
        "kind": job.kind,
        "purpose": "index" if job.kind == "index" else snapshot.get("purpose", "note"),
        "status": job.status,
        "generation": job.generation,
        "error_code": job.error_code,
        "created_at": job.created_at.isoformat(),
        "created_by": job.created_by_id,
        "policy_version": job.policy_version,
        "model": pick(snapshot.get("model", {}), ["model", "prompt_version", "runtime"]),
        "embedding": pick(
            snapshot.get("embedding", {}),
            [
                "model_name",
                "dimension",
                "artifact_digest",
                "pipeline_version",
                "runtime",
            ],
        ),
        "input": {
            "version_ids": snapshot.get("version_ids", []),
            "source_count": len(snapshot.get("sources", [])),
            "sources_digest": digest(snapshot.get("sources", [])),
            "manuscript_revision_id": manuscript.get("revision_id"),
            "manuscript_version": manuscript.get("version"),
            "blocks": [
                pick(block, ["block_id", "version_id", "position"])
                for block in manuscript.get("blocks", [])
            ],
        },
        "calls": [call_data(call) for call in job.model_calls.all()],
        "reading": {"id": str(reading.pk), "author_revision": reading.revision}
        if reading
        else None,
        "review": {"id": str(review.pk), "findings": findings} if review else None,
        "suggestions": suggestions,
        "notes": notes,
        "index": {"id": str(index.pk), "published": index.published_at is not None}
        if index
        else None,
    }


def facts_for(project):
    # 调用方持有项目锁，和 Worker 的调用/发布、采纳、稿件写入串行化。
    jobs = [job_data(job) for job in usage_jobs(project.pk)]
    purposes = {}
    for job in jobs:
        counts = purposes.setdefault(job["purpose"], Counter())
        counts["tasks"] += 1
        counts["calls"] += len(job["calls"])
        counts["successful_calls"] += sum(call["status"] == "succeeded" for call in job["calls"])
        counts["published_tasks"] += job["status"] == "succeeded"
        counts["reading_records"] += bool(job["reading"])
        counts["review_findings"] += len(job["review"]["findings"]) if job["review"] else 0
        counts["expression_suggestions"] += len(job["suggestions"])
        counts["notes"] += job["notes"]
        counts["accepted"] += sum(
            bool(item["decision"] and item["decision"]["action"] in ["accepted", "edited"])
            for item in job["suggestions"]
        )
        counts["rejected"] += sum(
            bool(item["decision"] and item["decision"]["action"] == "rejected")
            for item in job["suggestions"]
        )
    summary = dict(sum(purposes.values(), Counter()))
    # Counter 会移除零值；空项目与有任务的项目使用一致的字段。
    for field in [
        "tasks",
        "calls",
        "successful_calls",
        "published_tasks",
        "reading_records",
        "review_findings",
        "expression_suggestions",
        "notes",
        "accepted",
        "rejected",
    ]:
        summary.setdefault(field, 0)
    manuscript_version = (
        Manuscript.objects.filter(project=project)
        .values_list("current_revision__number", flat=True)
        .first()
        or 0
    )
    return {
        "schema": 1,
        "manuscript_version": manuscript_version,
        "summary": summary,
        "purposes": purposes,
        "jobs": jobs,
    }


def draft_for(facts):
    lines = [f"本清单对应稿件 v{facts['manuscript_version']}，由作者核对和补充。"]
    labels = {**AI_ACTIONS, "note": "阅读摘记", "index": "本地资料向量索引"}
    for purpose, counts in facts["purposes"].items():
        if purpose == "index":
            lines.append(
                f"本地资料向量索引：创建 {counts['tasks']} 个任务，"
                f"完成 {counts['published_tasks']} 个；未计入生成模型调用。"
            )
        else:
            lines.append(
                f"{labels.get(purpose, purpose)}：发起 {counts['calls']} 次模型调用，"
                f"发布 {counts['reading_records']} 份阅读记录、{counts['notes']} 条摘记、"
                f"{counts['review_findings']} 条诊断及 "
                f"{counts['expression_suggestions']} 条表达建议；"
                f"实际采纳 {counts['accepted']} 条表达修改。"
            )
    if not facts["jobs"]:
        lines.append("暂无系统内模型任务记录。")
    lines.append(
        "系统外 AI 使用由作者另行补充。调用、输出及核对均不等于实际采纳；"
        "本清单不推算原创比例，不构成原创证明或学术合规认证。"
    )
    return "\n".join(lines)
