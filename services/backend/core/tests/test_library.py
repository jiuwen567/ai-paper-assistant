from unittest.mock import patch

import pytest

from core.library.service import default_bibliography
from core.models import Bibliography, EmbeddingIndex, EvidenceCard, ProjectPolicy
from core.search.embeddings import configuration
from core.tests.embedding_provider import provider
from core.tests.test_materials import context as material_context
from core.tests.test_materials import intent, path, upload
from core.tests.test_parse_jobs import create
from worker.tasks import execute_job

context = material_context
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def source(context):
    data = "实验记录：提高温度后反应速率增加。\n对照记录：光照保持不变。".encode()
    with patch("core.materials.parse_views.dispatch"):
        version = intent(context, data=data)
        assert upload(context, version, data).status_code == 200
        run = create(context, version)
        execute_job(str(run.job_id))
    return version, run


def test_bibliography_evidence_notes_and_scope(context, source):
    client, project, _ = context
    version, run = source
    url = path(project, f"files/{version.pk}/bibliography/")
    assert client.get(url).data["version"] == 0
    metadata = {**default_bibliography(version), "source_scope": "abstract", "title": "自制摘要"}
    for _ in range(2):
        assert (
            client.put(url, {"version": 0, "snapshot": metadata}, format="json").data["version"]
            == 1
        )
    assert Bibliography.objects.get().revisions.count() == 1
    assert client.get(path(project, "search/?q=自制摘要")).data["results"]
    chunk = run.chunks.order_by("ordinal").first()
    payload = {
        "chunk_id": str(chunk.pk),
        "request_key": "card-1",
        "note": "作者的解释",
        "tags": ["实验", "实验"],
    }
    for _ in range(2):
        created = client.post(path(project, "evidence/"), payload, format="json")
        assert created.status_code in [200, 201], created.data
    card = EvidenceCard.objects.get()
    assert created.data["quote"] == chunk.text and created.data["note"]["text"] == "作者的解释"
    assert created.data["bibliography"]["source_scope"] == "abstract"
    assert created.data["note"]["tags"] == ["实验"]
    update = path(project, f"evidence/{card.pk}/")
    assert (
        client.patch(
            update, {"version": 1, "note": "手机短笔记", "tags": ["复核"]}, format="json"
        ).data["revision"]
        == 2
    )
    assert client.patch(update, {"version": 1, "note": "旧内容"}, format="json").status_code == 409
    assert client.get(path(project, "evidence/?tag=实验")).data["count"] == 0
    assert client.get(path(project, "evidence/?tag=复核")).data["count"] == 1
    metadata["source_scope"] = "full_text"
    assert client.put(url, {"version": 1, "snapshot": metadata}, format="json").status_code == 200
    assert client.get(update).data["bibliography"]["source_scope"] == "abstract"
    assert card.notes.count() == 2


@pytest.fixture(autouse=True)
def embedding_api():
    # 真实 HTTP 适配器与数据库，供应商返回固定向量，不评价模型语义质量。
    with provider() as requests:
        yield requests


def test_embedding_api_pgvector_search_and_withdrawal(context, source):
    client, project, user = context
    version, run = source
    ProjectPolicy.objects.filter(project=project).update(
        verified=True, source="自制规则", source_version="v1", allowed_actions=["reading"]
    )
    with patch("core.search.jobs.dispatch"):
        response = client.post(
            path(project, "indexes/"),
            {"idempotency_key": "index-1", "policy_version": 1},
            format="json",
        )
    assert response.status_code == 201, response.data
    index = EmbeddingIndex.objects.get()
    execute_job(str(index.job_id))
    execute_job(str(index.job_id))
    index.refresh_from_db()
    assert index.job.status == "succeeded", index.job.error_code
    assert index.dimension == 512 and index.segments.count() == 2
    found = client.get(path(project, "search/?mode=semantic&q=升温与反应速率"))
    assert found.status_code == 200, found.data
    assert "提高温度" in found.data["results"][0]["text"]
    assert found.data["results"][0]["source_scope"] == "unknown"
    assert client.get(path(project, "search/?q=温度")).data["results"][0][
        "source_version_id"
    ] == str(version.pk)
    state = path(project, f"materials/{version.material_id}/state/")
    assert (
        client.patch(state, {"version": 1, "access_state": "withdrawn"}, format="json").status_code
        == 200
    )
    assert client.get(path(project, "search/?q=温度")).data["results"] == []
    assert client.get(path(project, "search/?mode=semantic&q=温度")).status_code == 409
    assert (
        client.post(
            path(project, f"files/{version.pk}/parses/"), {"idempotency_key": "withdrawn"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            path(project, "evidence/"),
            {"chunk_id": str(run.chunks.first().pk), "request_key": "withdrawn"},
        ).status_code
        == 404
    )


def index_job(context, key="index-test"):
    client, project, _ = context
    configuration()
    ProjectPolicy.objects.filter(project=project).update(
        verified=True, source="自制规则", source_version="v1", allowed_actions=["reading"]
    )
    with patch("core.search.jobs.dispatch"):
        response = client.post(
            path(project, "indexes/"), {"idempotency_key": key, "policy_version": 1}, format="json"
        )
    assert response.status_code in [200, 201], response.data
    return EmbeddingIndex.objects.get(pk=response.data["id"])


def test_incompatible_model_rebuild_never_mixes_spaces(context, source):
    from django.test import override_settings

    client, project, _ = context
    first = index_job(context)
    execute_job(str(first.job_id))
    with override_settings(EMBEDDING_MODEL="another-api-model", EMBEDDING_DIMENSION=384):
        configuration()
        assert client.get(path(project, "search/?mode=semantic&q=温度")).status_code == 409
        second = index_job(context, "index-en")
        execute_job(str(second.job_id))
        second.refresh_from_db()
        assert second.dimension == 384 and second.job.status == "succeeded"
        result = client.get(path(project, "search/?mode=semantic&q=温度"))
        assert result.status_code == 200 and result.data["index"]["id"] == str(second.pk)
    assert first.segments.count() == second.segments.count() == 2
    assert client.get(path(project, "search/?mode=semantic&q=温度")).data["index"]["id"] == str(
        first.pk
    )


def test_index_transaction_failure_retry_and_stale_generation(context, source):
    client, project, _ = context
    index = index_job(context)
    with patch("core.search.jobs.finish", side_effect=RuntimeError("commit failure")):
        execute_job(str(index.job_id))
    index.refresh_from_db()
    assert index.job.status == "failed" and index.job.retryable and index.published_at is None
    assert not index.segments.exists()
    with patch("core.jobs.views.dispatch"):
        assert (
            client.post(path(project, f"jobs/{index.job_id}/retry/"), {"generation": 1}).status_code
            == 200
        )
    execute_job(str(index.job_id))
    execute_job(str(index.job_id))
    index.refresh_from_db()
    assert (
        index.job.status == "succeeded"
        and index.job.generation == 2
        and index.segments.count() == 2
    )


@pytest.mark.parametrize("change", ["withdraw", "revoke", "cancel"])
def test_index_change_during_encoding_prevents_publication(context, source, change):
    from django.contrib.auth import get_user_model

    from core.models import Material, ProjectMember
    from core.search.embeddings import encode

    client, project, _ = context
    user = get_user_model().objects.create_user(username="index-coauthor")
    member = ProjectMember.objects.create(project=project, user=user, role="author")
    client.force_authenticate(user)
    index = index_job(context)

    def changed(*args, **kwargs):
        vectors = encode(*args, **kwargs)
        if change == "withdraw":
            Material.objects.filter(pk=source[0].material_id).update(
                access_state="withdrawn", state_version=2
            )
        elif change == "revoke":
            member.delete()
        else:
            client.post(path(project, f"jobs/{index.job_id}/cancel/"), {"generation": 1})
        return vectors

    with patch("core.search.jobs.encode", side_effect=changed):
        execute_job(str(index.job_id))
    index.refresh_from_db()
    assert index.job.status == "cancelled" and not index.segments.exists()


def test_search_rechecks_revocation_and_isolates_project(context, source):
    from django.contrib.auth import get_user_model

    from core.models import Project, ProjectMember
    from core.search.embeddings import encode

    client, project, owner = context
    index = index_job(context)
    execute_job(str(index.job_id))
    other = Project.objects.create(owner=owner, name="其他项目")
    assert client.get(path(other, "search/?q=温度")).data["results"] == []
    reviewer = get_user_model().objects.create_user(username="search-reviewer")
    member = ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
    client.force_authenticate(reviewer)
    assert client.get(path(project, "search/?mode=semantic&q=温度")).status_code == 200
    assert (
        client.post(
            path(project, "indexes/"), {"idempotency_key": "no", "policy_version": 1}
        ).status_code
        == 403
    )

    def revoke(*args, **kwargs):
        vector = encode(*args, **kwargs)
        member.delete()
        return vector

    with patch("core.search.views.encode", side_effect=revoke):
        assert client.get(path(project, "search/?mode=semantic&q=温度")).status_code == 404


def test_database_enforces_evidence_source_vector_dimension_and_project(context, source):
    from django.db import IntegrityError, transaction

    from core.models import BibliographyRevision, ChunkEmbedding, Job, Project, SourceChunk

    _, project, user = context
    version, run = source
    other_version = intent(context, request_key="other-version")
    bibliography = Bibliography.objects.create(source_version=other_version, revision=1)
    revision = BibliographyRevision.objects.create(
        bibliography=bibliography, number=1, snapshot={}, created_by=user
    )
    chunk = run.chunks.first()
    with pytest.raises(IntegrityError, match="evidence_source_scope"), transaction.atomic():
        EvidenceCard.objects.create(
            chunk=chunk,
            bibliography_revision=revision,
            created_by=user,
            request_key="invalid",
            request_snapshot={},
        )
    job = Job.objects.create(
        project=project,
        created_by=user,
        kind="index",
        idempotency_key="test-vector",
        policy_version=1,
    )
    index = EmbeddingIndex.objects.create(
        job=job, model_name="test", dimension=2, artifact_digest="test", pipeline_version="test"
    )
    with pytest.raises(IntegrityError, match="embedding_space_scope"), transaction.atomic():
        ChunkEmbedding.objects.create(
            index=index, chunk=chunk, start=0, end=1, text_sha256="test", vector=[1, 0, 0]
        )
    ChunkEmbedding.objects.create(
        index=index, chunk=chunk, start=0, end=1, text_sha256="test", vector=[1, 0]
    )
    other = Project.objects.create(owner=user, name="其他项目")
    foreign_job = Job.objects.create(
        project=other, created_by=user, kind="index", idempotency_key="foreign", policy_version=1
    )
    for changes in [{"dimension": 3}, {"job": foreign_job}]:
        with pytest.raises(IntegrityError, match="embedding_space_scope"), transaction.atomic():
            EmbeddingIndex.objects.filter(pk=index.pk).update(**changes)
    with pytest.raises(IntegrityError, match="evidence_source_scope"), transaction.atomic():
        valid_bib = Bibliography.objects.create(source_version=version, revision=1)
        valid_rev = BibliographyRevision.objects.create(
            bibliography=valid_bib, number=1, snapshot={}, created_by=user
        )
        EvidenceCard.objects.create(
            chunk=chunk,
            bibliography_revision=valid_rev,
            created_by=user,
            request_key="valid",
            request_snapshot={},
        )
        BibliographyRevision.objects.filter(pk=valid_rev.pk).update(
            bibliography=bibliography, number=2
        )
    assert SourceChunk.objects.filter(pk=chunk.pk).exists()


def test_withdraw_then_restore_does_not_revive_old_parse(context, source):
    client, project, _ = context
    version, _ = source
    with patch("core.materials.parse_views.dispatch"):
        run = create(context, version, "pending-before-withdrawal")
    state = path(project, f"materials/{version.material_id}/state/")
    assert client.patch(state, {"version": 1, "access_state": "withdrawn"}).status_code == 200
    assert client.patch(state, {"version": 2, "access_state": "active"}).status_code == 200
    execute_job(str(run.job_id))
    run.refresh_from_db()
    assert run.job.status == "cancelled" and not run.chunks.exists()


def test_mini_token_notes_are_visible_to_web(context, source):
    from datetime import timedelta

    from django.test import override_settings
    from django.utils import timezone
    from rest_framework.test import APIClient

    from core.accounts.wechat import digest
    from core.models import WechatIdentity, WechatSession

    web, project, user = context
    chunk = source[1].chunks.first()
    created = web.post(
        path(project, "evidence/"),
        {"chunk_id": str(chunk.pk), "request_key": "mini-note", "note": "Web 初始笔记"},
        format="json",
    )
    assert created.status_code == 201
    url = path(project, f"evidence/{created.data['id']}/")
    with override_settings(WECHAT_APP_ID="self-authored-mini"):
        identity = WechatIdentity.objects.create(
            app_id="self-authored-mini", open_id="self-authored", user=user
        )
        WechatSession.objects.create(
            identity=identity,
            user=user,
            token_hash=digest("self-authored-token"),
            expires_at=timezone.now() + timedelta(hours=1),
        )
        mini = APIClient()
        mini.credentials(HTTP_AUTHORIZATION="Bearer self-authored-token")
        assert mini.get(url).data["quote"] == chunk.text
        assert (
            mini.put(
                url, {"version": 1, "note": "手机补充短笔记", "tags": ["复核"]}, format="json"
            ).status_code
            == 200
        )
        assert web.get(url).data["note"]["text"] == "手机补充短笔记"


def test_api_partial_batch_failure_retry_does_not_publish_partial_index(context, source):
    # 超过一批，第一批已调用成功也不得在第二批失败时发布。
    from core.tests.embedding_provider import response_for

    source[1].chunks.filter(ordinal=source[1].chunks.first().ordinal).update(
        text="自制温度记录。" * 400
    )
    calls = []

    def respond(payload):
        calls.append(payload)
        return (429, {}, {}) if len(calls) == 2 else (200, response_for(payload), {})

    with provider(respond):
        index = index_job(context)
        execute_job(str(index.job_id))
        index.refresh_from_db()
        assert index.job.status == "failed" and index.job.retryable
        assert index.job.error_code == "embedding_http_429"
        assert not index.segments.exists() and index.published_at is None
        with patch("core.jobs.views.dispatch"):
            response = context[0].post(
                path(context[1], f"jobs/{index.job_id}/retry/"), {"generation": 1}
            )
        assert response.status_code == 200
        execute_job(str(index.job_id))
        index.refresh_from_db()
        assert index.job.status == "succeeded" and index.segments.count() > 8
        count = index.segments.count()
        execute_job(str(index.job_id))
        assert index.segments.count() == count


def test_old_local_index_job_is_cancelled_without_api_call(context, source, embedding_api):
    from core.models import Job

    index = index_job(context)
    snapshot = dict(index.job.input_snapshot)
    snapshot["embedding"] = {
        "model_name": "BAAI/bge-small-zh-v1.5",
        "dimension": 512,
        "artifact_digest": "old-local-weights",
        "pipeline_version": "char256-v1/fastembed-old",
    }
    Job.objects.filter(pk=index.job_id).update(input_snapshot=snapshot)
    execute_job(str(index.job_id))
    index.refresh_from_db()
    assert index.job.status == "cancelled" and not index.segments.exists()
    assert not embedding_api
