"""自制更正案例的真实本地模型检查；不运行于 CI，也不接触真实论文。"""

import argparse
import json
import os
import time
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from django.test import override_settings  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from core.ai_jobs import AIRun  # noqa: E402
from core.models import (  # noqa: E402
    ImpactDecision,
    ImpactItem,
    Job,
    Material,
    MaterialVersion,
    ParseRun,
    Project,
    ProjectPolicy,
    SourceChunk,
)
from core.tests.evaluation_cases import IMPACT_BLOCKS, IMPACT_SOURCES  # noqa: E402
from core.tests.evaluation_cleanup import remove_project  # noqa: E402
from core.tests.test_impacts import change, create_model, link_block, scan  # noqa: E402
from core.tests.test_manuscripts import payload, save  # noqa: E402
from worker.tasks import execute_job  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not settings.DEBUG or urlsplit(args.base_url).hostname not in ["127.0.0.1", "localhost"]:
        raise SystemExit("仅允许在 DEBUG 开发环境调用本机模型，使用自制数据。")
    prefix = "impact-eval-" + uuid4().hex
    user = get_user_model().objects.create_user(username=prefix)
    project = Project.objects.create(owner=user, name=prefix)
    ProjectPolicy.objects.create(project=project, version=1, created_by=user)
    client = APIClient(HTTP_HOST="localhost")
    client.force_authenticate(user)
    context = (client, project, user)
    try:
        material = Material.objects.create(
            project=project, title="自制温度记录", category="research", revision=2
        )
        sources = []
        for number, text in enumerate(IMPACT_SOURCES, 1):
            source = MaterialVersion.objects.create(
                material=material,
                number=number,
                created_by=user,
                request_key=str(uuid4()),
                request_snapshot={},
                file_name=f"self-authored-v{number}.txt",
                size=len(text.encode()),
                media_type="text/plain",
                bucket="synthetic-no-file",
                object_key=f"{prefix}/{number}",
                status="available",
            )
            job = Job.objects.create(
                project=project,
                created_by=user,
                kind="parse",
                status="succeeded",
                policy_version=1,
                idempotency_key=str(uuid4()),
                input_snapshot={},
            )
            run = ParseRun.objects.create(
                source_version=source,
                number=1,
                parser_version="synthetic-excerpt-v1",
                job=job,
                published_at=timezone.now(),
            )
            SourceChunk.objects.create(
                run=run, ordinal=1, text=text, anchor={"kind": "text", "line": 1}
            )
            sources.append((source, run))
        texts = IMPACT_BLOCKS
        manuscript = save(
            context,
            payload(
                blocks=[{"id": str(uuid4()), "heading_level": 0, "text": text} for text in texts]
            ),
        ).data
        for index in range(3):
            link_block(context, manuscript, sources[0], index)
        corrected, _ = change(context, sources[0], sources[1])
        run, registered = scan(context, corrected)
        start = time.monotonic()
        with (
            transaction.atomic(),
            override_settings(AI_MODEL=args.model, AI_BASE_URL=args.base_url, AI_API_KEY=""),
        ):
            with patch("core.jobs.dispatch"):
                job = create_model(context, run, manuscript)
            events = []
            tools = []
            handle = AIRun.handle

            def trace(runner, event):
                events.append(event)
                entry = None
                if event.get("type") == "tool":
                    entry = {"name": event["name"], "args": event.get("args")}
                    tools.append(entry)
                try:
                    result = handle(runner, event)
                except Exception as exc:
                    if entry is not None:
                        entry["error_code"] = getattr(exc, "code", type(exc).__name__)
                    raise
                if entry is not None:
                    entry["response"] = result
                return result

            with patch.object(AIRun, "handle", trace):
                execute_job(str(job.pk))
        job.refresh_from_db()
        candidates = list(ImpactItem.objects.filter(job=job).values_list("snapshot", flat=True))
        positions = {b["version_id"]: index + 1 for index, b in enumerate(manuscript["blocks"])}
        for candidate in candidates:
            candidate["position"] = positions[candidate["block_version_id"]]
        current_manuscript = project.manuscript
        current_manuscript.refresh_from_db()
        revision = current_manuscript.current_revision
        current_texts = list(
            revision.items.order_by("position").values_list("block_version__text", flat=True)
        )
        report = {
            "case": "self-authored-temperature-correction-v1",
            "events": events,
            "tools": tools,
            "input_manuscript": texts,
            "model": args.model,
            "prompt_version": job.input_snapshot["model"]["prompt_version"],
            "expected": "三处登记依赖由SQL查到；模型补充第4块，勿误报第5块；正文始终不变。",
            "registered_positions": sorted(i["location"]["position"] for i in registered),
            "status": job.status,
            "error_code": job.error_code,
            "elapsed_seconds": round(time.monotonic() - start, 2),
            "candidates": candidates,
            "summary": (job.output or {}).get("summary"),
            "calls": list(
                job.model_calls.order_by("number").values("number", "status", "usage", "elapsed_ms")
            ),
            "manuscript_unchanged": revision.number == 1 and current_texts == list(texts),
            "author_decision_count": ImpactDecision.objects.filter(item__run_id=run["id"]).count(),
        }
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in [
                        "status",
                        "error_code",
                        "elapsed_seconds",
                        "registered_positions",
                        "manuscript_unchanged",
                        "author_decision_count",
                    ]
                }
            ),
            flush=True,
        )
    finally:
        remove_project(project, user)


if __name__ == "__main__":
    main()
