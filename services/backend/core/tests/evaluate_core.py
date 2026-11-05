"""固定自制案例的配对实测。只同步派发方式，不模拟模型响应。"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.tests.evaluation_cases import catalog
from core.tests.evaluation_direct import execute, fetch_json, local_endpoint, model_metadata
from core.tests.evaluation_metrics import fingerprint, review_template, score, usage_total
from core.tests.evaluation_review import render

ROOT = Path(__file__).resolve().parents[4]
GROUPS = ["reading", "review", "expression", "feedback", "impact"]


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def source_manifest():
    paths = list((ROOT / "services/backend").rglob("*.py"))
    paths += list((ROOT / "services/pi-runner/src").glob("*.ts"))
    paths += [ROOT / "pnpm-lock.yaml", ROOT / "uv.lock"]
    paths += [Path(__file__).with_name("evaluation_review.html")]
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
        if "__pycache__" not in path.parts
    }


def normalize(case, report):
    items = []
    if report["status"] == "succeeded":
        if case["purpose"] in {"reading", "comparison"}:
            output = report["result"]
            for document in output["documents"]:
                sid = report["selected_sources"][document["version_id"]]
                for field, content in document["fields"].items():
                    items.append({"id": f"{sid}:{field}", "content": content})
            if output["comparison"] is not None:
                items.append({"id": "comparison", "content": output["comparison"]})
        else:
            field = {"review": "findings", "expression": "suggestions"}.get(
                case["purpose"], "candidates"
            )
            items += [
                {"id": f"item-{i}", "content": value} for i, value in enumerate(report[field], 1)
            ]
            for field in ["summary", "source_checks"]:
                if report.get(field):
                    items.append({"id": field, "content": report[field]})
    calls = report["calls"]
    usage = usage_total(calls)
    usage["total_input"] = (
        usage["input"] + usage["cache_read"]
        if usage["input"] is not None and usage["cache_read"] is not None
        else None
    )
    return {
        "id": case["id"] + "/system",
        "case": case["id"],
        "arm": "system",
        "status": report["status"],
        "error_code": report["error_code"],
        "items": items,
        "elapsed_seconds": report["elapsed_seconds"],
        "calls": calls,
        "usage": usage,
        "model": report["model"],
        "reasoning_effort": report.get("reasoning_effort", ""),
        "raw_report": report,
    }


def metadata(args):
    return {
        "suite": catalog(),
        "model": model_metadata(args.base_url, args.model),
        "sources": source_manifest(),
        "temperature": 0,
        "reasoning_effort": args.reasoning_effort,
        "limits": {
            "system_max_calls": 4,
            "direct_max_calls": 1,
            "reading_review_expression_tokens_per_call": 8192,
            "feedback_impact_tokens_per_call": 4096,
        },
        "comparability": [
            "相同任务材料；系统按工具读取，直接组一次得到所选全文。",
            "输出协议不同；直接组简化为 items/summary JSON，解析失败保留原文。",
            "系统逐项校验，直接组无业务校验；协议成功不等于语义正确。",
            "固定先运行系统各组再直接组；未平衡冷启动和缓存，不作因果效率结论。",
            "API 为本机已下载模型；无付费接口调用，硬件/电费及人工成本未测。",
        ],
        "cost": {
            "api_currency": "USD",
            "api_amount": 0,
            "hardware_amount": None,
            "human_amount": None,
        },
    }


def run_system(group, args, directory, run):
    cases = [case for case in run["suite"]["cases"] if case["id"].split("/")[0] == group]
    target = directory / f"system-{group}.json"
    marker = directory / f"system-{group}.complete.json"
    if not marker.exists():
        if target.exists():
            raise ValueError(f"{group} 有未完成运行；保留诊断，不能自动重跑掩盖失败。")
        script = "review" if group == "expression" else group
        command = [
            sys.executable,
            str(ROOT / f"services/backend/core/tests/evaluate_{script}.py"),
            "--model",
            args.model,
            "--base-url",
            args.base_url,
            "--output",
            str(target),
        ]
        if group in {"review", "expression"}:
            command += ["--purpose", group]
        env = {
            **os.environ,
            "AI_API_KEY": "",
            "AI_REASONING_EFFORT": args.reasoning_effort,
            "PYTHONPATH": str(ROOT / "services/backend"),
        }
        with (directory / f"system-{group}.log").open("w") as log:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1200,
                check=False,
            )
        if completed.returncode:
            raise RuntimeError(f"{group} 脚本失败，检查保存的专用日志。")
        write(marker, {"output_digest": fingerprint(json.loads(target.read_text()))})
    raw = json.loads(target.read_text())
    if json.loads(marker.read_text())["output_digest"] != fingerprint(raw):
        raise ValueError("系统原始结果被更改，拒绝继续。")
    reports = {r["case"]: r for r in (raw if isinstance(raw, list) else [raw])}
    if set(reports) != {case["id"].split("/", 1)[1] for case in cases}:
        raise ValueError("系统输出未覆盖固定案例集合。")
    for case in cases:
        record = normalize(case, reports[case["id"].split("/", 1)[1]])
        if record["model"] != args.model:
            raise ValueError("系统模型不匹配。")
        if record["reasoning_effort"] != args.reasoning_effort:
            raise ValueError("系统推理模式与直接组不匹配。")
        run["records"] = [row for row in run["records"] if row["id"] != record["id"]] + [record]
        print(
            json.dumps({key: record[key] for key in ["id", "status", "elapsed_seconds"]}),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument(
        "--reasoning-effort", choices=["", "none", "low", "medium", "high"], default=""
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    path = directory / "run.json"
    if args.review:
        result = score(json.loads(path.read_text()), json.loads(args.review.read_text()))
        write(directory / "scores.json", result)
        return
    if not args.model or not args.base_url:
        parser.error("运行需要 --model 和 --base-url。")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
    from django.conf import settings

    if not settings.DEBUG:
        raise ValueError("仅允许 DEBUG 开发环境的自制评测。")
    pinned = metadata(args)
    if args.resume:
        run = json.loads(path.read_text())
        if run["configuration_digest"] != fingerprint(pinned):
            raise ValueError("代码、样例或模型已改变，不能续写这一轮结果。")
        if run["status"] == "completed":
            print("本轮已结束，保留已有结果与复核表。")
            return
    else:
        directory.mkdir(parents=True, exist_ok=False)
        run = {
            **pinned,
            "configuration_digest": fingerprint(pinned),
            "records": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }
        write(path, run)
    try:
        for group in GROUPS:
            run_system(group, args, directory, run)
            write(path, run)
        for case in run["suite"]["cases"]:
            key = case["id"] + "/direct"
            if any(row["id"] == key for row in run["records"]):
                continue
            result = execute(
                case, args.base_url, args.model, reasoning_effort=args.reasoning_effort
            )
            record = {
                **result,
                "id": key,
                "case": case["id"],
                "arm": "direct",
                "calls": [{"usage": result["usage"]}],
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
            }
            run["records"].append(record)
            write(path, run)
            print(
                json.dumps({k: record[k] for k in ["id", "status", "elapsed_seconds"]}), flush=True
            )
        if fingerprint(metadata(args)) != run["configuration_digest"]:
            raise ValueError("运行期间代码或模型变化，结果不能作为固定配置评测。")
        _, origin = local_endpoint(args.base_url)
        run["runtime_after"] = [
            {key: model.get(key) for key in ["name", "digest", "context_length", "size_vram"]}
            for model in fetch_json(origin + "/api/ps")["models"]
            if model.get("name") == args.model
        ]
        run["status"] = "completed"
        run["finished_at"] = datetime.now(timezone.utc).isoformat()
        run.pop("error_code", None)
        write(path, run)
        write(directory / "review-template.json", review_template(run))
        (directory / "review.html").write_text(render(run))
    except Exception as error:
        run["status"], run["error_code"] = "interrupted", type(error).__name__
        write(path, run)
        raise


if __name__ == "__main__":
    main()
