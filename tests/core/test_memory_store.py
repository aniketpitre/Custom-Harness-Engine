import sqlite3

import pytest

from core.memory.store import add_memory, init_db, search_memory
from core.gateway.cli import build_context


def test_memory_can_be_added_and_retrieved_with_provenance(tmp_path) -> None:
    conn = init_db(tmp_path / "memory.db")
    add_memory(
        conn,
        "note-1",
        "ArgoCD sync failures are usually caused by webhook drift",
        "human-authored",
        "human-reviewed",
        "devops",
    )

    results = search_memory(conn, "ArgoCD sync", "devops")

    assert results == [
        {
            "id": "note-1",
            "content": "ArgoCD sync failures are usually caused by webhook drift",
            "authorship": "human-authored",
            "provenance": "human-reviewed",
        }
    ]
    usage = conn.execute(
        "SELECT use_count, last_used_at FROM memory_entries WHERE id = ?", ("note-1",)
    ).fetchone()
    assert usage[0] == 1
    assert usage[1] is not None
    conn.close()


def test_memory_search_filters_by_domain_and_limit(tmp_path) -> None:
    conn = init_db(tmp_path / "memory.db")
    add_memory(conn, "devops-1", "Kubernetes pod restart", "human-authored", "user-input", "devops")
    add_memory(conn, "coding-1", "Kubernetes test fixture", "human-authored", "user-input", "coding")

    results = search_memory(conn, "Kubernetes", "devops", limit=1)

    assert [result["id"] for result in results] == ["devops-1"]
    conn.close()


def test_memory_search_handles_plain_goal_text(tmp_path) -> None:
    conn = init_db(tmp_path / "memory.db")
    add_memory(conn, "note-1", "Check service health", "agent-created", "tool-observed", "general")

    results = search_memory(conn, "What is the service health?", "general")

    assert results[0]["id"] == "note-1"
    conn.close()


def test_memory_rejects_invalid_provenance(tmp_path) -> None:
    conn = init_db(tmp_path / "memory.db")
    with pytest.raises(sqlite3.IntegrityError):
        add_memory(conn, "note-1", "Content", "human-authored", "untrusted", "general")
    conn.close()


def test_cli_context_includes_relevant_memory(tmp_path) -> None:
    conn = init_db(tmp_path / "memory.db")
    add_memory(
        conn,
        "note-1",
        "Service health checks should inspect readiness",
        "human-authored",
        "human-reviewed",
        "general",
    )

    context = build_context("What is the service health?", conn)

    assert context.memory_hits[0]["id"] == "note-1"
    assert context.memory_hits[0]["provenance"] == "human-reviewed"
    conn.close()