"""自制跨模块流程：真实存储/数据库与受控 Pi 输出，不作为模型效果证据。"""

import io
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from docx import Document
from rest_framework.test import APIClient

from core.cleanup import execute as execute_cleanup
from core.export_templates import (
    DEFAULT_CODE,
    DEFAULT_LAYOUT,
    DEFAULT_NAME,
    DEFAULT_RIGHTS,
    DEFAULT_SOURCE,
    register_template,
)
from core.graph import apply_snapshot, project_snapshot, purge_projection, sync_project
from core.library import default_bibliography
from core.models import ExportSnapshot, GraphState, Job, ProjectMember
from core.tests.evaluation_cases import IMPACT_SOURCES
from core.tests.test_cleanup import request_cleanup
from core.tests.test_disclosures import body as disclosure_body
from core.tests.test_disclosures import save as save_disclosure
from core.tests.test_exports import create as export_create
from core.tests.test_exports import download
from core.tests.test_expressions import decide, decision_body
from core.tests.test_expressions import run as expression_run
from core.tests.test_feedback import create_feedback, manual_task
from core.tests.test_graph import create as link_create
from core.tests.test_graph import query
from core.tests.test_impacts import change, scan
from core.tests.test_manuscripts import payload, save
from core.tests.test_materials import context as material_context
from core.tests.test_materials import intent, path, upload
from core.tests.test_parse_jobs import create as parse_create
from worker.tasks import execute_job

context = material_context
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def parsed(context, text, key, previous=None):
    changes = (
        {"material_id": str(previous.material_id), "base_revision": previous.number}
        if previous
        else {}
    )
    data = text.encode()
    source = intent(context, data=data, name=key + ".txt", request_key=key, **changes)
    with patch("core.parse_views.dispatch"):
        assert upload(context, source, data).status_code == 200
        run = parse_create(context, source, key=key)
        execute_job(str(run.job_id))
    assert Job.objects.get(pk=run.job_id).status == "succeeded"
    return source, run


def test_source_author_decision_export_correction_and_cleanup(context):
    client, project, author = context
    try:
        old = parsed(context, IMPACT_SOURCES[0], "original")
        chunk = old[1].chunks.get()
        located = client.get(path(project, f"chunks/{chunk.pk}/")).data
        assert located["chunk"]["text"] == IMPACT_SOURCES[0]
        assert located["chunk"]["anchor"]["kind"] == "txt"
        metadata = {
            **default_bibliography(old[0]),
            "title": "跨模块自制记录",
            "authors": ["自制作者"],
            "year": "2026",
            "source_scope": "research",
        }
        assert (
            client.put(
                path(project, f"files/{old[0].pk}/bibliography/"),
                {
                    "version": 0,
                    "snapshot": metadata,
                },
                format="json",
            ).status_code
            == 200
        )
        evidence = client.post(
            path(project, "evidence/"),
            {
                "chunk_id": str(chunk.pk),
                "request_key": "evidence",
                "note": "作者待核对",
                "tags": [],
            },
            format="json",
        )
        assert evidence.status_code == 201 and evidence.data["quote"] == IMPACT_SOURCES[0]
        outsider = get_user_model().objects.create_user(username="workflow-outsider")
        other = APIClient()
        other.force_authenticate(outsider)
        assert other.get(path(project, f"files/{old[0].pk}/")).status_code == 404
        membership = ProjectMember.objects.create(project=project, user=outsider, role="reviewer")
        assert other.get(path(project, f"chunks/{chunk.pk}/")).status_code == 200
        assert (
            other.post(
                path(project, "cleanup-preview/"),
                {
                    "scope": "material",
                    "material_id": str(old[0].material_id),
                },
                format="json",
            ).status_code
            == 403
        )
        membership.delete()
        assert other.get(path(project, f"chunks/{chunk.pk}/")).status_code == 404

        body = payload(
            blocks=[
                {"id": str(uuid4()), "text": IMPACT_SOURCES[0], "heading_level": 0},
                {"id": str(uuid4()), "text": "本研究对样本进行了观察。", "heading_level": 0},
            ]
        )
        manuscript = save(context, body).data
        link_create(context, manuscript, old, block_id=manuscript["blocks"][0]["id"])
        suggestion = expression_run(context, manuscript, old)
        decision = decision_body(suggestion)
        assert decide(context, suggestion, decision).status_code == 200
        assert decide(context, suggestion, decision).status_code == 200
        assert save(context, {**body, "request_key": "stale"}).status_code == 409
        current = client.get(path(project, "manuscript/")).data
        assert current["version"] == 2 and current["blocks"][1]["text"] == "本研究观察了样本。"
        feedback, _ = create_feedback(context, current, old)
        task, _ = manual_task(context, feedback, current)
        assert task["current"]["status"] == "todo"
        assert sync_project(project.pk)
        assert query(context)["status"] == "synced" and query(context)["count"] >= 2
        late_graph = project_snapshot(project.pk, GraphState.objects.get(project=project).revision)

        disclosure = save_disclosure(context, disclosure_body(context, verified=True))
        assert disclosure.status_code == 201
        template, _ = register_template(
            {
                "code": DEFAULT_CODE,
                "name": DEFAULT_NAME,
                "layout": DEFAULT_LAYOUT,
                "source_label": DEFAULT_SOURCE,
                "rights_note": DEFAULT_RIGHTS,
            },
            author,
        )
        selection = {
            "manuscript_version": 2,
            "disclosure_version": disclosure.data["saved_number"],
            "template_version_id": str(template.pk),
            "title": "跨模块自制交付",
            "author": "自制作者",
            "captions": [],
        }
        snapshot, _ = export_create(context, selection)
        with patch("core.export_jobs.s3_client", side_effect=OSError("fixture failure")):
            execute_job(str(snapshot.job_id))
        snapshot.job.refresh_from_db()
        assert snapshot.job.status == "failed" and snapshot.job.retryable
        latest_text = "作者另行改写的正文，本次结果仍待复核。"
        edited = payload(
            2,
            blocks=[
                {"id": current["blocks"][0]["id"], "text": latest_text, "heading_level": 0},
                {
                    "id": current["blocks"][1]["id"],
                    "text": current["blocks"][1]["text"],
                    "heading_level": 0,
                },
            ],
        )
        assert save(context, edited).status_code == 200
        with patch("core.job_views.dispatch"):
            retried = client.post(
                path(project, f"jobs/{snapshot.job_id}/retry/"), {"generation": 1}, format="json"
            )
        assert retried.status_code == 200
        execute_job(str(snapshot.job_id))
        frozen = download(context, snapshot)
        assert frozen.status_code == 200
        document = Document(io.BytesIO(b"".join(frozen.streaming_content)))
        texts = [p.text for p in document.paragraphs]
        assert IMPACT_SOURCES[0] in texts and latest_text not in texts
        assert "本研究观察了样本。" in "\n".join(texts)

        new = parsed(context, IMPACT_SOURCES[1], "corrected", previous=old[0])
        corrected, _ = change(context, old, new)
        _, affected = scan(context, corrected)
        assert any(item["location"]["block_id"] == current["blocks"][1]["id"] for item in affected)
        assert download(context, snapshot).status_code == 409
        assert sync_project(project.pk)
        record, _ = request_cleanup(context, old[0].material)
        execute_cleanup(record.pk)
        record.refresh_from_db()
        assert record.status == "succeeded"
        assert client.get(path(project, f"files/{old[0].pk}/")).status_code == 404
        assert client.get(path(project, f"files/{new[0].pk}/")).status_code == 404
        assert client.get(path(project, f"chunks/{chunk.pk}/")).status_code == 404
        assert not ExportSnapshot.objects.filter(pk=snapshot.pk).exists()
        remaining = client.get(path(project, "manuscript/")).data
        assert [block["text"] for block in remaining["blocks"]] == [latest_text]
        apply_snapshot(late_graph)
        assert query(context)["status"] == "synced" and query(context)["count"] == 0
    finally:
        purge_projection(project.pk)
