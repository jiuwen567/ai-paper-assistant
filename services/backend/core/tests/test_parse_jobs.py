from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from core.jobs.service import claim, fail
from core.materials.parse_jobs import publish_parse
from core.materials.parsing import parse_document
from core.models import (
    Job,
    Material,
    MaterialVersion,
    ParseRun,
    Project,
    ProjectMember,
    SourceChunk,
)
from core.tests.parse_samples import CSV_SAMPLE, docx_sample, pdf_sample
from core.tests.test_materials import context as material_context
from core.tests.test_materials import intent, path, upload
from worker.tasks import execute_job

context = material_context

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def no_queue():
    # 此文件直接执行 Worker 入口；独立测试库任务不能送入开发 Worker。
    with (
        patch("core.materials.parse_views.dispatch"),
        patch("core.jobs.views.dispatch"),
    ):
        yield


def create(context, version, key="parse-1"):
    client, project, _ = context
    response = client.post(
        path(project, f"files/{version.pk}/parses/"), {"idempotency_key": key}, format="json"
    )
    assert response.status_code in [200, 201], response.data
    return ParseRun.objects.get(pk=response.data["id"])


@pytest.mark.parametrize(
    "name,data",
    [
        ("sample.pdf", pdf_sample()),
        ("sample.docx", docx_sample()),
        ("sample.csv", CSV_SAMPLE),
        ("sample.txt", b"first\nsecond\nthird"),
    ],
)
def test_real_storage_parse_version_and_location(context, name, data):
    client, project, _ = context
    version = intent(context, data=data, name=name)
    assert upload(context, version, data).status_code == 200
    run = create(context, version)
    assert create(context, version).pk == run.pk
    execute_job(str(run.job_id))
    execute_job(str(run.job_id))
    run.refresh_from_db()
    assert run.job.status == "succeeded" and run.published_at
    assert run.chunks.count() == len(parse_document(data, name).chunks)
    chunks = client.get(path(project, f"parses/{run.pk}/chunks/")).data["results"]
    detail = client.get(path(project, f"chunks/{chunks[-1]['id']}/")).data
    assert detail["source_version"]["id"] == str(version.pk)
    assert detail["parse_run"]["id"] == str(run.pk)
    assert detail["chunk"]["id"] == chunks[-1]["id"]
    assert all(c["id"] in [v["id"] for v in chunks] for c in detail["context"])
    reparse = create(context, version, "parse-2")
    execute_job(str(reparse.job_id))
    assert reparse.number == 2 and run.chunks.count() == len(chunks)
    assert not set(run.chunks.values_list("id", flat=True)) & set(
        reparse.chunks.values_list("id", flat=True)
    )
    preview = client.get(path(project, f"files/{version.pk}/preview/"))
    if name.endswith(".pdf"):
        assert detail["preview_url"].endswith("#page=2")
        assert preview.status_code == 200 and preview["Content-Disposition"].startswith("inline")
        assert preview["X-Frame-Options"] == "SAMEORIGIN"
        assert b"".join(preview.streaming_content) == data
        preview.close()
    else:
        assert preview.status_code == 404 and detail["preview_url"] is None


def test_failed_parse_and_retry_publish_no_partial_or_duplicate_chunks(context):
    client, project, _ = context
    version = intent(context)
    upload(context, version)
    run = create(context, version)
    with patch(
        "core.materials.parse_jobs.s3_client", side_effect=OSError("private address")
    ):
        execute_job(str(run.job_id))
    run.refresh_from_db()
    assert run.job.status == "failed" and run.job.retryable
    assert run.job.error_code == "source_unavailable"
    assert not run.chunks.exists() and run.published_at is None
    assert client.get(path(project, f"parses/{run.pk}/chunks/")).status_code == 404
    for _ in range(2):
        assert (
            client.post(path(project, f"jobs/{run.job_id}/retry/"), {"generation": 1}).status_code
            == 200
        )
    execute_job(str(run.job_id))
    execute_job(str(run.job_id))
    run.refresh_from_db()
    assert run.job.status == "succeeded" and run.job.generation == 2 and run.chunks.count() == 1


def test_publication_rollback_and_stale_generation(context):
    version = intent(context)
    upload(context, version)
    run = create(context, version)
    job = claim(run.job_id)
    result = parse_document(b"self-authored text", "sample.txt")
    with patch(
        "core.materials.parse_jobs.finish", side_effect=RuntimeError("database failed")
    ):
        with pytest.raises(RuntimeError):
            publish_parse(run.pk, job.generation, result)
    run.refresh_from_db()
    assert not run.chunks.exists() and run.published_at is None
    fail(job.pk, job.generation, retryable=True)
    Job.objects.filter(pk=job.pk).update(status="queued")
    second = claim(job.pk)
    assert not publish_parse(run.pk, job.generation, result)
    assert publish_parse(run.pk, second.generation, result)
    assert not publish_parse(run.pk, second.generation, result)
    assert run.chunks.count() == 1


@pytest.mark.parametrize("change", ["revoke", "cancel", "source"])
def test_state_rechecked_before_publication(context, change):
    client, project, _ = context
    author = get_user_model().objects.create_user(username="parse-coauthor")
    member = ProjectMember.objects.create(project=project, user=author, role="author")
    client.force_authenticate(author)
    version = intent(context)
    upload(context, version)
    run = create(context, version)
    job = claim(run.job_id)
    if change == "revoke":
        member.delete()
    elif change == "cancel":
        client.post(path(project, f"jobs/{job.pk}/cancel/"), {"generation": 1})
    else:
        MaterialVersion.objects.filter(pk=version.pk).update(status="failed")
    assert not publish_parse(run.pk, 1, parse_document(b"sample", "sample.txt"))
    run.refresh_from_db()
    assert not run.chunks.exists() and run.published_at is None and run.job.status == "cancelled"


def test_unparseable_scan_has_diagnostic_nonretryable_failure(context):
    version = intent(context, data=pdf_sample(blank=True), name="scan.pdf")
    upload(context, version, pdf_sample(blank=True))
    run = create(context, version)
    execute_job(str(run.job_id))
    run.refresh_from_db()
    assert run.job.status == "failed" and run.job.error_code == "no_text"
    assert not run.job.retryable and not SourceChunk.objects.exists()


def test_scope_roles_and_input_conflict(context):
    client, project, owner = context
    version = intent(context)
    upload(context, version)
    run = create(context, version)
    execute_job(str(run.job_id))
    second = intent(context, request_key="upload-2")
    upload(context, second)
    assert (
        client.post(
            path(project, f"files/{second.pk}/parses/"), {"idempotency_key": "parse-1"}
        ).status_code
        == 409
    )
    other = Project.objects.create(owner=owner, name="另一个项目")
    chunk = run.chunks.get()
    for suffix in [
        f"files/{version.pk}/parses/",
        f"parses/{run.pk}/chunks/",
        f"chunks/{chunk.pk}/",
    ]:
        assert client.get(path(other, suffix)).status_code == 404
    reviewer = get_user_model().objects.create_user(username="parse-reviewer")
    ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
    client.force_authenticate(reviewer)
    assert client.get(path(project, f"chunks/{chunk.pk}/")).status_code == 200
    assert (
        client.post(
            path(project, f"files/{version.pk}/parses/"), {"idempotency_key": "review"}
        ).status_code
        == 403
    )
    ProjectMember.objects.filter(user=reviewer).delete()
    assert client.get(path(project, f"chunks/{chunk.pk}/")).status_code == 404


def test_database_rejects_cross_project_relations_and_parent_moves(context):
    _, project, user = context
    version = intent(context)
    upload(context, version)
    run = create(context, version)
    other = Project.objects.create(owner=user, name="其他项目")
    foreign_material = Material.objects.create(project=other, title="其他材料")
    foreign_job = Job.objects.create(
        project=other, created_by=user, kind="parse", idempotency_key="foreign", policy_version=1
    )
    with pytest.raises(IntegrityError, match="parse_project_scope"), transaction.atomic():
        ParseRun.objects.create(
            source_version=version, number=2, parser_version="test", job=foreign_job
        )
    for model, pk, changes in [
        (Job, run.job_id, {"project": other}),
        (Material, version.material_id, {"project": other}),
        (MaterialVersion, version.pk, {"material": foreign_material}),
    ]:
        with pytest.raises(IntegrityError, match="parse_project_scope"), transaction.atomic():
            model.objects.filter(pk=pk).update(**changes)
    assert ParseRun.objects.count() == 1


def test_concurrent_parse_requests_create_one_job(context):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections
    from rest_framework.test import APIClient

    _, project, user = context
    version = intent(context)
    upload(context, version)
    barrier = Barrier(2)

    def submit(_):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=user.pk))
            barrier.wait(timeout=10)
            return client.post(
                path(project, f"files/{version.pk}/parses/"), {"idempotency_key": "same"}
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, range(2))) == [200, 201]
    assert ParseRun.objects.count() == 1 and Job.objects.count() == 1
