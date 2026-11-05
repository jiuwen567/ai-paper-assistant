"""评分约束是软件测试；受控响应不计为真实模型效果。"""

from copy import deepcopy
from unittest.mock import patch

import pytest

from core.tests.evaluation_cases import catalog
from core.tests.evaluation_direct import execute, local_endpoint, prompt
from core.tests.evaluation_metrics import review_template, score, usage_total


def sample():
    run = {
        "status": "completed",
        "suite": {"cases": [{"id": "a", "purpose": "review", "targets": [{"id": "one"}]}]},
        "records": [
            {
                "id": "a/system",
                "case": "a",
                "arm": "system",
                "status": "succeeded",
                "items": [{"id": "1"}, {"id": "2"}],
            },
            {"id": "a/direct", "case": "a", "arm": "direct", "status": "failed", "items": []},
        ],
    }
    review = review_template(run)
    review.update(review_type="assistant_draft", reviewer="测试草案", gold_confirmed=True)
    for row in review["records"]:
        row["control_checked"] = True
        for item in row["items"]:
            item.update(verdict="correct", target="one", reason="测试指定同一目标")
    return run, review


def test_duplicate_does_not_inflate_score_and_failure_is_not_empty_success():
    run, review = sample()
    result = score(run, review)
    assert result["provisional"]
    a, b = result["records"]
    assert (a["tp"], a["fp"], a["fn"]) == (1, 1, 0)
    assert (b["tp"], b["fp"], b["fn"], b["status"]) == (0, 0, 1, "failed")
    assert all(row["review_seconds"] is None for row in result["records"])


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(run_digest="changed"),
        lambda r: r.update(review_type="pending"),
        lambda r: r.update(gold_confirmed=False),
        lambda r: r["records"].pop(),
        lambda r: r["records"][0]["items"].pop(),
        lambda r: r["records"][0].update(control_checked=False),
        lambda r: r["records"][0].update(review_seconds=1),
        lambda r: r["records"][0]["items"][0].update(target="unknown"),
    ],
)
def test_incomplete_or_mismatched_judgments_are_rejected(change):
    run, review = sample()
    change(review)
    with pytest.raises(ValueError):
        score(run, review)


def test_human_metrics_remain_unknown_unless_recorded():
    run, review = sample()
    review["review_type"] = "human"
    review["records"][0].update(review_seconds=12.5, human_operations=3)
    scored = score(run, review)
    assert not scored["provisional"]
    assert scored["records"][0]["review_seconds"] == 12.5
    assert scored["records"][1]["human_operations"] is None
    review["records"][0]["human_operations"] = True
    with pytest.raises(ValueError):
        score(run, review)


def test_unknown_usage_is_not_reported_as_zero():
    assert usage_total([{"usage": None}])["input"] is None
    assert usage_total([])["input"] == 0
    assert usage_total([{"usage": {"input": 2}}, {"usage": {"input": 3}}])["input"] == 5


def test_fixed_catalog_and_direct_prompt_do_not_leak_gold():
    suite = catalog()
    assert len(suite["cases"]) == len({c["id"] for c in suite["cases"]}) == 14
    for case in suite["cases"]:
        modified = deepcopy(case)
        modified["targets"] = [{"id": "NEVER_SEND_GOLD"}]
        modified["control_requirement"] = "NEVER_SEND_GOLD"
        assert "NEVER_SEND_GOLD" not in prompt(modified)
    assert suite["annotation_status"] == "assistant_draft_pending_human_review"


@pytest.mark.parametrize(
    "url",
    [
        "https://external.test/v1",
        "http://localhost/v1?key=secret",
        "http://user:secret@localhost/v1",
        "http://localhost/other",
    ],
)
def test_direct_rejects_nonlocal_or_credential_urls(url):
    with pytest.raises(ValueError):
        local_endpoint(url)


def test_direct_retains_raw_protocol_failure_without_counting_it_as_output():
    response = {
        "choices": [{"message": {"content": "not-json"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
    }
    with patch("core.tests.evaluation_direct.fetch_json", return_value=response):
        result = execute(catalog()["cases"][0], "http://127.0.0.1:11434/v1", "fixture")
    assert result["status"] == "failed" and result["items"] == []
    assert result["raw"] == "not-json" and result["usage"]["total_input"] == 10
    assert result["usage"]["cache_read"] is None


def test_system_reading_normalization_uses_fixed_source_mapping():
    from core.tests.evaluate_core import normalize

    case = catalog()["cases"][0]
    report = {
        "status": "succeeded",
        "error_code": "",
        "calls": [],
        "elapsed_seconds": 1,
        "model": "fixture",
        "selected_sources": {"random-id": "source-1"},
        "result": {
            "documents": [
                {
                    "version_id": "random-id",
                    "fields": {
                        "subject": {"status": "reported", "text": "自制对象", "citations": []}
                    },
                }
            ],
            "comparison": None,
        },
    }
    output = normalize(case, report)
    assert output["items"][0]["id"] == "source-1:subject"
    report["status"] = "failed"
    assert normalize(case, report)["items"] == []


def test_interrupted_run_cannot_be_scored_even_with_complete_judgments():
    run, review = sample()
    run["status"] = "interrupted"
    with pytest.raises(ValueError, match="整轮评测"):
        score(run, review)


def test_review_html_escapes_model_text_and_uses_text_nodes():
    from core.tests.evaluation_review import render

    run, _ = sample()
    run["records"][0]["items"][0]["content"] = "</script><script>window.attacked=true</script>"
    html = render(run)
    assert "<script>window.attacked=true" not in html
    assert "\\u003c/script>" in html
    assert "node.textContent=text" in html and "innerHTML" not in html


def test_direct_instructions_are_specific_to_purpose():
    cases = {case["id"]: case for case in catalog()["cases"]}
    assert "六项" in prompt(cases["reading/single"])
    assert "六项" not in prompt(cases["expression/concise"])
    assert "仅提取待办" in prompt(cases["feedback/compound"])
