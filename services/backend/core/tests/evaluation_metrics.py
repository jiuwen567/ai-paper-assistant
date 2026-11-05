"""根据显式复核表计数，不用关键词命中或模型自评冒充语义正确性。"""

import hashlib
import json
import math


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def unique(rows, key):
    result = {}
    for row in rows:
        value = row[key]
        if not isinstance(value, str) or not value or value in result:
            raise ValueError(f"重复或无效标识：{key}")
        result[value] = row
    return result


def measured(value, integer=False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("实测值必须是非负有限数或 null。")
    if not math.isfinite(value) or value < 0 or (integer and not isinstance(value, int)):
        raise ValueError("实测值必须是非负有限数或 null。")
    return value


def review_template(run):
    return {
        "run_digest": fingerprint(run),
        "review_type": "pending",
        "reviewer": "",
        "gold_confirmed": False,
        "records": [
            {
                "id": row["id"],
                "review_seconds": None,
                "human_operations": None,
                "items": [
                    {"id": item["id"], "verdict": "pending", "target": None, "reason": ""}
                    for item in row["items"]
                ],
                "control_checked": False,
            }
            for row in run["records"]
        ],
    }


def score(run, review):
    if run.get("status") != "completed":
        raise ValueError("整轮评测未完成或配置发生变化，不能评分。")
    if review["run_digest"] != fingerprint(run):
        raise ValueError("复核表与运行结果不匹配，请重新生成。")
    if review["review_type"] not in {"human", "assistant_draft"}:
        raise ValueError("尚未复核；不能将待定结果计为通过。")
    if not isinstance(review["reviewer"], str) or not review["reviewer"].strip():
        raise ValueError("必须注明复核者。")
    if review["gold_confirmed"] is not True:
        raise ValueError("必须先核对预期标注。")
    cases = unique(run["suite"]["cases"], "id")
    records = unique(run["records"], "id")
    judgments = unique(review["records"], "id")
    if records.keys() != judgments.keys():
        raise ValueError("复核表必须覆盖本轮全部结果。")
    expected = {(case, arm) for case in cases for arm in ["system", "direct"]}
    actual = [(row["case"], row["arm"]) for row in records.values()]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("必须包含每个案例的两组结果，不能遗漏或重复计数。")
    output = []
    for key, row in records.items():
        gold = unique(cases[row["case"]]["targets"], "id")
        items = unique(row["items"], "id")
        judgment = judgments[key]
        labels = unique(judgment["items"], "id")
        if items.keys() != labels.keys() or judgment["control_checked"] is not True:
            raise ValueError("必须核对全部输出项和阴性/边界条件。")
        if row["status"] not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("运行尚未结束。")
        if row["status"] != "succeeded" and items:
            raise ValueError("失败任务的内部草稿不能计为已交付结果。")
        matched, fp, partial = set(), 0, 0
        for item in labels.values():
            verdict, target = item["verdict"], item["target"]
            if verdict not in {"correct", "incorrect", "partial", "neutral"}:
                raise ValueError("存在待定或未知判断。")
            if not isinstance(item["reason"], str) or not item["reason"].strip():
                raise ValueError("每项判断必须说明理由。")
            if verdict == "correct":
                if target not in gold:
                    raise ValueError("正确项必须对应一个已登记预期项。")
                if target in matched:
                    fp += 1  # 重复输出不增加正确项。
                matched.add(target)
            else:
                if target is not None:
                    raise ValueError("非正确项不能消耗预期标注。")
                fp += verdict in {"incorrect", "partial"}
                partial += verdict == "partial"
        seconds = measured(judgment["review_seconds"])
        operations = measured(judgment["human_operations"], integer=True)
        if review["review_type"] != "human" and (seconds is not None or operations is not None):
            raise ValueError("AI 草案不能填写人类实测时间或操作量。")
        output.append(
            {
                "id": key,
                "case": row["case"],
                "arm": row["arm"],
                "purpose": cases[row["case"]]["purpose"],
                "status": row["status"],
                "tp": len(matched),
                "fp": fp,
                "fn": len(gold) - len(matched),
                "partial": partial,
                "expected_count": len(gold),
                "delivered_items": len(items),
                "review_seconds": seconds,
                "human_operations": operations,
            }
        )
    return {
        "review_type": review["review_type"],
        "provisional": review["review_type"] != "human",
        "run_digest": review["run_digest"],
        "records": output,
    }


def usage_total(calls):
    # 供应商未报告时保留未知，不因 Pi 成本表填零而声称免费。
    names = ["input", "output", "cache_read", "cache_write"]
    if not calls:
        return {name: 0 for name in names}
    return {
        name: sum(call["usage"][name] for call in calls)
        if all(
            isinstance(call.get("usage"), dict)
            and measured(call["usage"].get(name), integer=True) is not None
            for call in calls
        )
        else None
        for name in names
    }
