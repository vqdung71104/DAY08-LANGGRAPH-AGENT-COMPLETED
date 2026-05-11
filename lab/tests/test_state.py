"""Tests for state schema and helpers."""
from langgraph_agent_lab.scenarios import load_scenarios
from langgraph_agent_lab.state import Route, Scenario, initial_state, make_event


def test_scenario_validation():
    scenario = Scenario(id="x", query="hello", expected_route=Route.SIMPLE)
    state = initial_state(scenario)
    assert state["thread_id"] == "thread-x"
    assert state["attempt"] == 0
    assert state["events"] == []
    assert state["errors"] == []
    assert state["tool_results"] == []


def test_scenario_query_must_not_be_empty():
    import pytest
    with pytest.raises(Exception):
        Scenario(id="bad", query="   ", expected_route=Route.SIMPLE)


def test_initial_state_all_fields():
    s = Scenario(id="t1", query="test query", expected_route=Route.TOOL, max_attempts=5)
    state = initial_state(s)
    assert state["max_attempts"] == 5
    assert state["route"] == ""
    assert state["final_answer"] is None
    assert state["approval"] is None
    assert state["resume_from_checkpoint"] is False


def test_load_scenarios():
    scenarios = load_scenarios("data/sample/scenarios.jsonl")
    assert len(scenarios) >= 6
    routes = {s.expected_route for s in scenarios}
    assert Route.SIMPLE in routes
    assert Route.TOOL in routes
    assert Route.RISKY in routes


def test_make_event_structure():
    ev = make_event("intake", "completed", "test message", key="value")
    assert ev["node"] == "intake"
    assert ev["event_type"] == "completed"
    assert ev["message"] == "test message"
    assert ev["metadata"]["key"] == "value"
    assert "timestamp" in ev


def test_route_enum_values():
    assert Route.SIMPLE == "simple"
    assert Route.TOOL == "tool"
    assert Route.MISSING_INFO == "missing_info"
    assert Route.RISKY == "risky"
    assert Route.ERROR == "error"
