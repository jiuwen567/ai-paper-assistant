import copy
from unittest.mock import patch
from uuid import uuid4

import pytest

from core.ai.runtime import AIRun
from core.common.errors import ParseFailure
from core.jobs.service import claim
from core.library.service import current_bibliography
from core.models import EvidenceNote, Job, Material, ProjectMember, ProjectPolicy, ReadingRecord
from core.reading.service import FIELDS, validate_reading
from core.tests.test_ai_jobs import provider
from core.tests.test_library import context as library_context
from core.tests.test_library import source as library_source
from core.tests.test_materials import intent, path, upload
from core.tests.test_parse_jobs import create
from worker.tasks import execute_job

context = library_context
source = library_source
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def create_reading(context, sources, **changes):
    client, project, _ = context
    ProjectPolicy.objects.filter(project=project).update(
        verified=True,
        source="自制规则",
        source_version="v1",
        allowed_actions=["reading", "comparison"],
    )
    body = {
        "idempotency_key": "reading-1",
        "policy_version": 1,
        "purpose": "reading" if len(sources) == 1 else "comparison",
        "version_ids": [str(item[0].pk) for item in sources],
        **changes,
    }
    with patch("core.reading.views.dispatch"):
        response = client.post(path(project, "reading/tasks/"), body, format="json")
    assert response.status_code in [200, 201], response.data
    return Job.objects.get(pk=response.data["id"])


def extraction(sources):
    documents = []
    for version, run in sources:
        chunk = run.chunks.order_by("ordinal").first()
        documents.append(
            {
                "version_id": str(version.pk),
                "fields": {
                    key: {
                        "status": "reported",
                        "text": "协议样例提取",
                        "citations": [{"chunk_id": str(chunk.pk), "quote": chunk.text[:30]}],
                    }
                    for key in FIELDS
                },
            }
        )
    return {
        "documents": documents,
        "comparison": None
        if len(sources) == 1
        else {
            "status": "comparable",
            "reason": "协议样例比较",
            "citations": [
                document["fields"]["conditions"]["citations"][0] for document in documents
            ],
        },
    }


def respond_with(sources, result):
    def respond(number, _):
        return (
            [
                ("read_evidence", {"chunk_ids": [str(chunk.pk)]})
                for _, run in sources
                for chunk in run.chunks.all()
            ]
            if number == 1
            else [("submit_reading", result)]
        )

    return respond


def test_sdk_reading_author_revision_idempotency_and_scope(context, source):
    client, project, user = context
    result = extraction([source])
    with provider(respond_with([source], result)) as requests:
        job = create_reading(context, [source])
        assert create_reading(context, [source]).pk == job.pk
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        record = ReadingRecord.objects.get(job=job)
        assert len(requests) == 2 and not EvidenceNote.objects.exists()
        assert not record.revisions.exists()
        assert client.get(path(project, "reading/")).data["count"] == 1
        url = path(project, f"reading/{record.pk}/")
        edit = {
            "version": 0,
            "edits": [{"version_id": str(source[0].pk), "field": "result", "text": "作者独立修订"}],
            "note": "作者的理解",
            "verified": True,
        }
        for _ in range(2):
            saved = client.patch(url, edit, format="json")
            assert saved.status_code == 200, saved.data
            assert saved.data["revision"] == 1
        record.refresh_from_db()
        assert (
            record.revisions.count() == 1
            and record.model_output["documents"][0]["fields"]["result"]["text"] == "协议样例提取"
        )
        assert client.patch(url, {**edit, "note": "旧窗口覆盖"}, format="json").status_code == 409
        assert (
            client.patch(url, {**edit, "version": 1, "model_output": {}}, format="json").status_code
            == 400
        )
        Material.objects.filter(pk=source[0].material_id).update(state_version=3)
        assert client.get(url).data["sources_changed"] is True
        assert client.patch(url, {**edit, "version": 1}, format="json").status_code == 409
        assert (
            client.patch(url, {**edit, "version": 1, "verified": False}, format="json").status_code
            == 200
        )
        reviewer = type(user).objects.create_user(username="reading-reviewer")
        ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
        client.force_authenticate(reviewer)
        assert client.get(url).status_code == 200
        assert client.patch(url, {**edit, "version": 2}, format="json").status_code == 403
        ProjectMember.objects.filter(project=project, user=reviewer).delete()
        assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("quote", "reading_citation_invalid"),
        ("version", "reading_source_invalid"),
        ("chunk", "reading_citation_invalid"),
        ("unread", "reading_citation_invalid"),
        ("extra", "reading_schema_invalid"),
        ("missing_document", "reading_source_invalid"),
        ("comparison", "reading_schema_invalid"),
        ("fabricated_missing", "reading_schema_invalid"),
        ("number", "reading_number_mismatch"),
    ],
)
def test_rejects_incorrect_evidence_and_structure(context, source, mutation, code):
    with provider(lambda *_: []):
        job = create_reading(context, [source])
        result = extraction([source])
        value = result["documents"][0]["fields"]["result"]
        read = {str(chunk.pk) for chunk in source[1].chunks.all()}
        if mutation == "quote":
            value["citations"][0]["quote"] = "作者笔记不能冒充原文"
        elif mutation == "version":
            result["documents"][0]["version_id"] = str(uuid4())
        elif mutation == "chunk":
            value["citations"][0]["chunk_id"] = str(uuid4())
        elif mutation == "unread":
            read = set()
        elif mutation == "extra":
            value["verified"] = True
        elif mutation == "missing_document":
            result["documents"] = []
        elif mutation == "comparison":
            result["comparison"] = {"status": "uncertain", "reason": "wrong", "citations": []}
        elif mutation == "number":
            value["text"] = "虚构数值 99999"
        else:
            value["status"] = "not_mentioned"
        with pytest.raises(ParseFailure, match=code):
            validate_reading(job, result, read)
        assert not ReadingRecord.objects.exists()


def test_missing_fields_need_all_chunks_and_abstract_scope_is_preserved(context, source):
    _, _, user = context
    _, revision = current_bibliography(source[0], user)
    revision.snapshot["source_scope"] = "abstract"
    revision.save()
    with provider(lambda *_: []):
        job = create_reading(context, [source])
        result = extraction([source])
        result["documents"][0]["fields"]["limitations"] = {
            "status": "not_mentioned",
            "text": "",
            "citations": [],
        }
        first = str(source[1].chunks.order_by("ordinal").first().pk)
        partial = validate_reading(job, copy.deepcopy(result), {first})
        assert partial["documents"][0]["fields"]["limitations"]["status"] == "unavailable"
        complete = validate_reading(
            job, result, {str(chunk.pk) for chunk in source[1].chunks.all()}
        )
        assert complete["documents"][0]["fields"]["limitations"]["text"] == "所选摘要未提及。"
        assert complete["documents"][0]["source_scope"] == "abstract"


@pytest.fixture
def pair(context, source):
    data = "自制记录：条件为 40 摄氏度，速率为 2 毫摩尔每分钟。".encode()
    with patch("core.materials.parse_views.dispatch"):
        version = intent(context, data=data, request_key="upload-2", title="第二份自制记录")
        assert upload(context, version, data).status_code == 200
        run = create(context, version, key="parse-2")
        execute_job(str(run.job_id))
    return [source, (version, run)]


def test_comparison_requires_each_source_and_sufficient_conditions(context, pair):
    result = extraction(pair)
    with provider(respond_with(pair, result)):
        job = create_reading(context, pair)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        record = ReadingRecord.objects.get(job=job)
        assert record.model_output["comparison"]["status"] == "uncertain"
        assert len(record.model_output["documents"]) == 2
        ids = {str(chunk.pk) for _, run in pair for chunk in run.chunks.all()}
        wrong = extraction(pair)
        wrong["documents"][0]["fields"]["result"]["citations"] = wrong["documents"][1]["fields"][
            "result"
        ]["citations"]
        with pytest.raises(ParseFailure, match="reading_citation_invalid"):
            validate_reading(job, wrong, ids)
        wrong = extraction(pair)
        wrong["comparison"]["reason"] = "虚构比较数值 99999"
        with pytest.raises(ParseFailure, match="reading_number_mismatch"):
            validate_reading(job, wrong, ids)


def test_cross_source_fields_are_rejected_together_without_partial_publication(context, pair):
    with provider(lambda *_: []):
        job = create_reading(context, pair)
        result = extraction(pair)
        for field in FIELDS:
            result["documents"][0]["fields"][field] = copy.deepcopy(
                result["documents"][1]["fields"][field]
            )
        ids = {str(chunk.pk) for _, run in pair for chunk in run.chunks.all()}
        with pytest.raises(ParseFailure) as error:
            validate_reading(job, result, ids)
        assert error.value.code == "reading_citation_invalid"
        assert all(f"{pair[0][0].pk}.{field}" in error.value.message for field in FIELDS)
        assert not ReadingRecord.objects.exists()


def test_citation_repair_hint_uses_only_exact_matches_in_read_selected_source(context, pair):
    with provider(lambda *_: []):
        job = create_reading(context, pair)
        chunk = pair[0][1].chunks.order_by("ordinal").first()
        other = pair[1][1].chunks.order_by("ordinal").first()
        ids = {str(chunk.pk), str(other.pk)}
        for quote, hinted in [(chunk.text, True), (other.text, False), ("伪造原文", False)]:
            result = extraction(pair)
            value = result["documents"][0]["fields"]["result"]
            value["citations"] = [{"chunk_id": str(uuid4()), "quote": quote}]
            with pytest.raises(ParseFailure) as error:
                validate_reading(job, result, ids)
            message = error.value.message
            assert (f"已读片段 {chunk.pk}" in message) == hinted
            assert f"已读片段 {other.pk}" not in message
        assert not ReadingRecord.objects.exists()


def test_identical_tool_submission_is_idempotent_but_conflicts_discard_everything(context, source):
    result = extraction([source])
    for conflict in [False, True]:
        second = copy.deepcopy(result)
        if conflict:
            second["documents"][0]["fields"]["subject"]["text"] = "不同提取"
        with provider(
            lambda number, body: (
                respond_with([source], result)(number, body)
                if number == 1
                else [("submit_reading", result), ("submit_reading", second)]
            )
        ):
            job = create_reading(context, [source], idempotency_key=f"duplicate-{conflict}")
            execute_job(str(job.pk))
            job.refresh_from_db()
            assert job.status == ("failed" if conflict else "succeeded"), job.error_code
            assert ReadingRecord.objects.filter(job=job).count() == (0 if conflict else 1)


def test_no_record_after_stage_and_source_change(context, source):
    with provider(lambda *_: []):
        job = create_reading(context, [source])
        run = AIRun(claim(job.pk))
        run.handle({"type": "model_start"})
        run.handle({"type": "model_end", "ok": True})
        for chunk in source[1].chunks.all():
            run.handle(
                {"type": "tool", "name": "read_evidence", "args": {"chunk_ids": [str(chunk.pk)]}}
            )
        run.handle({"type": "tool", "name": "submit_reading", "args": extraction([source])})
        assert not ReadingRecord.objects.exists()
        Material.objects.filter(pk=source[0].material_id).update(state_version=2)
        assert run.handle({"type": "done", "success": True}) is None
        assert not ReadingRecord.objects.exists()


def test_old_prompt_snapshot_does_not_run_under_new_prompt(context, source):
    with provider(lambda *_: []) as requests:
        job = create_reading(context, [source])
        job.input_snapshot["model"]["prompt_version"] = "reading-v1"
        job.save(update_fields=["input_snapshot"])
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "cancelled", job.error_code
        assert not requests and not ReadingRecord.objects.exists()


def test_schema_feedback_repairs_within_existing_call_budget(context, pair):
    valid = extraction(pair)
    invalid = copy.deepcopy(valid)
    invalid["documents"] = invalid["documents"][:1]

    def respond(number, body):
        if number == 1:
            return respond_with(pair, valid)(number, body)
        return [("submit_reading", invalid if number == 2 else valid)]

    with provider(respond) as requests:
        job = create_reading(context, pair)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        assert len(requests) == 3
        assert ReadingRecord.objects.filter(job=job).count() == 1
        assert job.ai_events.filter(kind="validation_error").count() == 1


def test_repeated_schema_errors_are_bounded_and_never_publish(context, source):
    with provider(
        lambda *_: [("submit_reading", {"documents": [], "comparison": None})]
    ) as requests:
        job = create_reading(context, [source])
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.error_code == "model_call_limit" and len(requests) == 4
        assert not ReadingRecord.objects.exists()


@pytest.mark.parametrize("repair", [True, False])
def test_invalid_citation_can_repair_but_cannot_publish_or_expand_budget(context, source, repair):
    valid = extraction([source])
    invalid = copy.deepcopy(valid)
    invalid["documents"][0]["fields"]["result"]["citations"][0]["quote"] = "并非所选原文"

    def respond(number, body):
        if number == 1:
            return respond_with([source], valid)(number, body)
        assert not ReadingRecord.objects.exists()
        if number > 2:
            assert "reading_citation_invalid" in str(body)
        return [("submit_reading", valid if repair and number > 2 else invalid)]

    with provider(respond) as requests:
        job = create_reading(context, [source])
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == ("succeeded" if repair else "failed"), job.error_code
        assert len(requests) == (3 if repair else 4)
        assert ReadingRecord.objects.filter(job=job).count() == (1 if repair else 0)
        if not repair:
            assert job.error_code == "model_call_limit"
        assert job.ai_events.filter(kind="validation_error").exists()


def test_source_revocation_after_rejected_citation_stops_repair(context, source):
    valid = extraction([source])
    invalid = copy.deepcopy(valid)
    invalid["documents"][0]["fields"]["result"]["citations"][0]["chunk_id"] = str(uuid4())

    def respond(number, body):
        if number == 1:
            return respond_with([source], valid)(number, body)
        if number == 2:
            return [("submit_reading", invalid)]
        Material.objects.filter(pk=source[0].material_id).update(access_state="withdrawn")
        return [("submit_reading", valid)]

    with provider(respond):
        job = create_reading(context, [source])
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "cancelled", job.error_code
        assert not ReadingRecord.objects.exists()


def test_read_budget_returns_explicit_unavailable_and_does_not_authorize_citation(context, source):
    chunk = source[1].chunks.order_by("ordinal").first()
    with provider(lambda *_: []):
        job = create_reading(context, [source])
        run = AIRun(claim(job.pk))
        run.handle({"type": "model_start"})
        run.handle({"type": "model_end", "ok": True})
        run.read_characters = 8000
        response = run.handle(
            {"type": "tool", "name": "read_evidence", "args": {"chunk_ids": [str(chunk.pk)]}}
        )
        assert response[0]["unavailable"] and not run.read_ids
        rejected = run.handle(
            {"type": "tool", "name": "submit_reading", "args": extraction([source])}
        )
        assert rejected["status"] == "rejected" and rejected["code"] == "reading_citation_invalid"
        assert run.reading is None and not ReadingRecord.objects.exists()


def test_task_input_limits_permissions_and_source_listing(context, source):
    client, project, user = context
    url = path(project, "reading/tasks/")
    payload = {
        "idempotency_key": "input-check",
        "policy_version": 1,
        "purpose": "comparison",
        "version_ids": [str(source[0].pk)],
    }
    assert client.post(url, payload, format="json").status_code == 400
    with provider(lambda *_: []):
        payload["purpose"] = "reading"
        assert client.post(url, payload, format="json").status_code == 403
        assert client.get(path(project, "reading/sources/")).data["count"] == 1
        job = create_reading(context, [source])
        assert (
            client.post(
                url,
                {**payload, "idempotency_key": job.idempotency_key, "question": "不同问题"},
                format="json",
            ).status_code
            == 409
        )
        assert client.post(url, {**payload, "model": "other"}, format="json").status_code == 400
        Material.objects.filter(pk=source[0].material_id).update(access_state="withdrawn")
        assert client.get(path(project, "reading/sources/")).data["count"] == 0
        assert client.post(url, payload, format="json").status_code == 400
        reviewer = type(user).objects.create_user(username="task-reader")
        ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
        client.force_authenticate(reviewer)
        assert client.post(url, payload, format="json").status_code == 403
