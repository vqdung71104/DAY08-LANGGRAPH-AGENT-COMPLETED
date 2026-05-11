"""Tests for metrics schema and helpers."""
from langgraph_agent_lab.metrics import metric_from_state, summarize_metrics
from langgraph_agent_lab.state import make_event


def test_metric_from_state_success():
    state = {
        "scenario_id": "S",
        "route": "simple",
        "final_answer": "ok",
        "events": [make_event("intake", "completed", "ok"), make_event("answer", "completed", "ok")],
        "errors": [],
    }
    metric = metric_from_state(state, expected_route="simple", approval_required=False)
    assert metric.success is True
    assert metric.nodes_visited == 2
    assert metric.retry_count == 0


def test_metric_requires_approval():
    state = {
        "scenario_id": "S",
        "route": "risky",
        "final_answer": "done",
        "approval": {"approved": True},
        "events": [make_event("approval", "completed", "ok")],
        "errors": [],
    }
    metric = metric_from_state(state, expected_route="risky", approval_required=True)
    assert metric.success is True
    assert metric.approval_observed is True
    assert metric.interrupt_count == 1


def test_metric_missing_approval_fails():
    state = {
        "scenario_id": "S",
        "route": "risky",
        "final_answer": "done",
        "approval": None,
        "events": [],
        "errors": [],
    }
    metric = metric_from_state(state, expected_route="risky", approval_required=True)
    assert metric.success is False


def test_metric_wrong_route_fails():
    state = {
        "scenario_id": "S",
        "route": "tool",
        "final_answer": "ok",
        "events": [],
        "errors": [],
    }
    metric = metric_from_state(state, expected_route="simple", approval_required=False)
    assert metric.success is False


def test_summarize_metrics():
    m1 = metric_from_state({"scenario_id": "1", "route": "simple", "final_answer": "ok", "events": [], "errors": []}, "simple", False)
    m2 = metric_from_state({"scenario_id": "2", "route": "tool", "final_answer": None, "events": [], "errors": []}, "tool", False)
    report = summarize_metrics([m1, m2])
    assert report.total_scenarios == 2
    assert 0 <= report.success_rate <= 1
    assert report.total_retries == 0


def test_summarize_metrics_empty():
    import pytest
    with pytest.raises(ValueError):
        summarize_metrics([])


def test_metric_retry_count():
    state = {
        "scenario_id": "S",
        "route": "error",
        "final_answer": "done",
        "events": [
            make_event("retry", "completed", "1"),
            make_event("retry", "completed", "2"),
        ],
        "errors": ["e1", "e2"],
    }
    metric = metric_from_state(state, expected_route="error", approval_required=False)
    assert metric.retry_count == 2
