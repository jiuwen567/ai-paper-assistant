from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, transaction
from rest_framework.test import APIClient

from core.models import (
    DisclosureRevision,
    Job,
    ManuscriptRevision,
    ModelCall,
    Project,
    ProjectMember,
    ReadingRecord,
    ReadingRevision,
    ReviewDecision,
    ReviewFinding,
    ReviewRecord,
)
from core.tests.test_expressions import context as expression_context
from core.tests.test_expressions import decide, run
from core.tests.test_expressions import manuscript as expression_manuscript
from core.tests.test_expressions import source as expression_source
from core.tests.test_materials import path

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
context = expression_context
manuscript = expression_manuscript
source = expression_source


def body(context, **changes):
    state = context[0].get(path(context[1], "disclosure/")).data
    return {
        "version": state["current"]["number"] if state["current"] else 0,
        "request_key": str(uuid4()),
        "facts_token": state["facts_token"],
        "text": state["draft"],
        "external_uses": [],
        "verified": False,
        **changes,
    }


def save(context, data):
    return context[0].post(path(context[1], "disclosure/"), data, format="json")


def task(context, **changes):
    return Job.objects.create(
        project=context[1],
        created_by=context[2],
        kind="ai",
        policy_version=1,
        idempotency_key=str(uuid4()),
        **changes,
    )


def test_empty_draft_external_history_idempotent_and_ai_disabled(context):
    client, project, _ = context
    initial = client.get(path(project, "disclosure/")).data
    assert initial["current"] is None and initial["summary"]["calls"] == 0
    assert "不推算原创比例" in initial["draft"]
    data = body(
        context,
        verified=True,
        external_uses=[
            {
                "tool": "作者自报工具 v1",
                "purpose": "检查措辞",
                "scope": "方法第 2 段",
                "used_at": "2026-10",
                "note": "仅采纳一处标点建议",
            }
        ],
    )
    first = save(context, data)
    assert first.status_code == 201, first.data
    assert first.data["current"]["verified"] and not first.data["stale"]
    assert save(context, data).status_code == 200
    assert save(context, {**data, "text": "另一内容"}).status_code == 409
    second = save(context, body(context, text="作者修改使用说明", external_uses=[], verified=False))
    assert second.status_code == 201
    assert save(context, data).data["current"]["number"] == 2
    history = client.get(path(project, "disclosure/history/")).data
    assert history["count"] == 2
    original = client.get(path(project, "disclosure/history/1/")).data
    assert original["external_uses"] == data["external_uses"]
    assert original["facts"]["summary"]["calls"] == 0


def test_call_output_adoption_and_original_revision_are_distinct(context, manuscript, source):
    client, project, _ = context
    queued = task(context)
    suggestion = run(context, manuscript, source)
    before = client.get(path(project, "disclosure/")).data
    assert before["summary"]["tasks"] == 2
    assert before["summary"]["calls"] == 3  # 读稿、读依据、提交结果。
    assert before["summary"]["expression_suggestions"] == 1
    assert before["summary"]["accepted"] == 0
    data = body(context, verified=True)
    assert save(context, data).status_code == 201
    assert decide(context, suggestion).status_code == 200
    after = client.get(path(project, "disclosure/")).data
    assert after["summary"]["accepted"] == 1 and after["stale"]
    assert after["manuscript_version"] == 2
    assert after["facts_token"] != before["facts_token"]
    detail = client.get(path(project, f"usage/{suggestion.job_id}/")).data
    item = detail["suggestions"][0]
    assert item["id"] == str(suggestion.pk)
    assert item["manuscript_version"] == 1
    assert item["decision"]["manuscript_version"] == 2
    assert detail["input"]["blocks"][1]["version_id"] == manuscript["blocks"][1]["version_id"]
    assert detail["sources"][0]["source_version_id"] == str(source[0].pk)
    assert detail["model"]["runtime"] == "pi-1.5.0"
    assert client.get(path(project, f"usage/{queued.pk}/")).data["calls"] == []
    old = client.get(path(project, "disclosure/history/1/")).data
    assert old["facts"]["summary"]["accepted"] == 0


def test_retry_calls_unknown_usage_and_private_fields_are_not_exposed(context):
    client, project, _ = context
    secret = "synthetic-secret-never-expose"
    job = task(
        context,
        status="failed",
        generation=2,
        input_snapshot={
            "model": {
                "model": "test",
                "runtime": "pi-1.5.0",
                "api_key": secret,
                "base_url": secret,
            },
            "question": secret,
            "sources": [{"chunk_id": str(uuid4()), "private": secret}],
        },
    )
    for generation in [1, 2]:
        ModelCall.objects.create(
            job=job,
            generation=generation,
            number=1,
            model="test",
            prompt_version="test-v1",
            input_digest="a" * 64,
            status="failed",
            usage=None,
        )
    local = task(
        context,
        input_snapshot={
            "embedding": {
                "model_name": "local",
                "runtime": "fastembed-test",
                "cache_dir": secret,
                "directory": secret,
            }
        },
    )
    Job.objects.filter(pk=local.pk).update(kind="index")
    overview = client.get(path(project, "disclosure/")).data
    assert overview["summary"]["calls"] == 2
    assert overview["purposes"]["index"]["calls"] == 0
    assert overview["summary"]["published_tasks"] == 0
    for endpoint in ["usage/", f"usage/{job.pk}/", f"usage/{local.pk}/", "disclosure/"]:
        response = client.get(path(project, endpoint))
        assert response.status_code == 200
        assert secret not in str(response.data)
    calls = client.get(path(project, f"usage/{job.pk}/")).data["calls"]
    assert len(calls) == 2 and calls[0]["usage"] is None
    assert save(context, body(context)).status_code == 201
    assert secret not in str(DisclosureRevision.objects.get().facts)


def test_new_calls_and_stale_version_reject_without_losing_history(context):
    data = body(context, verified=True)
    task(context)
    assert save(context, data).status_code == 409
    assert not DisclosureRevision.objects.exists()
    data = body(context)
    assert save(context, data).status_code == 201
    assert save(context, {**data, "request_key": str(uuid4())}).status_code == 409
    refreshed = body(context, verified=True)
    assert save(context, refreshed).status_code == 201
    task(context)
    state = context[0].get(path(context[1], "disclosure/")).data
    assert state["current"]["verified"] and state["stale"]
    assert state["current"]["number"] == 2


def test_permission_revocation_other_project_and_readonly(context):
    client, project, user = context
    data = body(context)
    assert save(context, data).status_code == 201
    reviewer = get_user_model().objects.create_user(username="disclosure-reader")
    member = ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
    viewer = APIClient(HTTP_HOST="localhost")
    viewer.force_authenticate(reviewer)
    assert viewer.get(path(project, "disclosure/")).status_code == 200
    assert viewer.post(path(project, "disclosure/"), data, format="json").status_code == 403
    member.delete()
    for endpoint in ["disclosure/", "disclosure/history/", "disclosure/history/1/", "usage/"]:
        assert viewer.get(path(project, endpoint)).status_code == 404
    assert viewer.post(path(project, "disclosure/"), data, format="json").status_code == 404
    other = Project.objects.create(owner=user, name="另一测试项目")
    job = task(context)
    assert client.get(path(other, f"usage/{job.pk}/")).status_code == 404
    assert client.get(path(other, "disclosure/history/1/")).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"external_uses": [{"tool": "missing-fields"}]},
        {
            "external_uses": [
                {
                    "tool": "x",
                    "purpose": "x",
                    "scope": "x",
                    "used_at": "",
                    "note": "",
                    "api_key": "not-accepted",
                }
            ]
        },
        {"facts": {"accepted": 100}},
        {"verified": True, "text": ""},
    ],
)
def test_strict_input(context, change):
    assert save(context, body(context, **change)).status_code == 400
    assert not DisclosureRevision.objects.exists()


def test_database_history_is_immutable(context):
    assert save(context, body(context)).status_code == 201
    with pytest.raises(IntegrityError), transaction.atomic():
        DisclosureRevision.objects.update(text="不能改写历史")
    with pytest.raises(IntegrityError), transaction.atomic():
        DisclosureRevision.objects.update(
            project=Project.objects.create(owner=context[2], name="不能移动历史")
        )


def test_concurrent_save_one_version(context):
    data = body(context)
    barrier = Barrier(2)

    def submit():
        close_old_connections()
        try:
            client = APIClient(HTTP_HOST="localhost")
            client.force_authenticate(context[2])
            barrier.wait(timeout=10)
            return client.post(path(context[1], "disclosure/"), data, format="json").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(statuses) == [200, 201]
    assert DisclosureRevision.objects.count() == 1


def test_usage_and_history_pagination(context):
    for _ in range(21):
        task(context)
    first = context[0].get(path(context[1], "usage/")).data
    second = context[0].get(path(context[1], "usage/?page=2")).data
    assert first["count"] == 21 and len(first["results"]) == 20
    assert len(second["results"]) == 1
    assert second["results"][0]["id"] not in {job["id"] for job in first["results"]}


def test_reading_verification_and_review_confirmation_are_not_adoption(context, manuscript):
    reading = ReadingRecord.objects.create(
        job=task(context, status="succeeded", input_snapshot={"purpose": "reading"}),
        model_output={},
        revision=1,
    )
    ReadingRevision.objects.create(record=reading, number=1, verified=True, created_by=context[2])
    review = ReviewRecord.objects.create(
        job=task(context, status="succeeded", input_snapshot={"purpose": "review"}),
        manuscript_revision=ManuscriptRevision.objects.get(manuscript__project=context[1]),
        summary="自制汇总测试",
    )
    finding = ReviewFinding.objects.create(
        review=review,
        block_version_id=manuscript["blocks"][1]["version_id"],
        category="other",
        model_output={},
        status="confirmed",
        revision=1,
    )
    ReviewDecision.objects.create(
        finding=finding,
        number=1,
        status="confirmed",
        created_by=context[2],
    )
    task(context, status="succeeded", output={"proposals": [{"text": "自制摘记"}]})
    state = context[0].get(path(context[1], "disclosure/")).data
    assert state["summary"]["reading_records"] == 1
    assert state["summary"]["review_findings"] == 1
    assert state["summary"]["notes"] == 1
    assert state["summary"]["accepted"] == 0
    assert state["summary"]["expression_suggestions"] == 0
    records = context[0].get(path(context[1], "usage/")).data["results"]
    assert next(item for item in records if item["purpose"] == "reading")["reading"] == {
        "id": str(reading.pk),
        "author_revision": 1,
    }
    details = next(item for item in records if item["purpose"] == "review")["review"]
    assert details["findings"][0]["status"] == "confirmed"
