"""Node implementations for the LangGraph workflow.

Each function is small, testable, and returns a partial state update.
Input state is never mutated in place.
"""

from __future__ import annotations

import hashlib
import re

from .state import AgentState, ApprovalDecision, Route, make_event

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PII_PATTERN = re.compile(r"\b\d{13,16}\b|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")


def _redact_pii(text: str) -> str:
    """Replace obvious PII (emails, long card numbers) with [REDACTED]."""
    return _PII_PATTERN.sub("[REDACTED]", text)


def _tool_idempotency_key(scenario_id: str, attempt: int) -> str:
    """Generate a stable idempotency key for tool calls."""
    return hashlib.sha1(f"{scenario_id}:{attempt}".encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def intake_node(state: AgentState) -> dict:
    """Normalize raw query: strip whitespace, redact PII, extract metadata."""
    raw = state.get("query", "")
    normalized = _redact_pii(raw.strip().lower())
    return {
        "query": raw.strip(),
        "normalized_query": normalized,
        "messages": [f"intake:{raw[:60]}"],
        "events": [make_event("intake", "completed", "query normalized and PII-checked")],
    }


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using keyword-based policy.

    Routing policy (priority order):
    1. RISKY  – destructive/financial keywords: refund, delete, send, cancel, override
    2. TOOL   – lookup keywords: status, order, lookup, search, find, get, check
    3. MISSING_INFO – very short queries with vague pronouns (it, this, that) and < 5 tokens
    4. ERROR  – transient-failure simulation keywords: timeout, fail, error, crash
    5. SIMPLE – everything else (FAQ, how-to, definitions)
    """
    query = state.get("normalized_query") or state.get("query", "")
    q = query.lower()
    tokens = [w.strip("?!.,;:") for w in q.split()]

    route = Route.SIMPLE
    risk_level = "low"

    # Priority 1: destructive/financial – highest risk
    risky_kw = {"refund", "delete", "send", "cancel", "override", "remove", "wipe", "drop"}
    if risky_kw.intersection(tokens):
        route = Route.RISKY
        risk_level = "high"

    # Priority 2: tool lookup
    elif {"status", "order", "lookup", "search", "find", "get", "check", "list", "fetch"}.intersection(tokens):
        route = Route.TOOL
        risk_level = "low"

    # Priority 3: missing context
    elif len(tokens) < 5 and {"it", "this", "that", "them", "these"}.intersection(tokens):
        route = Route.MISSING_INFO

    # Priority 4: transient error simulation
    elif {"timeout", "fail", "failure", "error", "crash", "retry", "cannot", "recover"}.intersection(tokens):
        route = Route.ERROR
        risk_level = "medium"

    return {
        "route": route.value,
        "risk_level": risk_level,
        "events": [make_event("classify", "completed", f"route={route.value} risk={risk_level}")],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Generate a specific clarification question based on missing context."""
    query = state.get("query", "")
    # Produce a context-aware clarification question
    question = (
        f"I need more information to help with your request. "
        f"Could you please specify: (1) the exact subject or item you are referring to in '{query}', "
        f"(2) the order ID, account number, or reference if applicable, and "
        f"(3) the desired outcome? This will help me route your request correctly."
    )
    return {
        "pending_question": question,
        "final_answer": question,
        "events": [make_event("clarify", "completed", "clarification question generated")],
    }


def tool_node(state: AgentState) -> dict:
    """Execute a mock tool call with idempotency key.

    Simulates transient failures for error-route scenarios to test retry loops.
    The idempotency key ensures that re-runs on the same attempt produce the same result.
    """
    attempt = int(state.get("attempt", 0))
    scenario_id = state.get("scenario_id", "unknown")
    idem_key = _tool_idempotency_key(scenario_id, attempt)

    if state.get("route") == Route.ERROR.value and attempt < 2:
        result = (
            f"ERROR: transient failure "
            f"attempt={attempt} scenario={scenario_id} idempotency_key={idem_key}"
        )
    elif state.get("route") == Route.RISKY.value:
        # After approval, execute the risky action
        proposed = state.get("proposed_action", "action")
        result = (
            f"EXECUTED: risky-action approved: '{proposed}' "
            f"scenario={scenario_id} idempotency_key={idem_key}"
        )
    else:
        result = (
            f"SUCCESS: tool-result for scenario={scenario_id} "
            f"attempt={attempt} idempotency_key={idem_key}"
        )

    return {
        "tool_call_id": idem_key,
        "tool_results": [result],
        "events": [make_event("tool", "completed", f"tool executed attempt={attempt}", idempotency_key=idem_key)],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action with evidence summary and risk justification for approval."""
    query = state.get("query", "")
    risk_level = state.get("risk_level", "high")
    proposed = (
        f"ACTION: '{query}' | "
        f"risk={risk_level} | "
        f"thread={state.get('thread_id', 'unknown')} | "
        f"requires human approval before execution"
    )
    return {
        "proposed_action": proposed,
        "events": [make_event("risky_action", "pending_approval", "proposed action prepared", risk=risk_level)],
    }


def approval_node(state: AgentState) -> dict:
    """Human-in-the-loop approval step.

    In production: set LANGGRAPH_INTERRUPT=true to suspend execution and wait for a human.
    In test/CI: mock approval runs synchronously so the graph completes without infrastructure.

    Supports reject decision: if approved=False, the graph routes to clarify.
    """
    import os

    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        value = interrupt({
            "proposed_action": state.get("proposed_action"),
            "risk_level": state.get("risk_level"),
            "thread_id": state.get("thread_id"),
        })
        if isinstance(value, dict):
            decision = ApprovalDecision(**value)
        else:
            decision = ApprovalDecision(approved=bool(value))
    else:
        # Mock: auto-approve for lab grading; reject can be simulated via env
        force_reject = os.getenv("MOCK_APPROVAL_REJECT", "").lower() == "true"
        decision = ApprovalDecision(
            approved=not force_reject,
            reviewer="mock-reviewer",
            comment="auto-approved for lab demo" if not force_reject else "auto-rejected for testing",
        )

    return {
        "approval": decision.model_dump(),
        "events": [
            make_event(
                "approval",
                "completed",
                f"approved={decision.approved} reviewer={decision.reviewer}",
                approved=decision.approved,
            )
        ],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Increment attempt counter with bounded retry and exponential-backoff metadata.

    The actual sleep is not performed here (nodes are synchronous); backoff_ms is
    recorded for observability so the caller can implement it if needed.
    """
    attempt = int(state.get("attempt", 0)) + 1
    max_attempts = int(state.get("max_attempts", 3))
    backoff_ms = min(100 * (2 ** (attempt - 1)), 5000)  # cap at 5 s
    error_msg = f"transient failure attempt={attempt} of {max_attempts} backoff_ms={backoff_ms}"
    return {
        "attempt": attempt,
        "errors": [error_msg],
        "events": [
            make_event(
                "retry",
                "completed",
                f"retry attempt={attempt}/{max_attempts}",
                attempt=attempt,
                max_attempts=max_attempts,
                backoff_ms=backoff_ms,
            )
        ],
    }


def answer_node(state: AgentState) -> dict:
    """Produce a final grounded response.

    Grounds the answer in tool_results when available; references approval for risky routes.
    """
    tool_results = state.get("tool_results") or []
    approval = state.get("approval")
    route = state.get("route", "")

    if tool_results and route == Route.RISKY.value and approval:
        last_result = tool_results[-1]
        reviewer = approval.get("reviewer", "unknown")
        answer = (
            f"Request completed. Action executed after approval by '{reviewer}'. "
            f"Result: {last_result}"
        )
    elif tool_results:
        last_result = tool_results[-1]
        answer = f"Here is the information you requested: {last_result}"
    else:
        query = state.get("query", "")
        answer = (
            f"Thank you for your question: '{query}'. "
            f"Based on our knowledge base, I can assist you with this. "
            f"Please refer to our documentation or contact support for step-by-step guidance."
        )

    return {
        "final_answer": answer,
        "events": [make_event("answer", "completed", f"answer generated route={route}")],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the 'done?' check that enables retry loops.

    Checks for ERROR sentinel in the tool result. In production this would use
    an LLM-as-judge or structured validation against a schema.
    """
    tool_results = state.get("tool_results") or []
    latest = tool_results[-1] if tool_results else ""

    if "ERROR" in latest:
        verdict = "needs_retry"
        msg = f"tool result indicates failure: '{latest[:80]}'"
    else:
        verdict = "success"
        msg = f"tool result satisfactory: '{latest[:80]}'"

    return {
        "evaluation_result": verdict,
        "events": [make_event("evaluate", "completed", msg, verdict=verdict)],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Log unresolvable failures to dead-letter queue.

    In production: persist to DLQ, create a support ticket, and page on-call.
    Here we record the failure with full context for audit.
    """
    attempt = int(state.get("attempt", 0))
    errors = state.get("errors") or []
    scenario_id = state.get("scenario_id", "unknown")
    summary = "; ".join(errors[-3:]) if errors else "no error details"

    answer = (
        f"Your request (scenario={scenario_id}) could not be completed after "
        f"{attempt} retry attempts. "
        f"Error summary: {summary}. "
        f"A support ticket has been created and our team will follow up within 24 hours."
    )

    return {
        "final_answer": answer,
        "route": Route.DEAD_LETTER.value,
        "events": [
            make_event(
                "dead_letter",
                "completed",
                f"max retries exceeded attempt={attempt}",
                scenario_id=scenario_id,
                error_count=len(errors),
            )
        ],
    }


def finalize_node(state: AgentState) -> dict:
    """Finalize the run: emit terminal audit event and mark route as done if not dead_letter."""
    route = state.get("route", "unknown")
    final_answer = state.get("final_answer") or state.get("pending_question", "")
    nodes_visited = len(state.get("events", []))
    return {
        "events": [
            make_event(
                "finalize",
                "completed",
                "workflow finished",
                route=route,
                nodes_visited=nodes_visited,
                has_answer=bool(final_answer),
            )
        ]
    }
