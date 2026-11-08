import json

from django.conf import settings

from core.ai.configuration import SYSTEM_PROMPT
from core.ai.runtime import AIRun
from core.ai.state import checkpoint


def execute_ai(job):
    from core.ai.transport import run_pi

    if not checkpoint(job.pk, job.generation):
        return
    run = AIRun(job)
    config = {
        "base_url": settings.AI_BASE_URL,
        "model": settings.AI_MODEL,
        "api_key": settings.AI_API_KEY,
        "max_tokens_field": job.input_snapshot["model"]["max_tokens_field"],
        "reasoning_effort": job.input_snapshot["model"]["reasoning_effort"],
        "system_prompt": SYSTEM_PROMPT,
        "prompt": "请阅读以下片段并整理一条有出处的待核对摘记。片段编号："
        + ", ".join(item["chunk_id"] for item in job.input_snapshot["sources"][:5]),
    }
    purpose = job.input_snapshot.get("purpose")
    if purpose == "impact":
        from core.impacts.ai import IMPACT_PROMPT

        config.update(
            purpose=purpose,
            system_prompt=IMPACT_PROMPT,
            block_version_ids=[
                b["version_id"]
                for b in job.input_snapshot["impact"]["manuscript"]["blocks"]
                if b["version_id"] not in job.input_snapshot["impact"]["registered_blocks"]
            ],
            max_tokens=4096,
            prompt="先调用 read_impact，再用 submit_impact 提交可能相关位置。",
        )
    if purpose == "feedback":
        from core.feedback.service import FEEDBACK_PROMPT

        config.update(
            purpose=purpose,
            system_prompt=FEEDBACK_PROMPT,
            max_tokens=4096,
            prompt="先调用 read_feedback，再用 submit_feedback 提交候选任务。",
        )
    if purpose in ["reading", "comparison", "review", "expression"]:
        from core.reading.service import READING_PROMPT

        # 每个文件提供入口；不能把前几个片段误当作全部资料已读。
        catalog = []
        for version_id in job.input_snapshot["version_ids"]:
            sources = [
                item
                for item in job.input_snapshot["sources"]
                if item["source_version_id"] == version_id
            ]
            catalog.append(
                {
                    "version_id": version_id,
                    "source_scope": sources[0]["source_scope"],
                    "chunk_count": len(sources),
                    "chunk_ids": [item["chunk_id"] for item in sources[:12]],
                }
            )
        config.update(
            purpose=purpose,
            version_ids=job.input_snapshot["version_ids"],
            system_prompt=READING_PROMPT,
            max_tokens=8192,
            # 比较需在一个响应中提交多篇资料；单请求预算与 8192 token 输出匹配。
            # 总任务仍受 run_pi 的 180 秒期限和 MAX_CALLS 限制。
            request_timeout_ms=120_000 if purpose == "comparison" else 60_000,
            prompt=(
                "请先直接调用 read_evidence 批量读取下面目录中的 chunk_ids，不要先检索。"
                "读完后调用 submit_reading。documents 必须包含下列每个 version_id，"
                "一篇对应一项且含六个字段，不得只返回其中一篇。\n"
            )
            + json.dumps(
                {"task": purpose, "question": job.input_snapshot["question"], "sources": catalog},
                ensure_ascii=False,
            ),
        )
        if purpose in ["review", "expression"]:
            from core.expressions.service import EXPRESSION_PROMPT
            from core.reviews.service import REVIEW_PROMPT

            submit = "submit_review" if purpose == "review" else "submit_expression"
            read_prompt = "先调用 read_manuscript。" + (
                "再直接调用 read_evidence 批量读取下面目录的 chunk_ids，不要先检索。"
                if catalog
                else "本次没有外部材料，只能检查原稿和作者研究说明，不要编造证据编号。"
            )
            if catalog:
                read_prompt = (
                    "第一轮在同一响应中提出 read_manuscript 与 read_evidence 两个只读调用；"
                    "后者一次读取下面目录的 chunk_ids，执行器依次执行，不要先检索。"
                )

            config.update(
                system_prompt=REVIEW_PROMPT if purpose == "review" else EXPRESSION_PROMPT,
                block_version_ids=[
                    item["version_id"] for item in job.input_snapshot["manuscript"]["blocks"]
                ],
                prompt=(read_prompt + f"随后必须调用 {submit} 提交结果，普通文字答复不会保存。\n")
                + json.dumps(
                    {
                        "question": job.input_snapshot["question"],
                        "sources": catalog,
                        "manuscript_version": job.input_snapshot["manuscript"]["version"],
                    },
                    ensure_ascii=False,
                ),
            )
            if purpose == "review":
                config["prompt"] += (
                    "\n只提交原稿中确有具体问题的主张；已有依据支持的内容不用列为问题。"
                    "研究说明只作核对依据，不作为待修改正文。不要为每种分类各造一条问题。"
                )
    run_pi(
        config,
        run.handle,
        lambda: checkpoint(job.pk, job.generation),
        timeout_seconds=180
        if purpose in ["reading", "comparison", "review", "expression"]
        else None,
    )
