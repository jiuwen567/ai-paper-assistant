from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from django.test import override_settings
from rest_framework.test import APIClient

from core.ai_jobs import AIRun
from core.expressions import content_guards
from core.jobs import claim
from core.models import (
    ExpressionDecision,
    ExpressionSuggestion,
    Job,
    Manuscript,
    ManuscriptCitation,
    Material,
    Project,
    ProjectMember,
    ProjectPolicy,
    WechatIdentity,
)
from core.tests.test_ai_jobs import provider
from core.tests.test_library import context as library_context
from core.tests.test_library import source as library_source
from core.tests.test_manuscripts import payload, save
from core.tests.test_materials import path
from core.wechat import login_wechat
from worker.tasks import execute_job

context = library_context
source = library_source
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def manuscript(context):
    body = payload()
    body["blocks"][1]["text"] = "本研究对样本进行了观察。"
    result = save(context, body)
    assert result.status_code == 200
    return result.data


def output_for(manuscript, source=None):
    citations = []
    if source:
        chunk = source[1].chunks.order_by("ordinal").first()
        citations = [{"chunk_id": str(chunk.pk), "quote": chunk.text}]
    return {
        "summary": "仅改善所选原句的表达，待作者核对。",
        "suggestions": [
            {
                "block_version_id": manuscript["blocks"][1]["version_id"],
                "quote": manuscript["blocks"][1]["text"],
                "occurrence": 1,
                "replacement": "本研究观察了样本。",
                "reason": "删去冗余动词，使句子简洁。",
                "kind": "expression",
                "citations": citations,
            }
        ],
    }


def respond_with(output, source=None):
    def respond(number, _):
        if number == 1:
            return [("read_manuscript", {})]
        if source and number == 2:
            return [
                (
                    "read_evidence",
                    {"chunk_ids": [str(chunk.pk) for chunk in source[1].chunks.all()]},
                )
            ]
        return [("submit_expression", output)]

    return respond


def create(context, manuscript, source=None, **changes):
    client, project, _ = context
    ProjectPolicy.objects.filter(project=project).update(
        verified=True, source="自制规则", source_version="v1", allowed_actions=["expression"]
    )
    body = {
        "idempotency_key": str(uuid4()),
        "policy_version": 1,
        "manuscript_version": manuscript["version"],
        "block_ids": [block["id"] for block in manuscript["blocks"]],
        "version_ids": [str(source[0].pk)] if source else [],
        **changes,
    }
    with patch("core.expression_views.dispatch"):
        response = client.post(path(project, "expressions/tasks/"), body, format="json")
    assert response.status_code in [200, 201], response.data
    return Job.objects.get(pk=response.data["id"])


def run(context, manuscript, source=None, output=None):
    with provider(respond_with(output or output_for(manuscript, source), source)):
        job = create(context, manuscript, source)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
    return ExpressionSuggestion.objects.get(job=job)


def decision_body(suggestion, **changes):
    return {
        "request_key": str(uuid4()),
        "manuscript_version": suggestion.manuscript_revision.number,
        "policy_version": 1,
        "action": "accepted",
        "meaning_confirmed": True,
        **changes,
    }


def decide(context, suggestion, body=None):
    client, project, _ = context
    return client.post(
        path(project, f"suggestions/{suggestion.pk}/decision/"),
        body or decision_body(suggestion),
        format="json",
    )


def test_sdk_suggestion_mini_accept_web_reads_atomic_result_and_idempotency(
    context, manuscript, source
):
    web, project, user = context
    suggestion = run(context, manuscript, source)
    before = web.get(path(project, f"suggestions/{suggestion.pk}/")).data
    assert before["decision"] is None and before["input_changed"] is False
    assert any(item["kind"] == "delete" for item in before["diff"])
    assert Manuscript.objects.get(project=project).current_revision.number == 1
    with override_settings(WECHAT_APP_ID="expression-test-app"):
        WechatIdentity.objects.create(app_id="expression-test-app", open_id="synthetic", user=user)
        session = login_wechat("synthetic")
        mini = APIClient(HTTP_HOST="localhost")
        mini.credentials(HTTP_AUTHORIZATION="Bearer " + session["token"])
        body = decision_body(suggestion)
        accepted = decide((mini, project, user), suggestion, body)
        assert accepted.status_code == 200, accepted.data
        assert decide((mini, project, user), suggestion, body).status_code == 200
    current = web.get(path(project, "manuscript/")).data
    assert current["version"] == 2 and current["origin"] == "expression"
    assert current["blocks"][1]["text"] == "本研究观察了样本。"
    assert current["blocks"][1]["id"] == manuscript["blocks"][1]["id"]
    assert ExpressionDecision.objects.count() == ManuscriptCitation.objects.count() == 1
    citation = ManuscriptCitation.objects.get()
    assert str(citation.block_version_id) == current["blocks"][1]["version_id"]
    assert citation.snapshot["quote"] == source[1].chunks.order_by("ordinal").first().text
    detail = web.get(path(project, f"suggestions/{suggestion.pk}/")).data
    assert detail["decision"]["manuscript_version"] == 2
    assert detail["decision"]["action"] == "accepted"
    assert decide(context, suggestion).status_code == 409
    assert decide(context, suggestion, {**body, "action": "rejected"}).status_code == 409


def test_edited_accept_and_reject_keeps_original(context, manuscript):
    suggestion = run(context, manuscript)
    rejected = decide(
        context,
        suggestion,
        decision_body(suggestion, action="rejected", meaning_confirmed=False, reason="保留原句"),
    )
    assert rejected.status_code == 200
    assert rejected.data["decision"]["manuscript_version"] is None
    assert Manuscript.objects.get(project=context[1]).current_revision.number == 1
    assert not ManuscriptCitation.objects.exists()
    suggestion = run(context, manuscript)
    accepted = decide(
        context, suggestion, decision_body(suggestion, action="edited", text="本研究已观察样本。")
    )
    assert accepted.status_code == 200, accepted.data
    assert accepted.data["decision"]["text"] == "本研究已观察样本。"
    assert accepted.data["model_output"]["replacement"] == "本研究观察了样本。"


@pytest.mark.parametrize("change", ["manuscript", "source", "policy", "revoke"])
def test_stale_or_revoked_decision_never_writes(context, manuscript, source, change):
    client, project, owner = context
    author = get_user_model().objects.create_user(username="expression-author")
    ProjectMember.objects.create(project=project, user=author, role="author")
    client.force_authenticate(author)
    suggestion = run(context, manuscript, source)
    if change == "manuscript":
        assert save(context, payload(1)).status_code == 200
    elif change == "source":
        Material.objects.filter(pk=source[0].material_id).update(state_version=2)
    elif change == "policy":
        ProjectPolicy.objects.create(project=project, version=2, created_by=owner)
    else:
        ProjectMember.objects.filter(project=project, user=author).delete()
    before = Manuscript.objects.get(project=project).current_revision_id
    response = decide(context, suggestion)
    assert response.status_code == (404 if change == "revoke" else 409), response.data
    assert Manuscript.objects.get(project=project).current_revision_id == before
    assert not ExpressionDecision.objects.exists() and not ManuscriptCitation.objects.exists()


def test_transaction_rolls_back_body_citations_and_decision(context, manuscript, source):
    suggestion = run(context, manuscript, source)
    before = Manuscript.objects.get(project=context[1]).current_revision_id
    with patch(
        "core.expression_views.ExpressionDecision.objects.create",
        side_effect=RuntimeError("测试事务失败"),
    ):
        with pytest.raises(RuntimeError):
            decide(context, suggestion)
    assert Manuscript.objects.get(project=context[1]).current_revision_id == before
    assert not ManuscriptCitation.objects.exists() and not ExpressionDecision.objects.exists()
    assert decide(context, suggestion).status_code == 200


def test_two_concurrent_identical_decisions_only_publish_once(context, manuscript):
    suggestion = run(context, manuscript)
    body = decision_body(suggestion)
    barrier = Barrier(2)
    _, project, user = context

    def submit():
        close_old_connections()
        try:
            client = APIClient(HTTP_HOST="localhost")
            client.force_authenticate(user)
            barrier.wait(timeout=10)
            return decide((client, project, user), suggestion, body).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results == [200, 200]
    assert ExpressionDecision.objects.count() == 1
    assert Manuscript.objects.get(project=project).current_revision.number == 2


@pytest.mark.parametrize(
    "replacement",
    [
        "本研究观察了 100 个样本。",
        "本研究未对样本进行观察。",
        "本研究证明样本全部有效。",
        "此外，样本在实际生产中显著提高了加工效率。",
    ],
)
def test_content_changes_are_not_plain_polish(context, manuscript, replacement):
    output = output_for(manuscript)
    output["suggestions"][0]["replacement"] = replacement
    suggestion = run(context, manuscript, output=output)
    assert suggestion.model_output["guard_reasons"]
    assert decide(context, suggestion).status_code == 400
    assert (
        decide(
            context, suggestion, decision_body(suggestion, action="edited", text=replacement)
        ).status_code
        == 400
    )
    assert not ExpressionDecision.objects.exists()
    assert Manuscript.objects.get(project=context[1]).current_revision.number == 1


def test_substantive_output_not_saved_as_replacement_and_no_automatic_confirmation(
    context, manuscript
):
    output = output_for(manuscript)
    output["suggestions"][0].update(kind="substantive", replacement="编造一段结论")
    suggestion = run(context, manuscript, output=output)
    assert suggestion.model_output["replacement"] == suggestion.model_output["quote"]
    assert decide(context, suggestion).status_code == 400
    assert (
        decide(
            context,
            suggestion,
            decision_body(suggestion, action="rejected", meaning_confirmed=False),
        ).status_code
        == 200
    )
    suggestion = run(context, manuscript)
    assert (
        decide(context, suggestion, decision_body(suggestion, meaning_confirmed=False)).status_code
        == 400
    )


def test_existing_citations_copied_and_changed_source_blocks_next_accept(
    context, manuscript, source
):
    suggestion = run(context, manuscript, source)
    assert decide(context, suggestion).status_code == 200
    current = context[0].get(path(context[1], "manuscript/")).data
    output = output_for(current)
    output["suggestions"][0]["replacement"] = "本研究已观察样本。"
    next_suggestion = run(context, current, output=output)
    assert decide(context, next_suggestion).status_code == 200
    assert ManuscriptCitation.objects.count() == 2
    current = context[0].get(path(context[1], "manuscript/")).data
    output = output_for(current)
    later = run(context, current, output=output)
    Material.objects.filter(pk=source[0].material_id).update(state_version=2)
    assert decide(context, later).status_code == 409


def test_database_scope_immutable_and_project_cleanup(context, manuscript, source):
    suggestion = run(context, manuscript, source)
    assert decide(context, suggestion).status_code == 200
    decision = ExpressionDecision.objects.get()
    citation = ManuscriptCitation.objects.get()
    client, project, user = context
    other = Project.objects.create(owner=user, name="其他项目")
    foreign = client.put(path(other, "manuscript/"), payload(), format="json").data
    for action in [
        lambda: ExpressionSuggestion.objects.filter(pk=suggestion.pk).update(model_output={}),
        lambda: ExpressionDecision.objects.filter(pk=decision.pk).update(text="改写决定"),
        lambda: ManuscriptCitation.objects.filter(pk=citation.pk).update(snapshot={}),
        lambda: Job.objects.filter(pk=suggestion.job_id).update(project=other),
        lambda: ManuscriptCitation.objects.create(
            block_version_id=foreign["blocks"][1]["version_id"],
            chunk=citation.chunk,
            bibliography_revision=citation.bibliography_revision,
            fingerprint="f" * 64,
            snapshot={},
            created_by=user,
        ),
    ]:
        with pytest.raises(IntegrityError), transaction.atomic():
            action()
    project.delete()
    assert not ExpressionSuggestion.objects.exists() and not ManuscriptCitation.objects.exists()


def test_staged_suggestion_discarded_after_manuscript_edit(context, manuscript):
    with provider(lambda *_: []):
        job = create(context, manuscript)
        run_state = AIRun(claim(job.pk))
        run_state.handle({"type": "model_start"})
        run_state.handle({"type": "model_end", "ok": True})
        run_state.handle({"type": "tool", "name": "read_manuscript", "args": {}})
        run_state.handle(
            {"type": "tool", "name": "submit_expression", "args": output_for(manuscript)}
        )
        assert save(context, payload(1)).status_code == 200
        assert run_state.handle({"type": "done", "success": True}) is None
        assert not ExpressionSuggestion.objects.exists()


def test_tool_cannot_set_author_decision_or_unread_citation(context, manuscript, source):
    output = output_for(manuscript, source)
    output["suggestions"][0]["accepted"] = True
    with provider(respond_with(output, source)):
        job = create(context, manuscript, source)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "failed"
        assert not ExpressionSuggestion.objects.exists()
    assert content_guards("样本温度为 25 ℃。", "样本温度为 35 ℃。")
    assert content_guards("变化为 5%。", "变化为 5。")
    assert content_guards("x≤5。", "x≥5。")
    assert content_guards("甲+乙", "甲-乙")


def test_reviewer_cannot_generate_or_decide_and_revoked_cannot_preview(context, manuscript):
    suggestion = run(context, manuscript)
    client, project, _ = context
    user = get_user_model().objects.create_user(username="expression-reviewer")
    ProjectMember.objects.create(project=project, user=user, role="reviewer")
    client.force_authenticate(user)
    assert client.get(path(project, "suggestions/")).status_code == 200
    assert decide(context, suggestion).status_code == 403
    assert client.post(path(project, "expressions/tasks/"), {}, format="json").status_code == 403
    ProjectMember.objects.filter(project=project, user=user).delete()
    assert (
        client.post(
            path(project, f"suggestions/{suggestion.pk}/preview/"),
            {"text": "作者私有草稿"},
            format="json",
        ).status_code
        == 404
    )
    assert not ExpressionDecision.objects.exists()


def test_empty_proposal_is_not_an_edit_and_unread_citations_never_publish(
    context, manuscript, source
):
    with provider(respond_with({"summary": "所选范围没有表达建议。", "suggestions": []})):
        job = create(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded" and job.output["suggestion_ids"] == []
    output = output_for(manuscript, source)
    # 提交了真实片段编号，但模型本次未读，不允许发布。
    with provider(respond_with(output)):
        job = create(context, manuscript, source)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "failed" and job.error_code == "model_call_limit"
        assert job.ai_events.filter(details__code="expression_citation_invalid").exists()
    assert not ExpressionSuggestion.objects.exists()
    assert Manuscript.objects.get(project=context[1]).current_revision.number == 1
