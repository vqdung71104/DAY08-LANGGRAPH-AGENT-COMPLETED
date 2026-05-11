# Day 08 Lab Report — LangGraph Production Agent

## 1. Student Information

- **Name:** VinUniversity AICB Student
- **Lab:** Phase 2 / Track 3 / Day 8 — LangGraph Agent Orchestration
- **Date:** 2026-05-11
- **Repo:** phase2-track3-day8-langgraph-agent

---

## 2. Architecture Overview

### Graph Nodes

The agent is composed of **11 nodes** wired in a directed graph with conditional edges:

```
START → intake → classify → [answer | tool | clarify | risky_action | retry]
                                ↓           ↓              ↓
                            finalize    evaluate      approval
                                         ↓  ↓           ↓  ↓
                                       retry answer   tool clarify
                                         ↓
                                      dead_letter
                                         ↓
                                      finalize → END
```

| Node | Responsibility |
|---|---|
| `intake` | Normalize query, redact PII, extract metadata |
| `classify` | Keyword-based routing policy → route field |
| `answer` | Ground final response in tool_results / approval |
| `tool` | Idempotent mock tool call with transient-failure simulation |
| `evaluate` | "Done?" check — inspects tool result for ERROR sentinel |
| `clarify` | Generate context-aware clarification question |
| `risky_action` | Build proposed-action payload with risk justification |
| `approval` | HITL gate: real `interrupt()` or mock-approval via env flag |
| `retry` | Increment attempt, record backoff_ms for observability |
| `dead_letter` | Log unresolvable failures; in prod would page on-call |
| `finalize` | Terminal audit event with node count and answer presence |

### Conditional Routing

- `route_after_classify`: maps route enum → node name; falls back to `answer`
- `route_after_evaluate`: `needs_retry` → retry, else → answer
- `route_after_approval`: `approved=True` → tool, `approved=False` → clarify
- `route_after_retry`: `attempt >= max_attempts` → dead_letter, else → tool

---

## 3. State Schema

| Field | Type | Reducer | Purpose |
|---|---|---|---|
| `thread_id` | str | overwrite | LangGraph checkpoint key |
| `scenario_id` | str | overwrite | grading identity |
| `query` | str | overwrite | raw user query |
| `normalized_query` | str | overwrite | PII-redacted, lowercased |
| `route` | str | overwrite | current route (Route enum value) |
| `risk_level` | str | overwrite | low / medium / high |
| `attempt` | int | overwrite | current retry count |
| `max_attempts` | int | overwrite | retry cap (per scenario) |
| `final_answer` | str | overwrite | agent response |
| `pending_question` | str | overwrite | clarification question |
| `proposed_action` | str | overwrite | risky action description |
| `approval` | dict | overwrite | ApprovalDecision dump |
| `evaluation_result` | str | overwrite | success / needs_retry |
| `tool_call_id` | str | overwrite | idempotency key |
| `resume_from_checkpoint` | bool | overwrite | crash-resume flag |
| `messages` | list[str] | **append** | intake log |
| `tool_results` | list[str] | **append** | all tool call results |
| `errors` | list[str] | **append** | all error messages |
| `events` | list[dict] | **append** | full audit trail |

**Append-only fields** use `Annotated[list, add]` so LangGraph merges them across parallel branches and checkpoints without losing history.

---

## 4. Scenario Results

| Scenario | Expected Route | Actual Route | Success | Retries | Interrupts | Nodes |
|---|---|---|:---:|---:|---:|---:|
| G01_simple | simple | simple | ✅ | 0 | 0 | 4 |
| G02_simple2 | simple | simple | ✅ | 0 | 0 | 4 |
| G03_tool | tool | tool | ✅ | 0 | 0 | 6 |
| G04_tool2 | tool | tool | ✅ | 0 | 0 | 6 |
| G05_tool3 | tool | tool | ✅ | 0 | 0 | 6 |
| G06_missing | missing_info | missing_info | ✅ | 0 | 0 | 4 |
| G07_missing2 | missing_info | missing_info | ✅ | 0 | 0 | 4 |
| G08_risky | risky | risky | ✅ | 0 | 1 | 8 |
| G09_risky2 | risky | risky | ✅ | 0 | 1 | 8 |
| G10_risky3 | risky | simple | ❌ | 0 | 0 | 4 |
| G11_risky4 | risky | risky | ✅ | 0 | 1 | 8 |
| G12_error | error | simple | ❌ | 0 | 0 | 4 |
| G13_error2 | error | error | ✅ | 2 | 0 | 10 |
| G14_dead | error | dead_letter | ❌ | 1 | 0 | 5 |
| G15_mixed | risky | risky | ✅ | 0 | 1 | 8 |

### Summary

| Metric | Value |
|---|---|
| Total scenarios | 15 |
| **Success rate** | **80.0%** |
| Avg nodes visited | 5.9 |
| Total retries | 3 |
| Total interrupts (HITL) | 4 |
| Resume success | mock ✅ |


### Failed scenarios

- **G10_risky3**: expected `risky`, got `simple` — No error details
- **G12_error**: expected `error`, got `simple` — No error details
- **G14_dead**: expected `error`, got `dead_letter` — transient failure attempt=1 of 1 backoff_ms=100


---

## 5. Failure Analysis

### 5.1 Transient Tool Failure (retry loop)

**Scenario:** `S05_error` / `S07_dead_letter` — queries containing timeout/fail keywords route to ERROR.

**Behavior:**
1. `classify` → route=error → `retry` node increments attempt
2. `retry` → `tool` (attempt=0,1) → returns `ERROR: transient failure`
3. `evaluate` → `needs_retry` → back to `retry` (loop)
4. When `attempt >= max_attempts` → `dead_letter` node captures the failure

**Bounded by:** `max_attempts` field (default 3; S07 sets `max_attempts=1` to test immediate dead-letter).

**Production fix:** Add exponential backoff (`backoff_ms` is already recorded in event metadata), circuit breaker, and DLQ persistence.

### 5.2 Risky Action Without Approval

**Scenario:** `S04_risky` / `S06_delete` — queries with destructive keywords (refund, delete).

**Behavior:**
1. `classify` → route=risky
2. `risky_action` → builds proposed_action with risk justification
3. `approval` → HITL gate (mock: auto-approved; real: `interrupt()` suspends graph)
4. If `approved=False` → `clarify` (no action taken, user informed)
5. If `approved=True` → `tool` executes with idempotency key

**Risk mitigation:** Setting `MOCK_APPROVAL_REJECT=true` tests the rejection path. Real production would use LangGraph interrupt with a web UI review form.

### 5.3 Missing Context / Ambiguous Query

**Scenario:** `S03_missing` — short queries with vague pronouns route to MISSING_INFO.

**Behavior:** `clarify` node generates a structured question naming the specific missing fields (subject, order ID, desired outcome). No hallucination occurs.

---

## 6. Persistence & Recovery

### Checkpointer

The lab uses `MemorySaver` by default (no infrastructure). For crash-resume:

```python
checkpointer = build_checkpointer("sqlite", "lab_checkpoints.db")
graph = build_graph(checkpointer=checkpointer)

# Run 1 — may crash mid-graph
graph.invoke(state, config={"configurable": {"thread_id": "thread-S01_simple"}})

# Run 2 — same thread_id resumes from last checkpoint automatically
graph.invoke(state, config={"configurable": {"thread_id": "thread-S01_simple"}})
```

### Time-Travel Debug

```python
from langgraph_agent_lab.persistence import get_thread_history
history = get_thread_history(graph, "thread-S01_simple")
# history[0] is the most recent; history[-1] is initial state
```

### Thread ID Convention

Each scenario gets `thread_id = f"thread-{scenario.id}"`. This enables:
- Per-scenario replay without cross-contamination
- Independent state histories in a shared checkpointer

---

## 7. Extension Work

### Completed

- **Idempotency keys** for tool calls (`hashlib.sha1(scenario_id:attempt)`)
- **PII redaction** in `intake_node` (regex for emails and card numbers)
- **Exponential backoff metadata** recorded in retry events (`backoff_ms`)
- **Rejection path** in approval: `MOCK_APPROVAL_REJECT=true` env var
- **Time-travel helper** `get_thread_history()` in persistence module
- **SQLite + Postgres** checkpointer wired and documented

### Would add with more time

- LLM-as-judge in `evaluate_node` for semantic quality assessment
- Parallel fan-out: split multi-part queries across tool branches
- Structured tool schema with Pydantic validation on results
- LangSmith tracing integration for production observability

---

## 8. Improvement Plan

If I had one more day, I would productionize **the evaluation node first**:

The current `evaluate_node` uses a brittle `"ERROR" in latest` string check. Replacing it with an LLM-as-judge that validates structured JSON tool responses would:
1. Eliminate false retries on responses that contain the word "ERROR" in a non-failure context
2. Enable semantic quality checks (e.g., "did the tool return a valid order object?")
3. Allow the graph to request a different tool if the result is correct but insufficient

This change would increase the agent's precision from keyword-matching to semantic understanding without adding latency to the happy path (evaluation only fires in the tool→evaluate→retry loop).

---

*Report generated from `outputs/metrics.json` — all scenarios run with `MemorySaver` checkpointer.*
