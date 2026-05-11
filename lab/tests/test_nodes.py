"""Tests for individual node functions."""
from langgraph_agent_lab.nodes import (
    answer_node,
    ask_clarification_node,
    classify_node,
    dead_letter_node,
    evaluate_node,
    finalize_node,
    intake_node,
    retry_or_fallback_node,
    risky_action_node,
    tool_node,
)
from langgraph_agent_lab.state import Route


def base_state(**kwargs):
    return {"query": "test", "normalized_query": "test", "route": "simple",
            "risk_level": "low", "attempt": 0, "max_attempts": 3,
            "scenario_id": "S01", "thread_id": "thread-S01",
            "final_answer": None, "pending_question": None, "proposed_action": None,
            "approval": None, "evaluation_result": None, "tool_call_id": None,
            "messages": [], "tool_results": [], "errors": [], "events": [], **kwargs}


def test_intake_normalizes_query():
    state = base_state(query="  Hello World  ")
    result = intake_node(state)
    assert result["query"] == "Hello World"
    assert result["normalized_query"] == "hello world"


def test_intake_redacts_pii():
    state = base_state(query="user@example.com needs help")
    result = intake_node(state)
    assert "[REDACTED]" in result["normalized_query"]
    assert "user@example.com" not in result["normalized_query"]


def test_intake_emits_event():
    result = intake_node(base_state())
    assert len(result["events"]) == 1
    assert result["events"][0]["node"] == "intake"


def test_classify_simple():
    result = classify_node(base_state(normalized_query="how do i reset my password"))
    assert result["route"] == Route.SIMPLE.value


def test_classify_tool():
    result = classify_node(base_state(normalized_query="please lookup order status for order 123"))
    assert result["route"] == Route.TOOL.value


def test_classify_risky():
    result = classify_node(base_state(normalized_query="refund this customer"))
    assert result["route"] == Route.RISKY.value
    assert result["risk_level"] == "high"


def test_classify_missing_info():
    result = classify_node(base_state(normalized_query="can you fix it"))
    assert result["route"] == Route.MISSING_INFO.value


def test_classify_error():
    result = classify_node(base_state(normalized_query="timeout failure while processing"))
    assert result["route"] == Route.ERROR.value


def test_tool_node_success():
    state = base_state(route=Route.TOOL.value, attempt=2)
    result = tool_node(state)
    assert len(result["tool_results"]) == 1
    assert "SUCCESS" in result["tool_results"][0]


def test_tool_node_error_at_low_attempt():
    state = base_state(route=Route.ERROR.value, attempt=0)
    result = tool_node(state)
    assert "ERROR" in result["tool_results"][0]


def test_tool_node_idempotency_key():
    state = base_state(route=Route.TOOL.value, attempt=1)
    r1 = tool_node(state)
    r2 = tool_node(state)
    assert r1["tool_call_id"] == r2["tool_call_id"]


def test_evaluate_success():
    state = base_state(tool_results=["SUCCESS: result"])
    result = evaluate_node(state)
    assert result["evaluation_result"] == "success"


def test_evaluate_needs_retry():
    state = base_state(tool_results=["ERROR: transient failure"])
    result = evaluate_node(state)
    assert result["evaluation_result"] == "needs_retry"


def test_answer_node_with_tool_results():
    state = base_state(tool_results=["SUCCESS: order found"])
    result = answer_node(state)
    assert result["final_answer"] is not None
    assert "order found" in result["final_answer"]


def test_answer_node_fallback():
    state = base_state(query="how do I reset my password?")
    result = answer_node(state)
    assert result["final_answer"] is not None
    assert len(result["final_answer"]) > 10


def test_clarify_generates_question():
    state = base_state(query="Can you fix it?")
    result = ask_clarification_node(state)
    assert result["pending_question"] is not None
    assert result["final_answer"] == result["pending_question"]
    assert len(result["pending_question"]) > 20


def test_risky_action_prepares_proposal():
    state = base_state(query="refund customer", risk_level="high")
    result = risky_action_node(state)
    assert result["proposed_action"] is not None
    assert "refund" in result["proposed_action"].lower() or "ACTION" in result["proposed_action"]


def test_retry_increments_attempt():
    state = base_state(attempt=0)
    result = retry_or_fallback_node(state)
    assert result["attempt"] == 1
    assert len(result["errors"]) == 1


def test_retry_backoff_grows():
    r1 = retry_or_fallback_node(base_state(attempt=0))
    r2 = retry_or_fallback_node(base_state(attempt=1))
    boff1 = r1["events"][0]["metadata"]["backoff_ms"]
    boff2 = r2["events"][0]["metadata"]["backoff_ms"]
    assert boff2 > boff1


def test_dead_letter_produces_answer():
    state = base_state(attempt=3, errors=["e1", "e2"])
    result = dead_letter_node(state)
    assert result["final_answer"] is not None
    assert "3" in result["final_answer"]


def test_finalize_emits_event():
    result = finalize_node(base_state(route=Route.SIMPLE.value, final_answer="done"))
    assert len(result["events"]) == 1
    assert result["events"][0]["node"] == "finalize"
