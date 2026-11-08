import copy
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from core.ai.runtime import AIRun
from core.common.errors import ParseFailure
from core.jobs.service import claim
from core.library.service import current_bibliography
from core.models import (
    BlockVersion,
    Job,
    Manuscript,
    Material,
    Project,
    ProjectMember,
    ProjectPolicy,
    ReviewDecision,
    ReviewFinding,
    ReviewRecord,
)
from core.reviews.service import validate_review
from core.tests.test_ai_jobs import provider
from core.tests.test_library import context as library_context
from core.tests.test_library import source as library_source
from core.tests.test_manuscripts import payload, save
from core.tests.test_materials import path
from worker.tasks import execute_job

context = library_context
source = library_source
pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def manuscript(context):
    body = payload()
    body["blocks"][1]["text"] = "所有条件下均有效。另一个待核对的句子。"
    response = save(context, body)
    assert response.status_code == 200
    return response.data


def create_review(context, manuscript, sources=(), **changes):
    client, project, _ = context
    ProjectPolicy.objects.filter(project=project).update(
        verified=True, source="自制规则", source_version="v1", allowed_actions=["review"]
    )
    body = {
        "idempotency_key": "review-1",
        "policy_version": 1,
        "manuscript_version": manuscript["version"],
        "block_ids": [block["id"] for block in manuscript["blocks"]],
        "version_ids": [str(source[0].pk) for source in sources],
        **changes,
    }
    with patch("core.reviews.views.dispatch"):
        response = client.post(path(project, "reviews/tasks/"), body, format="json")
    assert response.status_code in [200, 201], response.data
    return Job.objects.get(pk=response.data["id"])


def finding_output(manuscript, source=None):
    citations = []
    if source:
        chunk = source[1].chunks.order_by("ordinal").first()
        citations = [{"chunk_id": str(chunk.pk), "quote": chunk.text}]
    return {
        "findings": [
            {
                "block_version_id": manuscript["blocks"][1]["version_id"],
                "quote": "所有条件下均有效。",
                "occurrence": 1,
                "category": "overclaim",
                "support": "insufficient",
                "reason": "现有记录不足以支持覆盖所有条件的结论。",
                "action": "请作者核对实验条件与结论范围。",
                "citations": citations,
                "related_blocks": [],
                "research_evidence": [],
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
        return [("submit_review", output)]

    return respond


def test_sdk_review_source_dimensions_author_decisions_and_recheck(context, manuscript, source):
    client, project, user = context
    _, bibliography = current_bibliography(source[0], user)
    bibliography.snapshot["source_scope"] = "abstract"
    bibliography.save()
    output = finding_output(manuscript, source)
    with provider(respond_with(output, source)) as requests:
        job = create_review(context, manuscript, [source])
        assert create_review(context, manuscript, [source]).pk == job.pk
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        assert len(requests) == 3
        record = ReviewRecord.objects.get(job=job)
        assert "1 条" in record.summary and "不代表全文正确" in record.summary
        item = record.findings.get()
        assert item.status == "pending" and item.model_output["start"] == 0
        assert record.source_checks[0]["material_exists"] is True
        assert record.source_checks[0]["bibliography_registered"] is True
        assert record.source_checks[0]["publication_status"] == "unverified"
        assert record.source_checks[0]["source_scope"] == "abstract"
        assert client.get(path(project, "reviews/")).data["count"] == 1
        url = path(project, f"review-findings/{item.pk}/")
        assert client.get(url).data["manuscript_text"] == manuscript["blocks"][1]["text"]
        ignored = {"version": 0, "status": "ignored", "reason": ""}
        assert client.patch(url, ignored, format="json").status_code == 400
        ignored["reason"] = "作者核对后认为当前表述另有明确限定，暂不采纳。"
        assert client.patch(url, ignored, format="json").status_code == 200
        assert client.patch(url, ignored, format="json").data["revision"] == 1
        assert ReviewDecision.objects.count() == 1
        assert (
            client.patch(url, {**ignored, "status": "confirmed"}, format="json").status_code == 409
        )
        assert (
            client.get(
                path(project, f"reviews/{record.pk}/findings/?status=ignored&category=overclaim")
            ).data["count"]
            == 1
        )
        body = payload(
            1,
            blocks=[
                {key: block[key] for key in ["id", "text", "heading_level"]}
                for block in manuscript["blocks"]
            ],
        )
        body["blocks"][1]["text"] = "仅在本次测试条件下有效。"
        new = save(context, body).data
        assert client.get(path(project, f"reviews/{record.pk}/")).data["input_changed"] is True
        assert (
            client.patch(
                url, {"version": 1, "status": "confirmed", "reason": ""}, format="json"
            ).status_code
            == 409
        )
        recheck = create_review(
            context, new, [source], idempotency_key="recheck", previous_review_id=str(record.pk)
        )
        assert recheck.input_snapshot["manuscript"]["version"] == 2
        assert client.get(path(project, f"reviews/{record.pk}/")).data["recheck_tasks"][0][
            "id"
        ] == str(recheck.pk)
        # 新结果固定在新稿，旧问题及忽略原因仍可回查。
        with provider(
            respond_with(
                {"findings": []},
                source,
            )
        ):
            # provider 配置变化后须新建任务，避免把测试端点切换误认成相同配置。
            newer = create_review(
                context,
                new,
                [source],
                idempotency_key="recheck-new",
                previous_review_id=str(record.pk),
            )
            execute_job(str(newer.pk))
            newer.refresh_from_db()
            assert newer.status == "succeeded", newer.error_code
            assert ReviewRecord.objects.get(job=newer).previous_review_id == record.pk
            assert "0 条" in ReviewRecord.objects.get(job=newer).summary
        assert ReviewDecision.objects.get().reason == ignored["reason"]
        assert Manuscript.objects.get(project=project).current_revision.number == 2


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("unread_manuscript", "review_unread_manuscript"),
        ("block", "review_block_scope"),
        ("quote", "review_quote_invalid"),
        ("blank_quote", "review_schema_invalid"),
        ("occurrence", "review_quote_invalid"),
        ("citation", "review_citation_invalid"),
        ("unread_source", "review_citation_invalid"),
        ("research", "review_research_invalid"),
        ("unsupported", "review_support_invalid"),
        ("number", "review_number_mismatch"),
        ("model_decision", "review_schema_invalid"),
        ("duplicate", "review_duplicate_finding"),
    ],
)
def test_rejects_wrong_locations_evidence_and_model_confirmation(
    context, manuscript, source, mutation, code
):
    with provider(lambda *_: []):
        job = create_review(context, manuscript, [source])
        result = finding_output(manuscript, source)
        value = result["findings"][0]
        read = {str(chunk.pk) for chunk in source[1].chunks.all()}
        if mutation == "block":
            value["block_version_id"] = str(uuid4())
        elif mutation == "quote":
            value["quote"] = "原稿不存在的句子"
        elif mutation == "blank_quote":
            value["quote"] = "   "
        elif mutation == "occurrence":
            value["occurrence"] = 2
        elif mutation == "citation":
            value["citations"][0]["quote"] = "编造的依据"
        elif mutation == "unread_source":
            read = set()
        elif mutation == "research":
            value["research_evidence"] = [{"field": "result", "quote": "作者并未写下的结果"}]
        elif mutation == "unsupported":
            value.update(support="contradicts", citations=[])
        elif mutation == "number":
            value["reason"] = "虚构 99999 次实验"
        elif mutation == "model_decision":
            value["status"] = "confirmed"
        elif mutation == "duplicate":
            result["findings"].append(copy.deepcopy(value))
        with pytest.raises(ParseFailure, match=code):
            validate_review(job, result, read, mutation != "unread_manuscript")
        assert not ReviewRecord.objects.exists()


def test_no_materials_means_insufficient_not_false_and_author_research_is_separate(
    context, manuscript
):
    result = finding_output(manuscript)
    result["findings"][0]["research_evidence"] = [
        {"field": "method", "quote": manuscript["research"]["method"]}
    ]
    with provider(respond_with(result)):
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        record = ReviewRecord.objects.get(job=job)
        assert record.source_checks == []
        assert record.findings.get().model_output["support"] == "insufficient"
        assert record.findings.get().model_output["research_evidence"][0]["field"] == "method"


@pytest.mark.parametrize("change", ["manuscript", "source", "revoke"])
def test_staged_review_discarded_when_input_or_permission_changes(
    context, manuscript, source, change
):
    client, project, owner = context
    author = get_user_model().objects.create_user(username="review-author")
    ProjectMember.objects.create(project=project, user=author, role="author")
    client.force_authenticate(author)
    with provider(lambda *_: []):
        job = create_review(context, manuscript, [source])
        run = AIRun(claim(job.pk))
        run.handle({"type": "model_start"})
        run.handle({"type": "model_end", "ok": True})
        run.handle({"type": "tool", "name": "read_manuscript", "args": {}})
        run.handle(
            {
                "type": "tool",
                "name": "read_evidence",
                "args": {"chunk_ids": [str(chunk.pk) for chunk in source[1].chunks.all()]},
            }
        )
        run.handle(
            {
                "type": "tool",
                "name": "submit_review",
                "args": finding_output(manuscript, source),
            }
        )
        if change == "source":
            Material.objects.filter(pk=source[0].material_id).update(state_version=2)
        elif change == "manuscript":
            client.force_authenticate(owner)
            assert save(context, payload(1)).status_code == 200
        else:
            ProjectMember.objects.filter(user=author).delete()
        assert run.handle({"type": "done", "success": True}) is None
        assert not ReviewRecord.objects.exists()
        job.refresh_from_db()
        assert job.status == "cancelled"


def test_readers_cannot_decide_and_database_rejects_mixed_projects(context, manuscript):
    client, project, user = context
    with provider(respond_with(finding_output(manuscript))):
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
    record = ReviewRecord.objects.get(job=job)
    item = record.findings.get()
    reviewer = get_user_model().objects.create_user(username="only-reviewer")
    ProjectMember.objects.create(project=project, user=reviewer, role="reviewer")
    client.force_authenticate(reviewer)
    url = path(project, f"review-findings/{item.pk}/")
    assert client.get(url).status_code == 200
    assert (
        client.patch(
            url, {"version": 0, "status": "confirmed", "reason": ""}, format="json"
        ).status_code
        == 403
    )
    ProjectMember.objects.filter(user=reviewer).delete()
    assert client.get(url).status_code == 404
    other = Project.objects.create(owner=user, name="另一个诊断项目")
    client.force_authenticate(user)
    other_manuscript = client.put(path(other, "manuscript/"), payload(), format="json").data
    foreign = BlockVersion.objects.get(pk=other_manuscript["blocks"][0]["version_id"])
    for operation in [
        lambda: Job.objects.filter(pk=job.pk).update(project=other),
        lambda: ReviewFinding.objects.create(
            review=record, block_version=foreign, category="other", model_output={}
        ),
        lambda: ReviewRecord.objects.filter(pk=record.pk).update(summary="改写诊断"),
        lambda: ReviewFinding.objects.filter(pk=item.pk).update(model_output={}),
    ]:
        with pytest.raises(IntegrityError), transaction.atomic():
            operation()
    project.delete()
    assert not ReviewRecord.objects.exists()


def test_sdk_repairs_quote_within_call_budget(context, manuscript):
    output = finding_output(manuscript)
    invalid = copy.deepcopy(output)
    invalid["findings"][0]["quote"] = "材料原文不能作为稿件位置。"

    def respond(number, _):
        if number == 1:
            return [("read_manuscript", {})]
        return [("submit_review", invalid if number == 2 else output)]

    with provider(respond) as requests:
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        assert len(requests) == 3
        assert ReviewRecord.objects.get(job=job).findings.count() == 1
        assert job.ai_events.filter(
            kind="validation_error", details__code="review_quote_invalid"
        ).exists()
        assert "review_quote_invalid" in str(requests[2])


def test_sdk_invalid_quote_cannot_publish_or_exceed_budget(context, manuscript):
    output = finding_output(manuscript)
    output["findings"][0]["quote"] = "不存在的原稿。"
    with provider(respond_with(output)) as requests:
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "failed" and job.error_code == "model_call_limit"
        assert len(requests) == 4
        assert not ReviewRecord.objects.filter(job=job).exists()


def test_missing_submission_gets_one_protocol_repair_without_new_permissions(context, manuscript):
    output = finding_output(manuscript)

    def respond(number, _):
        if number == 1:
            return [("read_manuscript", {})]
        return [] if number == 2 else [("submit_review", output)]

    with provider(respond) as requests:
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        assert len(requests) == 3 and ReviewRecord.objects.filter(job=job).count() == 1
        assert (
            job.ai_events.filter(
                kind="validation_error", details__code="result_unsubmitted"
            ).count()
            == 1
        )


def test_repeated_missing_submission_stops_without_publishing(context, manuscript):
    with provider(lambda *_: []) as requests:
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "failed" and job.error_code == "result_invalid"
        assert len(requests) == 2
        assert not ReviewRecord.objects.exists()


def test_old_review_prompt_is_cancelled_before_model_request(context, manuscript):
    with provider(lambda *_: []) as requests:
        job = create_review(context, manuscript)
        job.input_snapshot["model"]["prompt_version"] = "review-v1"
        job.save(update_fields=["input_snapshot"])
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "cancelled", job.error_code
        assert requests == [] and not ReviewRecord.objects.exists()


def test_missing_submission_does_not_continue_after_policy_revocation(context, manuscript):
    def respond(number, _):
        if number == 1:
            return [("read_manuscript", {})]
        ProjectPolicy.objects.filter(project=context[1]).update(verified=False, allowed_actions=[])
        return []

    with provider(respond) as requests:
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "cancelled", job.error_code
        assert len(requests) == 2 and not ReviewRecord.objects.exists()


def test_occurrence_feedback_counts_within_block_and_requires_resubmission(context, manuscript):
    valid = finding_output(manuscript)
    invalid = copy.deepcopy(valid)
    invalid["findings"][0]["occurrence"] = 2

    def respond(number, body):
        if number == 1:
            return [("read_manuscript", {})]
        if number == 3:
            assert "只有 1 处" in str(body)
            assert "不是段落编号" in str(body)
            assert not ReviewRecord.objects.exists()
        return [("submit_review", invalid if number == 2 else valid)]

    with provider(respond) as requests:
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        assert len(requests) == 3
        assert ReviewRecord.objects.get(job=job).findings.count() == 1


def test_same_claim_and_basis_cannot_repeat_by_changing_category(context, manuscript, source):
    with provider(lambda *_: []):
        job = create_review(context, manuscript, [source])
        result = finding_output(manuscript, source)
        second = copy.deepcopy(result["findings"][0])
        second["category"] = "evidence_missing"
        result["findings"].append(second)
        ids = {str(chunk.pk) for chunk in source[1].chunks.all()}
        with pytest.raises(ParseFailure, match="review_duplicate_finding"):
            validate_review(job, copy.deepcopy(result), ids, True)
        # 同一位置有不同依据的独立问题仍可保留，不按文本位置一概合并。
        second["citations"] = []
        validated = validate_review(job, result, ids, True)
        assert len(validated["findings"]) == 2
        assert not ReviewRecord.objects.exists()


def test_related_manuscript_and_unicode_occurrence_without_material_tools(context):
    body = payload()
    body["blocks"][1]["text"] = "🧪三次重复。补记：三次重复。"
    body["blocks"].append({"id": str(uuid4()), "text": "上述实验仅一次重复。", "heading_level": 0})
    manuscript = save(context, body).data
    output = finding_output(manuscript)
    finding = output["findings"][0]
    finding.update(
        quote="三次重复。",
        occurrence=2,
        category="contradiction",
        support="contradicts",
        reason="同一实验的重复次数表述不一致。",
        related_blocks=[
            {
                "block_version_id": manuscript["blocks"][2]["version_id"],
                "quote": "上述实验仅一次重复。",
                "occurrence": 1,
            }
        ],
    )
    with provider(respond_with(output)) as requests:
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        result = ReviewRecord.objects.get(job=job).findings.get().model_output
        assert result["start"] == 9 and result["end"] == 14
        assert result["related_blocks"][0]["block_id"] == manuscript["blocks"][2]["id"]
        names = {tool["function"]["name"] for tool in requests[0]["tools"]}
        assert names == {"read_manuscript", "submit_review"}


def test_reversed_contradiction_is_rejected_but_can_be_merged(context, manuscript):
    output = finding_output(manuscript)
    first, second = manuscript["blocks"]
    finding = output["findings"][0]
    finding.update(
        category="contradiction",
        support="contradicts",
        related_blocks=[
            {
                "block_version_id": first["version_id"],
                "quote": first["text"],
                "occurrence": 1,
            }
        ],
    )
    reverse = copy.deepcopy(finding)
    reverse.update(finding["related_blocks"][0])
    reverse["related_blocks"] = [
        {
            "block_version_id": second["version_id"],
            "quote": finding["quote"],
            "occurrence": 1,
        }
    ]
    invalid = copy.deepcopy(output)
    invalid["findings"].append(reverse)

    def respond(number, body):
        if number == 1:
            return [("read_manuscript", {})]
        if number == 3:
            assert "不能交换主句" in str(body)
            assert not ReviewRecord.objects.exists()
        return [("submit_review", invalid if number == 2 else output)]

    with provider(respond) as requests:
        job = create_review(context, manuscript)
        execute_job(str(job.pk))
        job.refresh_from_db()
        assert job.status == "succeeded", job.error_code
        assert len(requests) == 3 and ReviewRecord.objects.get(job=job).findings.count() == 1


def test_number_feedback_requires_explicit_evidence_not_just_reading(context, manuscript, source):
    output = finding_output(manuscript, source)
    output["findings"][0]["reason"] = "现有引文没有记录 987654 次重复。"
    with provider(lambda *_: []):
        job = create_review(context, manuscript, [source])
        ids = {str(chunk.pk) for chunk in source[1].chunks.all()}
        with pytest.raises(ParseFailure, match="review_number_mismatch") as error:
            validate_review(job, output, ids, True)
        assert "987654" in error.value.message and "chunk_id" in error.value.message
        assert not ReviewRecord.objects.exists()
