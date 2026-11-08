from rest_framework import serializers

from core.ai.configuration import MAX_TOOLS
from core.common.errors import ParseFailure
from core.library.service import searchable_chunks


class SearchInput(serializers.Serializer):
    query = serializers.CharField(max_length=100)


class ReadInput(serializers.Serializer):
    chunk_id = serializers.UUIDField()


class ReadBatchInput(serializers.Serializer):
    chunk_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=64)


class ProposalInput(serializers.Serializer):
    text = serializers.CharField(max_length=2000)
    chunk_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=5)


def validate_arguments(name, args):
    schema = {
        "project_search": SearchInput,
        "read_evidence": ReadInput,
        "save_note": ProposalInput,
        "submit_suggestion": ProposalInput,
    }.get(name)
    if schema is None or not isinstance(args, dict):
        raise ParseFailure("tool_denied", "模型请求了未授权工具。")
    serializer = schema(data=args)
    if set(args) != set(serializer.fields) or not serializer.is_valid():
        raise ParseFailure("tool_schema_invalid", "模型工具参数未通过校验。")
    return serializer.validated_data


def handle_tool(run, job, message):
    is_reading = job.input_snapshot.get("purpose") in ["reading", "comparison"]
    is_review = job.input_snapshot.get("purpose") == "review"
    is_expression = job.input_snapshot.get("purpose") == "expression"
    is_feedback = job.input_snapshot.get("purpose") == "feedback"
    is_manuscript = is_review or is_expression
    is_impact = job.input_snapshot.get("purpose") == "impact"
    structured = is_reading or is_manuscript or is_feedback or is_impact
    if run.call is not None or run.calls == 0 or run.tools >= (32 if structured else MAX_TOOLS):
        raise ParseFailure("tool_call_limit", "工具调用达到上限或顺序异常。")
    run.tools += 1
    name = message.get("name")
    if is_impact and name not in ["read_impact", "submit_impact"]:
        raise ParseFailure("tool_denied", "影响补查只能读取固定变更范围和提交候选。")
    if is_feedback and name not in ["read_feedback", "submit_feedback"]:
        raise ParseFailure("tool_denied", "反馈拆分只能读取已选意见和提交候选任务。")
    if (
        is_manuscript
        and not job.input_snapshot["version_ids"]
        and name in ["project_search", "read_evidence"]
    ):
        raise ParseFailure("tool_denied", "未选择材料，不能调用资料工具。")
    details = {"name": name, "number": run.tools}
    if is_impact and name == "read_impact":
        from core.impacts.ai import read_impact

        if message.get("args") != {}:
            raise ParseFailure("tool_schema_invalid", "读取影响范围不接受扩展参数。")
        result = read_impact(job)
        run.impact_read = True
    elif is_impact and name == "submit_impact":
        from core.impacts.ai import validate_output

        try:
            candidate = validate_output(job, message.get("args"), run.impact_read)
        except ParseFailure as exc:
            if run.impact is not None or exc.code not in {
                "impact_quote_invalid",
                "impact_anchor_invalid",
                "impact_duplicate",
            }:
                raise
            job.ai_events.create(
                generation=run.generation,
                kind="validation_error",
                details={"code": exc.code, "number": run.tools},
            )
            return None, {
                "status": "rejected",
                "code": exc.code,
                "message": exc.message + " 请直接修正 submit_impact，不重复读取已有内容。",
            }
        if run.impact is not None and run.impact != candidate:
            raise ParseFailure("impact_resubmitted", "重复提交了不同候选。")
        run.impact = candidate
        result = {"status": "staged"}
    elif is_feedback and name == "read_feedback":
        from core.feedback.service import read_feedback

        if message.get("args") != {}:
            raise ParseFailure("tool_schema_invalid", "读取意见不接受范围扩展参数。")
        result = read_feedback(job)
        run.feedback_read = True
    elif is_feedback and name == "submit_feedback":
        from core.feedback.service import validate_split

        try:
            candidate = validate_split(job, message.get("args"), run.feedback_read)
        except ParseFailure as exc:
            if run.feedback is not None or exc.code not in {
                "feedback_quote_invalid",
                "feedback_duplicate",
            }:
                raise
            job.ai_events.create(
                generation=run.generation,
                kind="validation_error",
                details={"code": exc.code, "number": run.tools},
            )
            return None, {"status": "rejected", "code": exc.code, "message": exc.message}
        if run.feedback is not None and run.feedback != candidate:
            raise ParseFailure("feedback_resubmitted", "重复提交了不同的候选任务。")
        run.feedback = candidate
        result = {"status": "staged"}
    elif is_manuscript and name == "read_manuscript":
        from core.reviews.service import read_manuscript

        if message.get("args") != {}:
            raise ParseFailure("tool_schema_invalid", "读取原稿不接受范围扩展参数。")
        result = read_manuscript(job)
        run.manuscript_read = True
    elif is_review and name == "submit_review":
        from core.reviews.service import validate_review

        try:
            candidate = validate_review(job, message.get("args"), run.read_ids, run.manuscript_read)
        except ParseFailure as exc:
            # 仅允许修正尚未暂存的内容错误；权限、范围及版本检查仍立即终止。
            if run.review is not None or exc.code not in {
                "review_quote_invalid",
                "review_citation_invalid",
                "review_research_invalid",
                "review_support_invalid",
                "review_number_mismatch",
                "review_duplicate_finding",
            }:
                raise
            job.ai_events.create(
                generation=run.generation,
                kind="validation_error",
                details={"code": exc.code, "number": run.tools},
            )
            return None, {
                "status": "rejected",
                "code": exc.code,
                "message": exc.message
                + " 已读结果仍在上下文中，请直接修正 submit_review，不必重复读取已有内容。",
            }
        if run.review is not None and run.review != candidate:
            raise ParseFailure("review_duplicate", "模型重复提交了不同的诊断结果。")
        run.review = candidate
        result = {"status": "staged"}
    elif is_expression and name == "submit_expression":
        from core.expressions.service import validate_expression

        try:
            candidate = validate_expression(
                job, message.get("args"), run.read_ids, run.manuscript_read
            )
        except ParseFailure as exc:
            if run.expression is not None or exc.code not in {
                "review_quote_invalid",
                "expression_citation_invalid",
                "expression_duplicate",
                "expression_unchanged",
                "expression_content_changed",
            }:
                raise
            job.ai_events.create(
                generation=run.generation,
                kind="validation_error",
                details={"code": exc.code, "number": run.tools},
            )
            return None, {
                "status": "rejected",
                "code": exc.code,
                "message": exc.message + " 请利用已读结果直接修正 submit_expression，不必重读。",
            }
        if run.expression is not None and run.expression != candidate:
            raise ParseFailure("expression_resubmitted", "重复提交了不同的表达建议。")
        run.expression = candidate
        result = {"status": "staged"}
    elif is_reading and name == "submit_reading":
        from core.reading.service import validate_reading

        try:
            candidate = validate_reading(job, message.get("args"), run.read_ids)
        except ParseFailure as exc:
            if run.reading is not None or exc.code not in {
                "reading_citation_invalid",
                "reading_number_mismatch",
            }:
                raise
            job.ai_events.create(
                generation=run.generation,
                kind="validation_error",
                details={"code": exc.code, "number": run.tools},
            )
            return None, {"status": "rejected", "code": exc.code, "message": exc.message}
        if run.reading is not None and run.reading != candidate:
            raise ParseFailure("reading_duplicate", "模型重复提交了阅读结果。")
        run.reading = candidate
        result = {"status": "staged"}
    else:
        if structured and name not in ["project_search", "read_evidence"]:
            raise ParseFailure("tool_denied", "任务请求了未授权工具。")
        if structured and name == "read_evidence":
            raw = message.get("args")
            serializer = ReadBatchInput(data=raw)
            if not isinstance(raw, dict) or set(raw) != {"chunk_ids"} or not serializer.is_valid():
                raise ParseFailure("tool_schema_invalid", "读取片段参数未通过校验。")
            args = serializer.validated_data
            if len(args["chunk_ids"]) != len(set(args["chunk_ids"])):
                raise ParseFailure("tool_schema_invalid", "读取片段不能重复。")
        else:
            args = validate_arguments(name, message.get("args"))
        result = source_tool(run, job, name, args)
    return details, result


def source_tool(run, job, name, args):
    sources = {item["chunk_id"]: item for item in job.input_snapshot["sources"]}
    chunks = searchable_chunks(job.project_id).filter(pk__in=sources)
    if name == "project_search":
        return [
            {"chunk_id": str(chunk.pk), "excerpt": chunk.text[:300]}
            for chunk in chunks.filter(text__icontains=args["query"]).order_by("id")[:8]
        ]
    if name == "read_evidence":
        ids = (
            [str(pk) for pk in args["chunk_ids"]]
            if "chunk_ids" in args
            else [str(args["chunk_id"])]
        )
        if not set(ids) <= set(sources):
            raise ParseFailure("tool_scope_denied", "模型请求了任务范围外的资料。")
        output = []
        for chunk_id in ids:
            chunk = chunks.get(pk=chunk_id)
            if "chunk_ids" in args and run.read_characters + len(chunk.text) > 8000:
                output.append(
                    {
                        "chunk_id": chunk_id,
                        "unavailable": "本次原文读取已达到 8000 字符上限，此片段未发送。",
                    }
                )
                continue
            run.read_characters += len(chunk.text)
            run.read_ids.add(chunk_id)
            context = {**sources[chunk_id], "text": chunk.text, "anchor": chunk.anchor}
            if "chunk_ids" in args:
                context = {
                    key: context[key]
                    for key in [
                        "chunk_id",
                        "source_version_id",
                        "source_scope",
                        "text",
                        "anchor",
                    ]
                }
            output.append(context)
        return output if "chunk_ids" in args else output[0]
    ids = [str(pk) for pk in args["chunk_ids"]]
    if len(ids) != len(set(ids)) or not set(ids) <= run.read_ids:
        raise ParseFailure("proposal_source_invalid", "待核对结果引用了本次未读取的资料。")
    run.proposals.append(
        {
            "kind": "note" if name == "save_note" else "suggestion",
            "text": args["text"],
            "sources": [sources[pk] for pk in ids],
        }
    )
    return {"status": "staged"}
