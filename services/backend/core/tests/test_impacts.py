"""自制材料更正：登记依赖、候选与作者处理均不改写研究结论。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from django.test import override_settings
from rest_framework.test import APIClient

from core.ai.runtime import AIRun
from core.ai.state import valid_locked
from core.common.errors import ParseFailure
from core.jobs.service import claim, lock_job
from core.library.service import active_chunks, searchable_chunks
from core.models import (
    GraphState,
    ImpactDecision,
    ImpactItem,
    ImpactRun,
    Job,
    Manuscript,
    MaterialChange,
    Project,
    ProjectMember,
    ProjectPolicy,
)
from core.tests.test_ai_jobs import provider
from core.tests.test_expressions import create as expression_job
from core.tests.test_expressions import decide
from core.tests.test_expressions import run as expression_run
from core.tests.test_feedback import create_feedback, manual_task
from core.tests.test_graph import create as create_link
from core.tests.test_library import context as library_context
from core.tests.test_library import source as library_source
from core.tests.test_manuscripts import payload, save
from core.tests.test_materials import intent, path, upload
from core.tests.test_parse_jobs import create as parse_create
from worker.tasks import execute_job

context = library_context
source = library_source
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def manuscript(context):
    data = payload(
        blocks=[
            {"id": str(uuid4()), "heading_level": 0, "text": text}
            for text in [
                "提高温度后反应速率增加。",
                "本研究对样本进行了观察。",
                "提高温度后反应速率增加，因此需要复核测量条件。",
                "无关实验的光照保持不变。",
            ]
        ]
    )
    result = save(context, data)
    assert result.status_code == 200
    return result.data


def new_source(context, source=None):
    data = "更正记录：提高温度后反应速率未见增加。\n单位核对后保留原始数据。".encode()
    changes = (
        {"material_id": str(source[0].material_id), "base_revision": source[0].number}
        if source
        else {}
    )
    with patch("core.materials.parse_views.dispatch"):
        version = intent(context, data=data, request_key=str(uuid4()), **changes)
        assert upload(context, version, data).status_code == 200
        run = parse_create(context, version, key=str(uuid4()))
        execute_job(str(run.job_id))
    return version, run


def change_body(source, replacement=None, **changes):
    source[0].refresh_from_db()
    return {
        "request_key": str(uuid4()),
        "source_version_id": str(source[0].pk),
        "replacement_id": str(replacement[0].pk) if replacement else None,
        "kind": "correction" if replacement else "withdrawal",
        "note": "单位更正，需要作者复核温度与速率的论述。",
        "confirmed": True,
        "state_version": source[0].material.state_version,
        "usage_version": source[0].usage_version,
        "replacement_usage_version": replacement[0].usage_version if replacement else None,
        **changes,
    }


def change(context, source, replacement=None, **changes):
    data = change_body(source, replacement, **changes)
    response = context[0].post(path(context[1], "material-changes/"), data, format="json")
    assert response.status_code == 201, response.data
    return response.data, data


def scan(context, change):
    response = context[0].post(
        path(context[1], f"material-changes/{change['id']}/runs/"),
        {"request_key": str(uuid4()), "sources_token": change["sources_token"]},
        format="json",
    )
    assert response.status_code == 201, response.data
    result = context[0].get(path(context[1], f"impact-runs/{response.data['id']}/items/")).data
    return response.data, result["results"]


def link_block(context, manuscript, source, index):
    return create_link(
        context,
        manuscript,
        source,
        block_id=manuscript["blocks"][index]["id"],
        claim=manuscript["blocks"][index]["text"],
    )


def handle_body(item, **changes):
    return {
        "request_key": str(uuid4()),
        "version": item["current"]["number"] if item["current"] else 0,
        "facts_token": item["facts_token"],
        "state": "retained",
        "note": "作者核对其他依据后保留原论述，后续继续检查。",
        "confirmed": True,
        **changes,
    }


def test_upload_supplement_and_explicit_correction_states(context, source):
    replacement = new_source(context, source)
    assert searchable_chunks(context[1].pk).filter(run=source[1]).exists()
    supplement, _ = change(context, source, replacement, kind="supplement")
    assert supplement["sources"]["old"]["usage_state"] == "active"
    revision = GraphState.objects.get(project=context[1]).revision
    corrected, data = change(context, source, replacement)
    assert corrected["sources"]["old"]["usage_state"] == "corrected"
    assert not searchable_chunks(context[1].pk).filter(run=source[1]).exists()
    assert active_chunks(context[1].pk).filter(run=source[1]).exists()
    assert searchable_chunks(context[1].pk).filter(run=replacement[1]).exists()
    assert GraphState.objects.get(project=context[1]).revision > revision
    endpoint = path(context[1], "material-changes/")
    assert context[0].post(endpoint, data, format="json").status_code == 200
    assert context[0].post(endpoint, {**data, "note": "不同说明"}, format="json").status_code == 409
    assert (
        context[0].post(endpoint, change_body(source, replacement), format="json").status_code
        == 409
    )
    assert MaterialChange.objects.count() == 2


def test_three_registered_dependencies_other_evidence_and_unrelated_untouched(
    context, source, manuscript
):
    for index in range(3):
        link_block(context, manuscript, source, index)
    alternative = new_source(context)
    other = create_link(
        context,
        manuscript,
        alternative,
        block_id=manuscript["blocks"][0]["id"],
        claim=manuscript["blocks"][0]["text"],
        evidence_quote="更正记录：提高温度后反应速率未见增加。",
        kind="context",
    )
    corrected, _ = change(context, source, new_source(context, source))
    run, items = scan(context, corrected)
    assert run["counts"] == {"registered": 3, "model": 0}
    assert {i["location"]["block_id"] for i in items} == {b["id"] for b in manuscript["blocks"][:3]}
    item = next(i for i in items if i["location"]["block_id"] == manuscript["blocks"][0]["id"])
    assert item["snapshot"]["other_evidence"][0]["record_id"] == other["id"]
    assert all(i["current"] is None and i["needs_review"] for i in items)
    assert context[0].get(path(context[1], "manuscript/")).data["blocks"] == manuscript["blocks"]
    assert Manuscript.objects.get(project=context[1]).current_revision.number == 1


def test_pending_suggestion_task_and_stale_acceptance(context, source, manuscript):
    suggestion = expression_run(context, manuscript, source)
    feedback, _ = create_feedback(context, manuscript, source)
    task, _ = manual_task(context, feedback, manuscript)
    corrected, _ = change(context, source, new_source(context, source))
    _, items = scan(context, corrected)
    assert {i["snapshot"]["kind"] for i in items} == {"suggestion", "task"}
    assert any(i["snapshot"].get("task_id") == task["id"] for i in items)
    assert decide(context, suggestion).status_code == 409
    assert Manuscript.objects.get(project=context[1]).current_revision.number == 1


def test_decision_conflicts_history_recheck_and_author_body_change(context, source, manuscript):
    link_block(context, manuscript, source, 0)
    corrected, _ = change(context, source, new_source(context, source))
    run, items = scan(context, corrected)
    item = items[0]
    endpoint = path(context[1], f"impact-items/{item['id']}/")
    data = handle_body(item)
    response = context[0].post(endpoint, data, format="json")
    assert response.status_code == 200 and not response.data["needs_review"]
    assert context[0].post(endpoint, data, format="json").status_code == 200
    assert ImpactDecision.objects.count() == 1
    assert context[0].post(endpoint, handle_body(item), format="json").status_code == 409
    update = payload(
        version=1,
        blocks=[{k: b[k] for k in ["id", "text", "heading_level"]} for b in manuscript["blocks"]],
    )
    update["blocks"][0]["text"] = "作者根据更正材料重新核对后修订论述。"
    assert save(context, update).status_code == 200
    refreshed = context[0].get(endpoint).data
    assert refreshed["needs_review"] and refreshed["location"]["stale"]
    result = context[0].post(endpoint, handle_body(refreshed, state="handled"), format="json")
    assert result.status_code == 200 and result.data["current"]["number"] == 2
    assert context[0].get(endpoint + "history/").data["count"] == 2
    next_run, next_items = scan(context, corrected)
    assert next_items == []
    assert next_run["comparison"] == {
        "previous_run_id": run["id"],
        "previous_number": 1,
        "remaining": 0,
        "new": 0,
        "no_longer_registered": 1,
    }
    assert context[0].get(path(context[1], f"impact-runs/{run['id']}/items/")).data["count"] == 1


def test_withdrawal_legacy_restore_does_not_reactivate_corrected_version(context, source):
    replacement = new_source(context, source)
    change(context, source, replacement)
    endpoint = path(context[1], f"materials/{source[0].material_id}/state/")
    assert (
        context[0]
        .patch(endpoint, {"version": 1, "access_state": "withdrawn"}, format="json")
        .status_code
        == 200
    )
    assert MaterialChange.objects.filter(kind="withdrawal", scope="material").count() == 2
    assert (
        context[0]
        .patch(endpoint, {"version": 1, "access_state": "withdrawn"}, format="json")
        .status_code
        == 200
    )
    assert MaterialChange.objects.filter(kind="withdrawal").count() == 2
    assert (
        context[0]
        .patch(endpoint, {"version": 2, "access_state": "active"}, format="json")
        .status_code
        == 200
    )
    assert not searchable_chunks(context[1].pk).filter(run=source[1]).exists()
    assert searchable_chunks(context[1].pk).filter(run=replacement[1]).exists()
    withdrawn, _ = change(context, source)
    assert withdrawn["sources"]["old"]["usage_state"] == "withdrawn"
    assert not active_chunks(context[1].pk).filter(run=source[1]).exists()
    assert (
        context[0]
        .post(path(context[1], f"files/{source[0].pk}/parses/"), {"idempotency_key": str(uuid4())})
        .status_code
        == 404
    )


def test_two_concurrent_corrections_have_one_winner(context, source):
    replacement = new_source(context, source)
    body = change_body(source, replacement)
    barrier = Barrier(2)

    def post(key):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(get_user_model().objects.get(pk=context[2].pk))
            barrier.wait(timeout=10)
            return client.post(
                path(context[1], "material-changes/"), {**body, "request_key": key}, format="json"
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(post, ["one", "two"])) == [201, 409]
    assert MaterialChange.objects.count() == 1


def create_model(context, run, manuscript):
    ProjectPolicy.objects.filter(project=context[1]).update(
        verified=True, source="自制规则", source_version="v1", allowed_actions=["review"]
    )
    with patch("core.jobs.service.dispatch"):
        response = context[0].post(
            path(context[1], f"impact-runs/{run['id']}/model/"),
            {
                "idempotency_key": str(uuid4()),
                "policy_version": 1,
                "block_ids": [b["id"] for b in manuscript["blocks"]],
            },
            format="json",
        )
    assert response.status_code == 201, response.data
    return Job.objects.get(pk=response.data["id"])


def output(manuscript):
    return {
        "candidates": [
            {
                "block_version_id": manuscript["blocks"][2]["version_id"],
                "body_quote": manuscript["blocks"][2]["text"],
                "reason": "可能受单位更正影响，请作者核对。",
                "basis": "note",
                "chunk_id": None,
                "change_quote": "单位更正",
            }
        ],
    }


def test_real_pi_candidate_scope_and_no_automatic_confirmation(context, source, manuscript):
    link_block(context, manuscript, source, 0)
    corrected, _ = change(context, source, new_source(context, source))
    run, _ = scan(context, corrected)
    with provider(
        lambda number, _: (
            [("read_impact", {})] if number == 1 else [("submit_impact", output(manuscript))]
        )
    ):
        job = create_model(context, run, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
    assert job.status == "succeeded", job.error_code
    assert job.model_calls.count() == 2
    assert "1 处" in job.output["summary"] and "不代表已确认" in job.output["summary"]
    usage = context[0].get(path(context[1], f"usage/{job.pk}/")).data
    assert len(usage["impact_candidates"]) == 1
    assert usage["input"]["impact_run_id"] == run["id"]
    assert set(usage["input"]["version_ids"]) == {
        corrected["sources"]["old"]["id"],
        corrected["sources"]["new"]["id"],
    }
    summary = context[0].get(path(context[1], "disclosure/")).data["summary"]
    assert summary["impact_candidates"] == 1 and summary["accepted"] == 0
    assert ImpactItem.objects.filter(run_id=run["id"], origin="model").count() == 1
    assert not ImpactDecision.objects.exists()
    assert Manuscript.objects.get(project=context[1]).current_revision.number == 1


def test_model_rejects_unread_fabricated_and_registered_quotes(context, source, manuscript):
    from core.impacts.ai import validate_output

    link_block(context, manuscript, source, 0)
    corrected, _ = change(context, source, new_source(context, source))
    run, _ = scan(context, corrected)
    with override_settings(AI_MODEL="synthetic", AI_BASE_URL="http://127.0.0.1:10000/v1"):
        job = create_model(context, run, manuscript)
    for read, fields in [
        (False, {}),
        (True, {"body_quote": "编造原文"}),
        (True, {"chunk_id": str(uuid4()), "basis": "old"}),
        (True, {"block_version_id": manuscript["blocks"][0]["version_id"]}),
    ]:
        value = output(manuscript)
        value["candidates"][0].update(fields)
        with pytest.raises(ParseFailure):
            validate_output(job, value, read)
    assert not ImpactItem.objects.filter(origin="model").exists()


def test_evidence_side_and_identifier_must_match_without_automatic_conversion(
    context, source, manuscript
):
    from core.impacts.ai import read_impact, validate_output

    corrected, _ = change(context, source, new_source(context, source))
    run, _ = scan(context, corrected)
    with provider(lambda *_: []):
        job = create_model(context, run, manuscript)
        content = read_impact(job)
        references = {
            side: next(c for c in content["sources"] if c["side"] == side)
            for side in ["old", "new"]
        }
        for side in ["old", "new", "note"]:
            valid = output(manuscript)
            if side != "note":
                valid["candidates"][0].update(
                    basis=side,
                    chunk_id=references[side]["chunk_id"],
                    change_quote=references[side]["excerpt"],
                )
            assert validate_output(job, valid, True)["candidates"][0]["basis"] == side
        for side, cid in [
            ("old", None),
            ("new", None),
            ("old", references["new"]["chunk_id"]),
            ("new", references["old"]["chunk_id"]),
            ("note", references["new"]["chunk_id"]),
        ]:
            invalid = output(manuscript)
            invalid["candidates"][0].update(basis=side, chunk_id=cid)
            with pytest.raises(ParseFailure, match="impact_anchor_invalid") as error:
                validate_output(job, invalid, True)
            if side in references:
                assert references[side]["chunk_id"] in error.value.message
        assert not ImpactItem.objects.filter(origin="model").exists()


def test_sdk_new_basis_null_is_rejected_then_repaired_in_original_budget(
    context, source, manuscript
):
    from core.impacts.ai import read_impact

    corrected, _ = change(context, source, new_source(context, source))
    run, _ = scan(context, corrected)
    selected = {}

    def respond(number, _):
        if number == 1:
            return [("read_impact", {})]
        if number == 3:
            assert not ImpactItem.objects.filter(origin="model").exists()
        data = output(manuscript)
        data["candidates"][0].update(
            basis="new",
            chunk_id=None if number == 2 else selected["chunk_id"],
            change_quote=selected["excerpt"],
        )
        return [("submit_impact", data)]

    with provider(respond) as requests:
        job = create_model(context, run, manuscript)
        selected.update(next(c for c in read_impact(job)["sources"] if c["side"] == "new"))
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        assert len(requests) == 3
        item = ImpactItem.objects.get(job=job)
        assert item.snapshot["basis"] == "new" and item.snapshot["chunk_id"] == selected["chunk_id"]
        assert job.ai_events.filter(kind="validation_error").exists()
        assert not ImpactDecision.objects.exists()
        assert Manuscript.objects.get(project=context[1]).current_revision.number == 1


def test_old_impact_prompt_is_cancelled_without_model_request(context, source, manuscript):
    corrected, _ = change(context, source, new_source(context, source))
    run, _ = scan(context, corrected)
    with provider(lambda *_: []) as requests:
        job = create_model(context, run, manuscript)
        job.input_snapshot["model"]["prompt_version"] = "impact-v1"
        job.save(update_fields=["input_snapshot"])
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "cancelled", job.error_code
        assert not requests and not ImpactItem.objects.filter(origin="model").exists()


def test_withdrawn_source_not_sent_and_running_model_cancelled(context, source, manuscript):
    from core.impacts.ai import read_impact

    withdrawn, _ = change(context, source)
    run, _ = scan(context, withdrawn)
    with override_settings(AI_MODEL="synthetic", AI_BASE_URL="http://127.0.0.1:10000/v1"):
        job = create_model(context, run, manuscript)
        assert read_impact(job)["sources"] == []
        claimed = claim(job.pk)
        ProjectMember.objects.create(
            project=context[1],
            user=get_user_model().objects.create_user(username="viewer"),
            role="reviewer",
        )
        update = payload(
            version=1,
            blocks=[
                {k: b[k] for k in ["id", "text", "heading_level"]} for b in manuscript["blocks"]
            ],
        )
        update["blocks"][1]["text"] = "作者的新稿"
        assert save(context, update).status_code == 200
        with transaction.atomic():
            assert not valid_locked(lock_job(job.pk), claimed.generation)
        job.refresh_from_db()
        assert job.status == "cancelled" and job.error_code == "ai_input_changed"


def test_old_expression_job_cancelled_before_new_tool_call(context, source, manuscript):
    with override_settings(AI_MODEL="synthetic", AI_BASE_URL="http://127.0.0.1:10000/v1"):
        job = expression_job(context, manuscript, source)
        claimed = claim(job.pk)
        change(context, source, new_source(context, source))
        assert AIRun(claimed).handle({"type": "model_start"}) is None
        job.refresh_from_db()
        assert job.status == "cancelled"
        assert not job.model_calls.exists()


def test_database_immutable_and_scope_permissions(context, source, manuscript):
    link_block(context, manuscript, source, 0)
    corrected, _ = change(context, source, new_source(context, source))
    run, items = scan(context, corrected)
    for model, pk, fields in [
        (MaterialChange, corrected["id"], {"note": "改写"}),
        (ImpactRun, run["id"], {"number": 99}),
        (ImpactItem, items[0]["id"], {"snapshot": {}}),
    ]:
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.filter(pk=pk).update(**fields)
    other = Project.objects.create(owner=context[2], name="另一个项目")
    assert context[0].get(path(other, f"impact-runs/{run['id']}/")).status_code == 404
    with pytest.raises(IntegrityError), transaction.atomic():
        source[0].material.project = other
        source[0].material.save()
    viewer = get_user_model().objects.create_user(username="impact-viewer")
    ProjectMember.objects.create(project=context[1], user=viewer, role="reviewer")
    context[0].force_authenticate(viewer)
    assert context[0].get(path(context[1], f"impact-runs/{run['id']}/")).status_code == 200
    endpoint = path(context[1], f"impact-items/{items[0]['id']}/")
    assert context[0].post(endpoint, handle_body(items[0]), format="json").status_code == 403
    ProjectMember.objects.filter(user=viewer).delete()
    assert context[0].get(endpoint).status_code == 404


def test_correction_projection_and_withdrawn_path_removal(context, source, manuscript):
    from core.graph.service import graph_paths, purge_projection, sync_project

    pid = context[1].pk
    try:
        link_block(context, manuscript, source, 0)
        assert sync_project(pid)
        assert graph_paths(pid)[2] == 1
        change(context, source, new_source(context, source))
        assert sync_project(pid)
        route = context[0].get(path(context[1], "graph/paths/")).data["results"][0]
        assert route["state"] == "needs_review"
        change(context, source)
        assert sync_project(pid)
        assert graph_paths(pid)[2] == 0
    finally:
        purge_projection(pid)


@pytest.mark.parametrize("cause", ["source", "permission", "policy"])
def test_model_cancelled_on_scope_or_authorization_change(context, source, manuscript, cause):
    corrected, _ = change(context, source, new_source(context, source))
    run, _ = scan(context, corrected)
    with override_settings(AI_MODEL="synthetic", AI_BASE_URL="http://127.0.0.1:10000/v1"):
        job = create_model(context, run, manuscript)
        claimed = claim(job.pk)
        if cause == "source":
            change(context, source)
        elif cause == "permission":
            context[2].is_active = False
            context[2].save()
        else:
            ProjectPolicy.objects.filter(project=context[1]).update(allowed_actions=[])
        assert AIRun(claimed).handle({"type": "model_start"}) is None
        job.refresh_from_db()
        assert job.status == "cancelled"
        assert not job.model_calls.exists()


def test_source_change_conflicts_with_author_handling_and_recheck(context, source, manuscript):
    link_block(context, manuscript, source, 0)
    corrected, _ = change(context, source, new_source(context, source))
    run, items = scan(context, corrected)
    item = items[0]
    change(context, source)
    endpoint = path(context[1], f"impact-items/{item['id']}/")
    assert context[0].post(endpoint, handle_body(item), format="json").status_code == 409
    assert not ImpactDecision.objects.exists()
    assert context[0].get(path(context[1], f"impact-runs/{run['id']}/")).data["sources_changed"]
    assert (
        context[0]
        .post(
            path(context[1], f"material-changes/{corrected['id']}/runs/"),
            {"request_key": str(uuid4()), "sources_token": corrected["sources_token"]},
            format="json",
        )
        .status_code
        == 409
    )


def test_cross_material_relation_rejected_by_api_and_database(context, source):
    replacement = new_source(context)
    data = change_body(source, replacement)
    assert (
        context[0].post(path(context[1], "material-changes/"), data, format="json").status_code
        == 404
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        MaterialChange.objects.create(
            source_version=source[0],
            replacement=replacement[0],
            kind="correction",
            scope="version",
            note="跨材料关系不得登记",
            state_snapshot={},
            created_by=context[2],
            request_key=str(uuid4()),
            request_digest="x",
        )
    source[0].refresh_from_db()
    assert source[0].usage_state == "active"


def test_model_empty_result_with_all_selected_blocks_registered(context, source, manuscript):
    for index in range(len(manuscript["blocks"])):
        link_block(context, manuscript, source, index)
    corrected, _ = change(context, source, new_source(context, source))
    run, _ = scan(context, corrected)
    with provider(
        lambda number, _: (
            [("read_impact", {})] if number == 1 else [("submit_impact", {"candidates": []})]
        )
    ):
        from core.impacts.ai import read_impact

        job = create_model(context, run, manuscript)
        assert read_impact(job)["blocks"] == []
        execute_job(str(job.pk))
    job.refresh_from_db()
    assert job.status == "succeeded", job.error_code
    assert job.output["item_ids"] == []
    assert not ImpactItem.objects.filter(origin="model").exists()
