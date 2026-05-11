"""Tests for routing functions."""
from langgraph_agent_lab.routing import route_after_approval, route_after_classify, route_after_evaluate, route_after_retry
from langgraph_agent_lab.state import Route


def test_route_after_classify_all_routes():
    assert route_after_classify({"route": Route.SIMPLE.value}) == "answer"
    assert route_after_classify({"route": Route.TOOL.value}) == "tool"
    assert route_after_classify({"route": Route.RISKY.value}) == "risky_action"
    assert route_after_classify({"route": Route.MISSING_INFO.value}) == "clarify"
    assert route_after_classify({"route": Route.ERROR.value}) == "retry"


def test_route_after_classify_unknown_falls_back():
    assert route_after_classify({"route": "unknown_route"}) == "answer"
    assert route_after_classify({}) == "answer"


def test_route_after_approval_approved():
    assert route_after_approval({"approval": {"approved": True}}) == "tool"


def test_route_after_approval_rejected():
    assert route_after_approval({"approval": {"approved": False}}) == "clarify"


def test_route_after_approval_missing():
    assert route_after_approval({"approval": None}) == "clarify"
    assert route_after_approval({}) == "clarify"


def test_route_after_retry_under_limit():
    assert route_after_retry({"attempt": 0, "max_attempts": 3}) == "tool"
    assert route_after_retry({"attempt": 1, "max_attempts": 3}) == "tool"
    assert route_after_retry({"attempt": 2, "max_attempts": 3}) == "tool"


def test_route_after_retry_at_limit():
    assert route_after_retry({"attempt": 3, "max_attempts": 3}) == "dead_letter"
    assert route_after_retry({"attempt": 5, "max_attempts": 3}) == "dead_letter"


def test_route_after_retry_max_one():
    """S07 scenario: max_attempts=1 -> dead_letter after first retry."""
    assert route_after_retry({"attempt": 1, "max_attempts": 1}) == "dead_letter"


def test_route_after_evaluate_success():
    assert route_after_evaluate({"evaluation_result": "success"}) == "answer"


def test_route_after_evaluate_needs_retry():
    assert route_after_evaluate({"evaluation_result": "needs_retry"}) == "retry"


def test_route_after_evaluate_missing():
    assert route_after_evaluate({}) == "answer"
