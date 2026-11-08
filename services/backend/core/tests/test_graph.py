"""真实 PostgreSQL 和 Neo4j，所有图节点使用本用例创建的随机项目 ID。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from django.test import override_settings
from rest_framework.test import APIClient

from core.graph.errors import GraphUnavailable
from core.graph.service import (
    apply_snapshot,
    driver,
    graph_paths,
    purge_projection,
    recover_events,
    sync_project,
)
from core.graph.snapshot import project_snapshot
from core.models import (
    EvidenceLink,
    EvidenceLinkRevision,
    GraphEvent,
    GraphState,
    GraphTombstone,
    Job,
    ManuscriptCitation,
    Material,
    Project,
    ProjectMember,
    ReviewFinding,
    ReviewRecord,
)
from core.tests.test_library import context as library_context
from core.tests.test_library import source as library_source
from core.tests.test_manuscripts import payload, save
from core.tests.test_materials import path

context = library_context
source = library_source
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture(autouse=True)
def clean_graph(context):
    project_id = context[1].pk
    try:
        yield
    finally:
        purge_projection(project_id)


@pytest.fixture
def manuscript(context):
    data = payload()
    data["blocks"][1]["text"] = "本次实验记录中，提高温度后反应速率增加。"
    response = save(context, data)
    assert response.status_code == 200
    return response.data


def body(manuscript, source, **changes):
    chunk = source[1].chunks.order_by("ordinal").first()
    return {
        "request_key": str(uuid4()),
        "manuscript_version": manuscript["version"],
        "block_id": manuscript["blocks"][1]["id"],
        "chunk_id": str(chunk.pk),
        "claim": "提高温度后反应速率增加。",
        "claim_occurrence": 1,
        "evidence_quote": "提高温度后反应速率增加。",
        "evidence_occurrence": 1,
        "kind": "supports",
        "note": "作者核对自制记录，仅限本次条件。",
        "confirmed": True,
        **changes,
    }


def create(context, manuscript, source, **changes):
    response = context[0].post(
        path(context[1], "evidence-links/"),
        body(manuscript, source, **changes),
        format="json",
    )
    assert response.status_code in [200, 201], response.data
    return response.data


def query(context, **params):
    return context[0].get(path(context[1], "graph/paths/"), params).data


def decision(link, **changes):
    return {
        "request_key": str(uuid4()),
        "version": link["current"]["number"],
        "state": "withdrawn",
        "kind": "supports",
        "note": "作者撤回该支持关系",
        "confirmed": False,
        **changes,
    }


def test_author_path_fixed_records_and_reverse_query(context, manuscript, source):
    client, project, _ = context
    link = create(context, manuscript, source)
    state = GraphState.objects.get(project=project)
    assert state.revision > 0 and state.applied_revision == 0
    assert GraphEvent.objects.filter(project=project, processed_at=None).exists()
    before = query(context)
    assert before["status"] == "missing" and before["count"] is None
    assert sync_project(project.pk)
    result = query(context, block_id=manuscript["blocks"][1]["id"])
    assert result["status"] == "synced" and result["count"] == 1
    item = result["results"][0]
    assert item["origin"] == "author" and item["state"] == "confirmed"
    assert item["claim"] == item["evidence_quote"] == "提高温度后反应速率增加。"
    assert item["location"]["manuscript_version"] == 1
    assert item["location"]["block_version_id"] == manuscript["blocks"][1]["version_id"]
    assert item["source_version_id"] == str(source[0].pk) and item["parse_id"] == str(source[1].pk)
    assert client.get(path(project, f"chunks/{item['chunk_id']}/")).status_code == 200
    reverse = query(context, material_id=source[0].material_id)
    assert reverse["results"][0]["id"] == f"author:{link['id']}"
    assert query(context, block_id=manuscript["blocks"][0]["id"])["count"] == 0


def test_outbox_atomic_rollback_and_request_idempotency(context, manuscript, source):
    client, project, _ = context
    before = GraphState.objects.get(project=project).revision
    with pytest.raises(RuntimeError), transaction.atomic():
        create(context, manuscript, source)
        raise RuntimeError("模拟业务事务回滚")
    assert not EvidenceLink.objects.exists()
    assert GraphState.objects.get(project=project).revision == before
    data = body(manuscript, source)
    for _ in range(2):
        assert client.post(path(project, "evidence-links/"), data, format="json").status_code in [
            200,
            201,
        ]
    assert EvidenceLink.objects.count() == EvidenceLinkRevision.objects.count() == 1
    changed = {**data, "kind": "context"}
    assert client.post(path(project, "evidence-links/"), changed, format="json").status_code == 409
    assert (
        client.post(
            path(project, "evidence-links/"),
            body(manuscript, source, claim="模型编造结论"),
            format="json",
        ).status_code
        == 400
    )


def test_old_events_cannot_restore_withdrawn_link(context, manuscript, source):
    client, project, _ = context
    link = create(context, manuscript, source)
    version = GraphState.objects.get(project=project).revision
    old = project_snapshot(project.pk, version)
    assert sync_project(project.pk)
    assert apply_snapshot(old) == version
    assert graph_paths(project.pk)[2] == 1
    payload = decision(link)
    endpoint = path(project, f"evidence-links/{link['id']}/")
    assert client.post(endpoint, payload, format="json").status_code == 200
    after = GraphState.objects.get(project=project).revision
    assert client.post(endpoint, payload, format="json").status_code == 200
    assert GraphState.objects.get(project=project).revision == after
    assert query(context)["status"] == "pending" and query(context)["count"] is None
    assert sync_project(project.pk)
    assert apply_snapshot(old) == after
    assert query(context)["count"] == 0
    history = client.get(endpoint + "history/").data
    assert [item["state"] for item in history["results"]] == ["withdrawn", "confirmed"]


def test_material_withdrawal_and_restore_require_new_author_check(context, manuscript, source):
    client, project, _ = context
    link = create(context, manuscript, source)
    assert sync_project(project.pk)
    old = project_snapshot(project.pk, GraphState.objects.get(project=project).revision)
    state_path = path(project, f"materials/{source[0].material_id}/state/")
    assert (
        client.patch(
            state_path, {"version": 1, "access_state": "withdrawn"}, format="json"
        ).status_code
        == 200
    )
    assert query(context)["status"] == "pending"
    assert client.get(path(project, f"evidence-links/{link['id']}/")).data["evidence_quote"] == ""
    assert sync_project(project.pk)
    apply_snapshot(old)
    assert query(context)["count"] == 0
    assert (
        client.patch(
            state_path, {"version": 2, "access_state": "active"}, format="json"
        ).status_code
        == 200
    )
    assert sync_project(project.pk)
    assert query(context)["results"][0]["state"] == "needs_review"
    response = client.post(
        path(project, f"evidence-links/{link['id']}/"),
        decision(link, state="confirmed", confirmed=True),
        format="json",
    )
    assert response.status_code == 200
    assert sync_project(project.pk)
    assert query(context)["results"][0]["state"] == "confirmed"


def test_changed_manuscript_keeps_history_without_confirming_new_text(context, manuscript, source):
    client, project, _ = context
    link = create(context, manuscript, source)
    assert sync_project(project.pk)
    blocks = [
        {key: value[key] for key in ["id", "text", "heading_level"]}
        for value in manuscript["blocks"]
    ]
    blocks[1]["text"] = "不同条件仍需要作者核对。"
    assert save(context, payload(1, blocks=blocks)).status_code == 200
    assert query(context)["status"] == "pending"
    assert sync_project(project.pk)
    item = query(context)["results"][0]
    assert item["state"] == "needs_review" and item["location"]["stale"]
    assert item["location"]["manuscript_version"] == 1
    assert (
        client.post(
            path(project, f"evidence-links/{link['id']}/"),
            decision(link, state="confirmed", confirmed=True),
            format="json",
        ).status_code
        == 409
    )


def test_model_diagnosis_and_manuscript_citation_not_author_support(context, manuscript, source):
    _, project, user = context
    author = create(context, manuscript, source)
    link = EvidenceLink.objects.get(pk=author["id"])
    chunk = source[1].chunks.order_by("ordinal").first()
    job = Job.objects.create(
        project=project,
        created_by=user,
        policy_version=1,
        kind="ai",
        ai_action="review",
        status="succeeded",
        idempotency_key=str(uuid4()),
        input_snapshot={},
    )
    review = ReviewRecord.objects.create(
        job=job, manuscript_revision=link.manuscript_revision, summary="自制诊断"
    )
    finding = ReviewFinding.objects.create(
        review=review,
        block_version=link.block_version,
        category="overclaim",
        status="confirmed",
        model_output={
            "quote": link.claim,
            "support": "insufficient",
            "citations": [
                {"chunk_id": str(chunk.pk), "quote": link.evidence_quote, "state_version": 1}
            ],
        },
    )
    ManuscriptCitation.objects.create(
        block_version=link.block_version,
        chunk=chunk,
        created_by=user,
        snapshot={"quote": link.evidence_quote, "state_version": 1},
        fingerprint="a" * 64,
    )
    assert sync_project(project.pk)
    result = query(context)
    assert result["count"] == 3
    by_origin = {row["origin"]: row for row in result["results"]}
    assert by_origin["model"]["state"] == "candidate"
    assert by_origin["model"]["finding_status"] == "confirmed"
    assert by_origin["model"]["model_support"] == "insufficient"
    assert by_origin["citation"]["kind"] == "cites"
    assert by_origin["author"]["state"] == "confirmed"
    finding.status = "ignored"
    finding.save(update_fields=["status"])
    assert query(context)["status"] == "pending"
    assert sync_project(project.pk)
    assert query(context)["count"] == 2


def test_unavailable_retry_and_rebuild_after_projection_loss(context, manuscript, source):
    client, project, _ = context
    create(context, manuscript, source)
    with patch(
        "core.graph.service.apply_snapshot", side_effect=ConnectionError("不要记录私密端点")
    ):
        assert sync_project(project.pk) is False
    state = GraphState.objects.get(project=project)
    assert state.last_error == "ConnectionError"
    assert GraphEvent.objects.filter(
        project=project, error_code="ConnectionError", attempts=1
    ).exists()
    with patch("core.graph.views.graph_paths", side_effect=ConnectionError):
        unavailable = query(context)
    assert unavailable["status"] == "unavailable" and unavailable["count"] is None
    assert sync_project(project.pk)
    purge_projection(project.pk)
    assert query(context)["status"] == "missing"
    state.refresh_from_db()
    data = {"request_key": str(uuid4()), "revision": state.revision}
    with patch("core.graph.views.dispatch"):
        for status in [202, 200]:
            assert (
                client.post(path(project, "graph/rebuild/"), data, format="json").status_code
                == status
            )
    assert sync_project(project.pk)
    assert query(context)["count"] == 1


def test_database_scope_immutable_quotes_and_revoked_access(context, manuscript, source):
    client, project, owner = context
    saved = create(context, manuscript, source)
    link = EvidenceLink.objects.get(pk=saved["id"])
    with pytest.raises(IntegrityError), transaction.atomic():
        EvidenceLink.objects.filter(pk=link.pk).update(claim="改写历史")
    with pytest.raises(IntegrityError), transaction.atomic():
        EvidenceLinkRevision.objects.filter(link=link).update(kind="context")
    other = Project.objects.create(owner=owner, name="仅用于跨项目约束")
    try:
        with pytest.raises(IntegrityError), transaction.atomic():
            link.pk = uuid4()
            link.project = other
            link.request_key = str(uuid4())
            link.save(force_insert=True)
    finally:
        other.delete()
    reviewer = get_user_model().objects.create_user(username="graph-reviewer")
    ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
    client.force_authenticate(reviewer)
    assert (
        client.post(
            path(project, "evidence-links/"), body(manuscript, source), format="json"
        ).status_code
        == 403
    )
    ProjectMember.objects.filter(project=project, user=reviewer).delete()
    with patch("core.graph.views.graph_paths") as graph:
        assert client.get(path(project, "graph/paths/")).status_code == 404
        graph.assert_not_called()


def test_concurrent_duplicate_decisions_and_projection_order(context, manuscript, source):
    _, project, user = context
    saved = create(context, manuscript, source)
    old = project_snapshot(project.pk, GraphState.objects.get(project=project).revision)
    payload = decision(saved)
    barrier = Barrier(2)

    def submit():
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=user.pk))
            barrier.wait()
            return client.post(
                path(project, f"evidence-links/{saved['id']}/"), payload, format="json"
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: submit(), range(2))) == [200, 200]
    latest = project_snapshot(project.pk, GraphState.objects.get(project=project).revision)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(apply_snapshot, [latest, old]))
    assert graph_paths(project.pk)[0] == latest["revision"]
    assert graph_paths(project.pk)[2] == 0
    assert EvidenceLinkRevision.objects.count() == 2
    with driver() as graph, graph.session() as session:
        assert (
            session.run(
                "MATCH (n:PaperNode {project:$project}) RETURN count(n) AS n",
                project=str(project.pk),
            ).single()["n"]
            == 0
        )


def test_raw_material_update_also_writes_event_in_same_transaction(context, manuscript, source):
    _, project, _ = context
    create(context, manuscript, source)
    assert sync_project(project.pk)
    old = GraphState.objects.get(project=project).revision
    Material.objects.filter(pk=source[0].material_id).update(
        access_state="withdrawn", state_version=2
    )
    assert GraphState.objects.get(project=project).revision == old + 1
    assert query(context)["status"] == "pending"
    assert sync_project(project.pk)
    assert query(context)["count"] == 0


def test_graph_commit_before_receipt_failure_can_be_replayed(context, manuscript, source):
    _, project, _ = context
    create(context, manuscript, source)
    revision = GraphState.objects.get(project=project).revision
    with patch.object(GraphState, "save", side_effect=RuntimeError("模拟回执写入前中断")):
        with pytest.raises(RuntimeError):
            sync_project(project.pk)
    assert GraphState.objects.get(project=project).applied_revision == 0
    assert GraphEvent.objects.filter(project=project, processed_at=None).exists()
    assert graph_paths(project.pk)[0] == revision
    assert sync_project(project.pk)
    assert not GraphEvent.objects.filter(project=project, processed_at=None).exists()
    assert query(context)["count"] == 1


def test_new_parse_does_not_reconfirm_old_evidence(context, manuscript, source):
    from core.tests.test_parse_jobs import create as parse
    from worker.tasks import execute_job

    client, project, _ = context
    link = create(context, manuscript, source)
    assert sync_project(project.pk)
    with patch("core.materials.parse_views.dispatch"):
        run = parse(context, source[0], key=str(uuid4()))
    execute_job(str(run.job_id))
    assert sync_project(project.pk)
    assert query(context)["results"][0]["state"] == "needs_review"
    response = client.post(
        path(project, f"evidence-links/{link['id']}/"),
        decision(link, state="confirmed", confirmed=True),
        format="json",
    )
    assert response.status_code == 409


def test_graph_cannot_supply_foreign_or_fabricated_business_records(context, manuscript, source):
    link = create(context, manuscript, source)
    assert sync_project(context[1].pk)
    revision = GraphState.objects.get(project=context[1]).revision
    with patch(
        "core.graph.views.graph_paths", return_value=(revision, [f"author:{uuid4()}"], 1)
    ):
        result = query(context)
    assert (
        result["status"] == "inconsistent" and result["count"] is None and result["results"] == []
    )
    with patch(
        "core.graph.views.graph_paths", return_value=(revision, [f"author:{link['id']}"], 1)
    ):
        result = query(context, block_id=manuscript["blocks"][0]["id"])
    assert result["status"] == "inconsistent" and result["results"] == []


def test_real_disconnected_graph_is_not_empty_result(context, manuscript, source):
    create(context, manuscript, source)
    with override_settings(NEO4J_URI="bolt://127.0.0.1:1"):
        result = query(context)
        assert sync_project(context[1].pk) is False
    assert result["status"] == "unavailable" and result["count"] is None
    assert result["error_code"].startswith("query_")
    assert GraphEvent.objects.filter(project=context[1], processed_at=None).exists()
    assert sync_project(context[1].pk)


def test_project_delete_outbox_rollback_and_late_projection(context, manuscript, source):
    client, project, _ = context
    project_id = project.pk
    create(context, manuscript, source)
    old = project_snapshot(project_id, GraphState.objects.get(project=project).revision)
    assert sync_project(project_id)
    with pytest.raises(RuntimeError), transaction.atomic():
        project.delete()
        raise RuntimeError("模拟删除业务事务回滚")
    project.pk = project_id
    assert not GraphTombstone.objects.filter(project_id=project_id).exists()
    assert EvidenceLink.objects.filter(project=project).exists()
    project.delete()
    assert GraphTombstone.objects.filter(project_id=project_id, processed_at=None).exists()
    assert client.get(f"/api/v1/projects/{project_id}/graph/paths/").status_code == 404
    with patch("core.graph.service.delete_projection", side_effect=ConnectionError("模拟连接失败")):
        recover_events()
    assert GraphTombstone.objects.get(project_id=project_id).error_code == "ConnectionError"
    recover_events()
    assert GraphTombstone.objects.get(project_id=project_id).processed_at is not None
    with pytest.raises(GraphUnavailable, match="project_deleted"):
        apply_snapshot(old)
    assert graph_paths(project_id)[2] == 0


def test_rebuild_can_replace_projection_ahead_of_restored_postgres(context, manuscript, source):
    client, project, _ = context
    create(context, manuscript, source)
    current = GraphState.objects.get(project=project).revision
    future = project_snapshot(project.pk, current + 10)
    apply_snapshot(future)
    assert query(context)["status"] == "inconsistent"
    with patch("core.graph.views.dispatch"):
        response = client.post(
            path(project, "graph/rebuild/"),
            {"request_key": str(uuid4()), "revision": current},
            format="json",
        )
    assert response.status_code == 202
    assert response.data["revision"] == current + 11
    assert sync_project(project.pk)
    assert query(context)["status"] == "synced"
    assert apply_snapshot(future) == current + 11
