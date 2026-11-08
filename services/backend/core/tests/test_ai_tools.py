"""工具处理拆出后仍限制调用顺序、范围和结果提交。"""

from types import SimpleNamespace

import pytest

from core.ai.tools import handle_tool, validate_arguments
from core.common.errors import ParseFailure


def run_state(**overrides):
    return SimpleNamespace(call=None, calls=1, tools=0, **overrides)


@pytest.mark.parametrize(
    "purpose,name", [("feedback", "read_evidence"), ("impact", "project_search")]
)
def test_specialized_tasks_cannot_expand_tool_scope(purpose, name):
    job = SimpleNamespace(input_snapshot={"purpose": purpose})
    with pytest.raises(ParseFailure) as error:
        handle_tool(run_state(), job, {"name": name, "args": {}})
    assert error.value.code == "tool_denied"


def test_tools_require_a_completed_model_call():
    run = run_state()
    run.calls = 0
    with pytest.raises(ParseFailure) as error:
        handle_tool(run, SimpleNamespace(input_snapshot={"purpose": "reading"}), {})
    assert error.value.code == "tool_call_limit"


def test_feedback_rejection_remains_recoverable_without_staging(monkeypatch):
    from core.feedback import service

    def reject(*args):
        raise ParseFailure("feedback_quote_invalid", "自制引文不匹配。")

    monkeypatch.setattr(service, "validate_split", reject)
    events = []
    job = SimpleNamespace(
        input_snapshot={"purpose": "feedback"},
        ai_events=SimpleNamespace(create=lambda **event: events.append(event)),
    )
    run = run_state(feedback=None, feedback_read=True, generation=1)
    details, result = handle_tool(run, job, {"name": "submit_feedback", "args": {}})
    assert details is None
    assert result["status"] == "rejected"
    assert run.feedback is None
    assert events[0]["kind"] == "validation_error"


def test_unknown_tools_are_rejected():
    with pytest.raises(ParseFailure) as error:
        validate_arguments("shell", {"command": "forbidden"})
    assert error.value.code == "tool_denied"
