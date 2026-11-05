"""自制原稿，真实 PostgreSQL / S3；不把 XML 检查算作 Word 打开验收。"""

import io
import zipfile
from contextlib import closing
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from docx import Document

from core.export_jobs import execute_export, publish_export
from core.export_templates import (
    DEFAULT_CODE,
    DEFAULT_LAYOUT,
    DEFAULT_NAME,
    DEFAULT_RIGHTS,
    DEFAULT_SOURCE,
    register_template,
)
from core.health import s3_client
from core.jobs import claim
from core.models import ExportDownload, ExportSnapshot, ExportTemplateVersion
from core.tests.test_disclosures import body as disclosure_body
from core.tests.test_disclosures import save as save_disclosure
from core.tests.test_manuscripts import payload, save
from core.tests.test_materials import context as material_context
from core.tests.test_materials import path
from core.word_export import render_word
from worker.tasks import execute_job

context = material_context
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def draft(context):
    body = payload()
    body["blocks"] += [
        {"id": str(uuid4()), "heading_level": 0, "text": "自制图题"},
        {"id": str(uuid4()), "heading_level": 0, "text": "自制表题"},
    ]
    assert save(context, body).status_code == 200
    assert save_disclosure(context, disclosure_body(context, verified=True)).status_code == 201
    template, _ = register_template(
        {
            "code": DEFAULT_CODE,
            "name": DEFAULT_NAME,
            "layout": DEFAULT_LAYOUT,
            "source_label": DEFAULT_SOURCE,
            "rights_note": DEFAULT_RIGHTS,
        },
        context[2],
    )
    return body, {
        "manuscript_version": 1,
        "disclosure_version": 1,
        "template_version_id": str(template.pk),
        "title": "自制导出样例",
        "author": "测试作者",
        "captions": [
            {"block_id": body["blocks"][2]["id"], "kind": "figure"},
            {"block_id": body["blocks"][3]["id"], "kind": "table"},
        ],
    }


def preview(context, selection):
    return context[0].post(path(context[1], "exports/preview/"), selection, format="json")


def create(context, selection):
    response = preview(context, selection)
    assert response.status_code == 200, response.data
    data = {
        **selection,
        "preview_token": response.data["preview_token"],
        "confirmed": True,
        "request_key": str(uuid4()),
    }
    with patch("core.export_views.dispatch"):
        saved = context[0].post(path(context[1], "exports/"), data, format="json")
    assert saved.status_code == 201, saved.data
    return ExportSnapshot.objects.get(pk=saved.data["id"]), data


def download(context, snapshot):
    return context[0].get(path(context[1], f"exports/{snapshot.pk}/download/"))


def test_snapshot_keeps_old_body_disclosure_template_and_idempotency(context, draft):
    original, selection = draft
    snapshot, data = create(context, selection)
    original.update(version=1, request_key="next")
    original["blocks"][1]["text"] = "导出后改写的新稿"
    assert save(context, original).status_code == 200
    assert (
        save_disclosure(
            context, disclosure_body(context, text="新的披露", verified=True)
        ).status_code
        == 201
    )
    with patch("core.export_views.dispatch"):
        repeat = context[0].post(path(context[1], "exports/"), data, format="json")
    assert repeat.status_code == 200 and repeat.data["id"] == str(snapshot.pk)
    execute_job(str(snapshot.job_id))
    snapshot.job.refresh_from_db()
    assert snapshot.job.status == "succeeded", snapshot.job.error_code
    response = download(context, snapshot)
    assert response.status_code == 200
    raw = b"".join(response.streaming_content)
    document = Document(io.BytesIO(raw))
    texts = [p.text for p in document.paragraphs]
    assert "  作者原稿\n保留空白。  " in texts
    assert "导出后改写的新稿" not in texts and "新的披露" not in texts
    assert "图 1 自制图题" in texts and "表 1 自制表题" in texts
    assert document.sections[1].header.paragraphs[0].text == selection["title"]
    assert len(document.sections) == 2
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        xml = archive.read("word/document.xml").decode()
        assert "TOC " in xml and "SEQ Figure" in xml and "SEQ Table" in xml
        assert 'w:pgNumType w:start="1"' in xml
    assert raw == render_word(snapshot.content, snapshot.created_at)
    assert ExportDownload.objects.filter(file__snapshot=snapshot).count() == 1
    detail = context[0].get(path(context[1], f"exports/{snapshot.pk}/")).data
    assert detail["downloads"][0]["file_id"] == detail["file"]["id"]
    assert detail["content"]["manuscript_version"] == 1


def test_failed_storage_retry_and_late_generation_cannot_publish(context, draft):
    snapshot, _ = create(context, draft[1])
    with patch("core.export_jobs.s3_client", side_effect=OSError):
        execute_job(str(snapshot.job_id))
    snapshot.job.refresh_from_db()
    assert snapshot.job.retryable and snapshot.job.error_code == "export_storage"
    first = snapshot.files.get(generation=1)
    with patch("core.job_views.dispatch"):
        retry = context[0].post(
            path(context[1], f"jobs/{snapshot.job_id}/retry/"), {"generation": 1}, format="json"
        )
    assert retry.status_code == 200
    second = claim(snapshot.job_id)
    assert not publish_export(first.pk, 1, "0" * 64, 100)
    execute_export(second)
    snapshot.job.refresh_from_db()
    assert snapshot.job.status == "succeeded"
    assert snapshot.files.get(generation=2).object_key != first.object_key
    assert download(context, snapshot).status_code == 200


def test_preview_conflict_confirmation_and_immutable_records(context, draft):
    original, selection = draft
    snapshot, data = create(context, selection)
    assert (
        context[0]
        .post(path(context[1], "exports/"), {**data, "title": "另一标题"}, format="json")
        .status_code
        == 409
    )
    assert (
        context[0]
        .post(path(context[1], "exports/"), {**data, "confirmed": False}, format="json")
        .status_code
        == 400
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        ExportSnapshot.objects.filter(pk=snapshot.pk).update(content={})
    with pytest.raises(IntegrityError), transaction.atomic():
        ExportTemplateVersion.objects.filter(pk=snapshot.template_version_id).update(
            name="覆盖模板"
        )
    original.update(version=1, request_key="new")
    original["blocks"][1]["text"] = "已改稿"
    assert save(context, original).status_code == 200
    assert preview(context, selection).status_code == 409


def test_download_corruption_not_audited_and_revocation(context, draft):
    snapshot, _ = create(context, draft[1])
    execute_job(str(snapshot.job_id))
    artifact = snapshot.files.get(published_at__isnull=False)
    with closing(s3_client()) as storage:
        storage.put_object(Bucket=artifact.bucket, Key=artifact.object_key, Body=b"corrupt")
    assert download(context, snapshot).status_code == 503
    assert not ExportDownload.objects.exists()
    user = context[2]
    user.is_active = False
    user.save()
    assert download(context, snapshot).status_code == 403


@pytest.fixture
def cited(context, draft):
    from core.ai_jobs import sources_snapshot
    from core.library import default_bibliography
    from core.models import ManuscriptCitation
    from core.tests.test_materials import intent, upload
    from core.tests.test_parse_jobs import create as parse

    version = intent(context)
    with patch("core.parse_views.dispatch"):
        assert upload(context, version).status_code == 200
        run = parse(context, version)
        execute_job(str(run.job_id))
    chunk = run.chunks.first()
    current = context[0].get(path(context[1], "manuscript/")).data
    source = sources_snapshot(context[1].pk, [str(version.pk)])[0]
    ManuscriptCitation.objects.create(
        block_version_id=current["blocks"][1]["version_id"],
        chunk=chunk,
        snapshot=source,
        fingerprint="a" * 64,
        created_by=context[2],
    )
    metadata = {
        **default_bibliography(version),
        "title": "冻结的参考文献",
        "authors": ["自制作者"],
        "year": "2026",
    }
    response = context[0].put(
        path(context[1], f"files/{version.pk}/bibliography/"),
        {"version": 0, "snapshot": metadata},
        format="json",
    )
    assert response.status_code == 200, response.data
    return version, metadata


def test_citations_copy_bibliography_and_withdrawal_blocks_old_export(context, draft, cited):
    version, metadata = cited
    snapshot, _ = create(context, draft[1])
    references = snapshot.content["references"]
    assert references[0]["number"] == 1 and references[0]["bibliography_number"] == 1
    response = context[0].put(
        path(context[1], f"files/{version.pk}/bibliography/"),
        {"version": 1, "snapshot": {**metadata, "title": "新题录"}},
        format="json",
    )
    assert response.status_code == 200
    execute_job(str(snapshot.job_id))
    response = download(context, snapshot)
    assert response.status_code == 200
    document = Document(io.BytesIO(b"".join(response.streaming_content)))
    assert any("冻结的参考文献" in p.text for p in document.paragraphs)
    assert not any("新题录" in p.text for p in document.paragraphs)
    assert 'w:anchor="paper_reference_1"' in document.element.xml
    version.material.access_state = "withdrawn"
    version.material.state_version += 1
    version.material.save()
    assert download(context, snapshot).status_code == 409
    detail = context[0].get(path(context[1], f"exports/{snapshot.pk}/")).data
    assert detail["content"] is None and not detail["downloadable"]
    assert preview(context, draft[1]).status_code == 409
    version.material.access_state = "active"
    version.material.state_version += 1
    version.material.save()
    assert download(context, snapshot).status_code == 409
    assert preview(context, draft[1]).status_code == 409


def test_source_change_before_publish_cancels(context, draft, cited):
    snapshot, _ = create(context, draft[1])
    version = cited[0]
    version.usage_state = "withdrawn"
    version.usage_version += 1
    version.save()
    execute_job(str(snapshot.job_id))
    snapshot.job.refresh_from_db()
    assert snapshot.job.status == "cancelled" and snapshot.job.error_code == "export_source_changed"
    assert not snapshot.files.exists()


def test_template_append_version_and_preview_detects_bibliography_change(context, draft, cited):
    old = ExportTemplateVersion.objects.get(pk=draft[1]["template_version_id"])
    value = {
        "code": old.code,
        "name": old.name,
        "layout": {**old.layout, "body_size_pt": 13},
        "source_label": old.source_label,
        "rights_note": old.rights_note,
    }
    new, created = register_template(value, context[2])
    assert created and new.number == old.number + 1
    assert register_template(value, context[2])[0].pk == new.pk
    before = preview(context, draft[1])
    version, metadata = cited
    assert (
        context[0]
        .put(
            path(context[1], f"files/{version.pk}/bibliography/"),
            {"version": 1, "snapshot": {**metadata, "year": "2025"}},
            format="json",
        )
        .status_code
        == 200
    )
    data = {
        **draft[1],
        "preview_token": before.data["preview_token"],
        "confirmed": True,
        "request_key": str(uuid4()),
    }
    assert context[0].post(path(context[1], "exports/"), data, format="json").status_code == 409
    assert not ExportSnapshot.objects.exists()


def test_policy_change_before_publish_cancels(context, draft):
    from core.models import ProjectPolicy

    snapshot, _ = create(context, draft[1])
    ProjectPolicy.objects.create(project=context[1], version=2, created_by=context[2])
    execute_job(str(snapshot.job_id))
    snapshot.job.refresh_from_db()
    assert snapshot.job.status == "cancelled"
    assert snapshot.job.error_code == "authorization_changed"
    assert not snapshot.files.exists()


def test_project_scope_and_reviewer_cannot_create(context, draft):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient

    from core.models import Project, ProjectMember

    snapshot, _ = create(context, draft[1])
    other = Project.objects.create(owner=context[2], name="另一自制项目")
    assert context[0].get(path(other, f"exports/{snapshot.pk}/")).status_code == 404
    with pytest.raises(IntegrityError), transaction.atomic():
        type(snapshot.job).objects.filter(pk=snapshot.job_id).update(project=other)
    reviewer = get_user_model().objects.create_user(username="export-reviewer")
    ProjectMember.objects.create(project=context[1], user=reviewer, role="reviewer")
    client = APIClient()
    client.force_authenticate(reviewer)
    assert (
        client.post(path(context[1], "exports/preview/"), draft[1], format="json").status_code
        == 403
    )
    assert client.get(path(context[1], f"exports/{snapshot.pk}/")).status_code == 200
    ProjectMember.objects.filter(project=context[1], user=reviewer).delete()
    assert client.get(path(context[1], f"exports/{snapshot.pk}/")).status_code == 404
