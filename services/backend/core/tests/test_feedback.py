from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from django.test import override_settings
from rest_framework.test import APIClient

from core.accounts.wechat import login_wechat
from core.ai.runtime import AIRun
from core.common.errors import ParseFailure
from core.jobs.service import claim
from core.models import (
    Feedback,
    FeedbackCandidate,
    FeedbackCandidateDecision,
    FeedbackTask,
    FeedbackTaskRevision,
    Job,
    Manuscript,
    Material,
    MentorReport,
    Project,
    ProjectMember,
    ProjectPolicy,
    WechatIdentity,
)
from core.tests.test_ai_jobs import provider
from core.tests.test_expressions import manuscript as expression_manuscript
from core.tests.test_library import context as library_context
from core.tests.test_library import source as library_source
from core.tests.test_manuscripts import payload, save
from core.tests.test_materials import path
from worker.tasks import execute_job

context = library_context
source = library_source
manuscript = expression_manuscript
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def location(manuscript=None):
    return {
        "manuscript_version": manuscript["version"] if manuscript else None,
        "block_id": manuscript["blocks"][1]["id"] if manuscript else None,
    }


def create_feedback(context, manuscript=None, source=None, **changes):
    data = {
        "request_key": str(uuid4()),
        "text": "请补充样本条件，并解释指标选择。",
        "source_label": "自制会议记录，作者转录",
        "source_chunk_id": str(source[1].chunks.first().pk) if source else None,
        **location(manuscript),
        **changes,
    }
    response = context[0].post(path(context[1], "feedback/"), data, format="json")
    assert response.status_code in [200, 201], response.data
    return response.data, data


def create_split(context, feedback, manuscript=None):
    ProjectPolicy.objects.filter(project=context[1]).update(
        verified=True, allowed_actions=["feedback"], source="自制规则", source_version="v1"
    )
    data = {"idempotency_key": str(uuid4()), "policy_version": 1, **location(manuscript)}
    with patch("core.feedback.views.dispatch"):
        response = context[0].post(
            path(context[1], f"feedback/{feedback['id']}/split/"), data, format="json"
        )
    assert response.status_code == 201, response.data
    return Job.objects.get(pk=response.data["id"]), data


def output():
    return {
        "candidates": [
            {
                "title": "补充样本条件",
                "instruction": "由作者检查材料并补充样本条件。",
                "quote": "请补充样本条件",
                "occurrence": 1,
            },
            {
                "title": "解释指标选择",
                "instruction": "由作者说明指标选择依据。",
                "quote": "解释指标选择",
                "occurrence": 1,
            },
        ],
    }


def run_split(context, feedback, manuscript=None, respond=None):
    with provider(
        respond
        or (
            lambda number, _: (
                [("read_feedback", {})] if number == 1 else [("submit_feedback", output())]
            )
        )
    ) as requests:
        job, _ = create_split(context, feedback, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        assert {tool["function"]["name"] for tool in requests[0]["tools"]} == {
            "read_feedback",
            "submit_feedback",
        }
    return job


def task_body(manuscript=None, **changes):
    return {
        "request_key": str(uuid4()),
        "title": "作者核对样本条件",
        "instruction": "根据原始记录补充说明。",
        **location(manuscript),
        **changes,
    }


def manual_task(context, feedback, manuscript=None):
    data = task_body(manuscript)
    response = context[0].post(
        path(context[1], f"feedback/{feedback['id']}/tasks/"), data, format="json"
    )
    assert response.status_code == 201, response.data
    return response.data, data


def progress_body(task, manuscript=None, **changes):
    return task_body(
        manuscript,
        **{
            "title": task["current"]["title"],
            "instruction": task["current"]["instruction"],
            "version": task["current"]["number"],
            "status": "doing",
            "note": "正在检查原始记录",
            "result_kind": "pending",
            **changes,
        },
    )


def modify_manuscript(context, manuscript):
    blocks = [
        {"id": block["id"], "text": block["text"], "heading_level": block["heading_level"]}
        for block in manuscript["blocks"]
    ]
    blocks[1]["text"] += "作者补充了样本条件。"
    response = save(context, payload(manuscript["version"], blocks=blocks))
    assert response.status_code == 200
    return response.data


def test_manual_feedback_progress_actual_change_and_separate_mentor_history(
    context, manuscript, source
):
    client, project, _ = context
    feedback, data = create_feedback(context, manuscript, source)
    assert feedback["recording"] == "author_transcription"
    assert feedback["location"]["position"] == 2
    assert client.post(path(project, "feedback/"), data, format="json").data["id"] == feedback["id"]
    assert (
        client.post(
            path(project, "feedback/"), {**data, "text": "其他意见"}, format="json"
        ).status_code
        == 409
    )
    task, task_data = manual_task(context, feedback, manuscript)
    url = path(project, f"feedback-tasks/{task['id']}/")
    assert task["candidate_id"] is None and task["current"]["mentor_reports"] == []
    assert (
        client.post(
            path(project, f"feedback/{feedback['id']}/tasks/"), task_data, format="json"
        ).data["id"]
        == task["id"]
    )
    changed = modify_manuscript(context, manuscript)
    assert client.get(url).data["current"]["location"]["stale"]
    assert client.get(path(project, f"feedback/{feedback['id']}/")).data["location"]["stale"]
    stale = progress_body(task, manuscript)
    assert client.post(url, stale, format="json").status_code == 409
    completed = progress_body(
        task,
        changed,
        status="completed",
        result_kind="modified",
        note="已据原始记录补充条件，位置见关联正文。",
    )
    saved = client.post(url, completed, format="json")
    assert saved.status_code == 200, saved.data
    assert saved.data["current"]["number"] == 2
    assert saved.data["current"]["mentor_reports"] == []
    assert saved.data["original_location"]["manuscript_version"] == 1
    assert saved.data["current"]["location"]["manuscript_version"] == 2
    assert client.post(url, completed, format="json").data["current"]["number"] == 2
    report = {
        "request_key": str(uuid4()),
        "version": 2,
        "status": "confirmed",
        "text": "自制导师回复：本次处理可以。",
        "source_label": "作者转录的会议回复",
    }
    recorded = client.post(url + "mentor-reports/", report, format="json")
    assert recorded.status_code == 201 and recorded.data["recording"] == "author_transcription"
    assert client.post(url + "mentor-reports/", report, format="json").status_code == 200
    next_body = progress_body(saved.data, changed)
    assert client.post(url, next_body, format="json").status_code == 200
    latest = client.get(url).data
    assert latest["current"]["mentor_reports"] == []
    history = client.get(url + "history/").data
    assert history["count"] == 3 and history["results"][1]["mentor_reports"][0]["task_version"] == 2
    assert (
        client.post(
            url + "mentor-reports/", {**report, "request_key": str(uuid4())}, format="json"
        ).status_code
        == 409
    )
    assert FeedbackTask.objects.count() == MentorReport.objects.count() == 1


def test_sdk_candidates_need_author_confirmation_and_do_not_modify_manuscript(context, manuscript):
    client, project, _ = context
    feedback, _ = create_feedback(context, manuscript)
    job = run_split(context, feedback, manuscript)
    assert job.model_calls.count() == 2
    assert "2 条候选" in job.output["summary"] and "不代表导师确认" in job.output["summary"]
    assert not FeedbackTask.objects.exists() and not MentorReport.objects.exists()
    assert Manuscript.objects.get(project=project).current_revision.number == 1
    candidates = client.get(path(project, f"feedback/{feedback['id']}/candidates/")).data
    assert candidates["count"] == 2 and all(
        item["decision"] is None for item in candidates["results"]
    )
    candidate = candidates["results"][0]
    decision = task_body(
        manuscript, action="accepted", confirmed=True, reason="已核对原始意见", policy_version=1
    )
    url = path(project, f"feedback-candidates/{candidate['id']}/decision/")
    assert client.post(url, {**decision, "confirmed": False}, format="json").status_code == 400
    accepted = client.post(url, decision, format="json")
    assert accepted.status_code == 200, accepted.data
    task_id = accepted.data["decision"]["task_id"]
    assert client.post(url, decision, format="json").data["decision"]["task_id"] == task_id
    assert client.post(url, {**decision, "title": "其他标题"}, format="json").status_code == 409
    assert (
        client.post(url, {**decision, "request_key": str(uuid4())}, format="json").status_code
        == 409
    )
    task = client.get(path(project, f"feedback-tasks/{task_id}/")).data
    assert task["candidate_id"] == candidate["id"] and task["current"]["status"] == "todo"
    other = candidates["results"][1]
    rejected = client.post(
        path(project, f"feedback-candidates/{other['id']}/decision/"),
        {**decision, "request_key": str(uuid4()), "action": "rejected", "confirmed": False},
        format="json",
    )
    assert rejected.status_code == 200 and rejected.data["decision"]["task_id"] is None
    assert FeedbackTask.objects.count() == 1 and FeedbackCandidateDecision.objects.count() == 2


def test_old_candidate_cannot_be_confirmed_but_can_be_rejected(context, manuscript):
    feedback, _ = create_feedback(context, manuscript)
    job = run_split(context, feedback, manuscript)
    changed = modify_manuscript(context, manuscript)
    candidate = FeedbackCandidate.objects.filter(job=job).first()
    url = path(context[1], f"feedback-candidates/{candidate.pk}/decision/")
    data = task_body(changed, action="accepted", confirmed=True, reason="", policy_version=1)
    assert context[0].post(url, data, format="json").status_code == 409
    ProjectPolicy.objects.filter(project=context[1]).update(allowed_actions=[])
    assert (
        context[0]
        .post(url, {**data, "action": "rejected", "confirmed": False}, format="json")
        .status_code
        == 200
    )
    assert not FeedbackTask.objects.exists()


@pytest.mark.parametrize("change", ["manuscript", "source", "permission"])
def test_staged_result_not_published_after_input_or_permission_change(
    context, manuscript, source, change
):
    feedback, _ = create_feedback(context, manuscript, source)
    with provider(lambda *_: []):
        job, _ = create_split(context, feedback, manuscript)
        state = AIRun(claim(job.pk))
        state.handle({"type": "model_start"})
        state.handle({"type": "model_end", "ok": True, "usage": None})
        state.handle({"type": "tool", "name": "read_feedback", "args": {}})
        assert state.handle({"type": "tool", "name": "submit_feedback", "args": output()}) == {
            "status": "staged"
        }
        if change == "manuscript":
            modify_manuscript(context, manuscript)
        elif change == "source":
            Material.objects.filter(pk=source[0].material_id).update(
                access_state="withdrawn", state_version=2
            )
        else:
            ProjectPolicy.objects.filter(project=context[1]).update(allowed_actions=[])
        assert state.handle({"type": "done", "success": True}) is None
    job.refresh_from_db()
    assert job.status == "cancelled" and not FeedbackCandidate.objects.exists()


def test_feedback_tool_scope_and_fabricated_quote_are_rejected(context):
    feedback, _ = create_feedback(context)
    with provider(lambda *_: []):
        job, _ = create_split(context, feedback)
        state = AIRun(claim(job.pk))
        state.handle({"type": "model_start"})
        state.handle({"type": "model_end", "ok": True, "usage": None})
        for name in ["read_evidence", "read_manuscript", "complete_task", "mentor_confirm"]:
            with pytest.raises(ParseFailure) as error:
                state.handle({"type": "tool", "name": name, "args": {}})
            assert error.value.code == "tool_denied"
        state.handle({"type": "tool", "name": "read_feedback", "args": {}})
        wrong = output()
        wrong["candidates"][0]["quote"] = "导师未说过的要求"
        assert (
            state.handle({"type": "tool", "name": "submit_feedback", "args": wrong})["status"]
            == "rejected"
        )
        assert not FeedbackCandidate.objects.exists()


def test_empty_feedback_split_is_valid_and_no_tasks_created(context):
    feedback, _ = create_feedback(context, text="待下次讨论。")
    job = run_split(
        context,
        feedback,
        respond=lambda number, _: (
            [("read_feedback", {})] if number == 1 else [("submit_feedback", {"candidates": []})]
        ),
    )
    assert job.output["candidate_ids"] == [] and not FeedbackTask.objects.exists()
    assert "0 条候选" in job.output["summary"]


def test_wrong_occurrence_reports_actual_count_and_requires_repair(context):
    feedback, _ = create_feedback(context)
    invalid = output()
    invalid["candidates"][1]["occurrence"] = 2

    def respond(number, body):
        if number == 1:
            return [("read_feedback", {})]
        if number == 3:
            assert "解释指标选择" in str(body) and "只有 1 处" in str(body)
            assert not FeedbackCandidate.objects.exists() and not FeedbackTask.objects.exists()
        return [("submit_feedback", invalid if number == 2 else output())]

    job = run_split(context, feedback, respond=respond)
    assert job.model_calls.count() == 3 and job.feedback_candidates.count() == 2
    assert not FeedbackTask.objects.exists() and not MentorReport.objects.exists()


def test_old_feedback_prompt_is_cancelled_without_model_request(context):
    feedback, _ = create_feedback(context)
    with provider(lambda *_: []) as requests:
        job, _ = create_split(context, feedback)
        job.input_snapshot["model"]["prompt_version"] = "feedback-v1"
        job.save(update_fields=["input_snapshot"])
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "cancelled", job.error_code
        assert not requests and not FeedbackCandidate.objects.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "completed", "result_kind": "pending"},
        {"status": "completed", "result_kind": "modified"},
        {"status": "completed", "result_kind": "no_change", "note": ""},
        {"status": "doing", "result_kind": "modified"},
        {"mentor_status": "confirmed"},
    ],
)
def test_progress_validation_and_no_ai_mentor_fields(context, changes):
    feedback, _ = create_feedback(context)
    task, _ = manual_task(context, feedback)
    response = context[0].post(
        path(context[1], f"feedback-tasks/{task['id']}/"),
        progress_body(task, **changes),
        format="json",
    )
    assert response.status_code == 400
    assert FeedbackTaskRevision.objects.count() == 1 and not MentorReport.objects.exists()


def test_permission_revocation_and_cross_project_locations(context, manuscript):
    client, project, user = context
    feedback, _ = create_feedback(context, manuscript)
    task, _ = manual_task(context, feedback, manuscript)
    reader = get_user_model().objects.create_user(username="feedback-reader")
    member = ProjectMember.objects.create(project=project, user=reader, role="reviewer")
    viewer = APIClient()
    viewer.force_authenticate(reader)
    assert viewer.get(path(project, "feedback-tasks/")).status_code == 200
    assert (
        viewer.post(
            path(project, f"feedback-tasks/{task['id']}/"),
            progress_body(task, manuscript),
            format="json",
        ).status_code
        == 403
    )
    member.delete()
    for suffix in [
        "feedback/",
        "feedback-tasks/",
        f"feedback-tasks/{task['id']}/",
        f"feedback/{feedback['id']}/",
    ]:
        assert viewer.get(path(project, suffix)).status_code == 404
    other = Project.objects.create(owner=user, name="另一专用项目")
    for suffix in [
        f"feedback/{feedback['id']}/",
        f"feedback-tasks/{task['id']}/",
        f"feedback-tasks/{task['id']}/history/",
    ]:
        assert client.get(path(other, suffix)).status_code == 404
    other_context = client, other, user
    foreign, _ = create_feedback(other_context)
    assert (
        client.post(
            path(other, f"feedback/{foreign['id']}/tasks/"), task_body(manuscript), format="json"
        ).status_code
        == 404
    )


def test_database_scope_and_immutable_history(context, manuscript):
    feedback, _ = create_feedback(context, manuscript)
    task, _ = manual_task(context, feedback, manuscript)
    with pytest.raises(IntegrityError), transaction.atomic():
        Feedback.objects.update(text="改写原始意见")
    with pytest.raises(IntegrityError), transaction.atomic():
        FeedbackTaskRevision.objects.update(status="completed")
    other = Project.objects.create(owner=context[2], name="其他测试项目")
    original = Feedback.objects.get(pk=feedback["id"])
    with pytest.raises(IntegrityError), transaction.atomic():
        Feedback.objects.create(
            project=other,
            text="越界关联",
            source_label="test",
            manuscript_revision=original.manuscript_revision,
            block_version=original.block_version,
            created_by=context[2],
            request_key="bad",
            request_digest="a" * 64,
        )


def test_concurrent_progress_single_version(context):
    feedback, _ = create_feedback(context)
    task, _ = manual_task(context, feedback)
    body = progress_body(task)
    barrier = Barrier(2)

    def update(_):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(context[2])
            barrier.wait(timeout=10)
            return client.post(
                path(context[1], f"feedback-tasks/{task['id']}/"), body, format="json"
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(update, range(2))) == [200, 200]
    assert FeedbackTaskRevision.objects.count() == 2


def test_wechat_progress_and_web_disclosure_do_not_count_completion_as_ai_text_adoption(
    context, source
):
    client, project, user = context
    feedback, _ = create_feedback(context, source=source)
    job = run_split(context, feedback)
    candidate = FeedbackCandidate.objects.filter(job=job).first()
    accepted = client.post(
        path(project, f"feedback-candidates/{candidate.pk}/decision/"),
        task_body(action="accepted", confirmed=True, reason="已核对", policy_version=1),
        format="json",
    )
    assert accepted.status_code == 200, accepted.data
    task_id = accepted.data["decision"]["task_id"]
    task_url = path(project, f"feedback-tasks/{task_id}/")
    task = client.get(task_url).data
    before = client.get(path(project, "disclosure/")).data
    assert before["summary"]["feedback_candidates"] == 2
    assert before["summary"]["confirmed_tasks"] == 1
    with override_settings(WECHAT_APP_ID="feedback-test-app"):
        WechatIdentity.objects.create(
            app_id="feedback-test-app", open_id="synthetic-feedback", user=user
        )
        session = login_wechat("synthetic-feedback")
        mini = APIClient()
        mini.credentials(HTTP_AUTHORIZATION="Bearer " + session["token"])
        data = progress_body(
            task,
            status="completed",
            result_kind="no_change",
            note="作者核查后决定保留正文，原因已登记。",
        )
        assert mini.post(task_url, data, format="json").status_code == 200
        assert mini.post(task_url, data, format="json").status_code == 200
    after = client.get(path(project, "disclosure/")).data
    assert after["summary"]["completed_tasks"] == 1 and after["summary"]["accepted"] == 0
    assert after["facts_token"] != before["facts_token"]
    assert client.get(task_url).data["current"]["mentor_reports"] == []
    detail = client.get(path(project, f"usage/{job.pk}/")).data
    assert detail["input"]["feedback_id"] == feedback["id"]
    assert detail["input"]["source_count"] == 1
    assert detail["input"]["version_ids"] == [str(source[0].pk)]
    assert detail["sources"][0]["chunk_id"] == str(feedback["source_chunk_id"])
    assert (
        next(item for item in detail["feedback_candidates"] if item["task_id"])["task_version"] == 2
    )
