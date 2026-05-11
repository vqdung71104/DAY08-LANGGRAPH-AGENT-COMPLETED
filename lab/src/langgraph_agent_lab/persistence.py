"""Checkpointer adapter with SQLite and time-travel support."""

from __future__ import annotations

from typing import Any


def build_checkpointer(kind: str = "memory", database_url: str | None = None) -> Any | None:
    """Return a LangGraph checkpointer.

    Supported kinds:
    - memory  : MemorySaver (default, no infrastructure required)
    - sqlite  : SqliteSaver (file-based persistence, crash-resume capable)
    - postgres: PostgresSaver (production-grade)
    - none    : no checkpointing (stateless)

    SQLite enables crash-resume: if a run is interrupted, invoke the graph again
    with the same thread_id and it will resume from the last checkpoint.
    """
    if kind == "none":
        return None
    if kind == "memory":
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()
    if kind == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise RuntimeError(
                "SQLite checkpointer requires: pip install langgraph-checkpoint-sqlite"
            ) from exc
        db_path = database_url or "checkpoints.db"
        return SqliteSaver.from_conn_string(db_path)
    if kind == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise RuntimeError(
                "Postgres checkpointer requires: pip install langgraph-checkpoint-postgres"
            ) from exc
        return PostgresSaver.from_conn_string(database_url or "")
    raise ValueError(f"Unknown checkpointer kind: {kind!r}. Valid: memory, sqlite, postgres, none")


def get_thread_history(graph: Any, thread_id: str) -> list[dict[str, Any]]:
    """Return all checkpoint states for a thread (time-travel / debug).

    Usage::
        history = get_thread_history(graph, "thread-S01_simple")
        for snap in history:
            print(snap["config"], snap["values"].get("route"))
    """
    config = {"configurable": {"thread_id": thread_id}}
    snapshots = list(graph.get_state_history(config))
    return [
        {
            "config": snap.config,
            "values": snap.values,
            "next": snap.next,
            "created_at": getattr(snap, "created_at", None),
        }
        for snap in snapshots
    ]
