"""Event log (source of truth), sessions, storage migrations."""
import json
import sqlite3

import pytest

from core import eventlog
from core.memory import store
from core.memory.store import (claim_session, create_session, fail_stale_running, get_session, init_db,
                               update_session)
from core.transcript import repair_transcript, validate_transcript

pytestmark = pytest.mark.integration


@pytest.fixture
def conn():
    c = init_db()
    yield c
    c.close()


def _tool_turn(conn, sid, n):
    eventlog.append_event(conn, sid, "assistant_msg", {"content": None, "tool_calls": [
        {"id": f"c{n}", "type": "function", "function": {"name": "read", "arguments": "{}"}}]})
    eventlog.append_event(conn, sid, "tool_result", {"tool_call_id": f"c{n}", "content": f"result {n}"})


def test_append_assigns_seq_and_chains_hashes(conn):
    a = eventlog.append_event(conn, "s", "user_msg", {"content": "hi"})
    b = eventlog.append_event(conn, "s", "assistant_msg", {"content": "yo"})
    assert (a["seq"], b["seq"]) == (1, 2) and a["hash"] != b["hash"]
    assert eventlog.verify_chain(conn, "s") == (True, None)
    assert eventlog.chain_head(conn, "s") == b["hash"]


def test_tampering_is_detected(conn):
    for i in range(4):
        eventlog.append_event(conn, "s", "user_msg", {"content": f"m{i}"})
    conn.execute("UPDATE events SET payload = ? WHERE session_id = 's' AND seq = 2", ('{"content":"forged"}',))
    conn.commit()
    assert eventlog.verify_chain(conn, "s") == (False, 2)


def test_messages_rebuilt_in_order_with_tool_pairs(conn):
    eventlog.append_event(conn, "s", "user_msg", {"content": "goal"})
    _tool_turn(conn, "s", 1)
    eventlog.append_event(conn, "s", "assistant_msg", {"content": "final"})
    eventlog.append_event(conn, "s", "action", {"tool": "x"})       # non-message events are skipped
    msgs = eventlog.messages_for(conn, "s")
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert validate_transcript(msgs) == []


def test_interrupted_tool_call_is_repaired_on_rebuild(conn):
    eventlog.append_event(conn, "s", "user_msg", {"content": "goal"})
    eventlog.append_event(conn, "s", "assistant_msg", {"content": None, "tool_calls": [
        {"id": "x", "type": "function", "function": {"name": "t", "arguments": "{}"}}]})
    msgs = eventlog.messages_for(conn, "s")          # crash before the tool result was logged
    assert validate_transcript(msgs) == [] and msgs[-1]["role"] == "tool"


def test_repair_drops_orphan_results():
    msgs = [{"role": "user", "content": "x"}, {"role": "tool", "tool_call_id": "zz", "content": "?"}]
    assert repair_transcript(msgs) == [{"role": "user", "content": "x"}]


def test_compaction_event_is_applied_on_replay(conn):
    eventlog.append_event(conn, "s", "user_msg", {"content": "goal"})       # seq 1 (pinned)
    _tool_turn(conn, "s", 1)                                                # seq 2,3
    _tool_turn(conn, "s", 2)                                                # seq 4,5
    eventlog.append_event(conn, "s", "compaction", {"summary": "S", "first_kept_seq": 4, "pinned_seqs": [1],
                                                    "pruned": {"c2": "[pruned]"}})
    msgs = eventlog.messages_for(conn, "s")
    assert msgs[0]["content"] == "goal" and "<summary>" in msgs[1]["content"]
    assert msgs[2]["role"] == "assistant" and msgs[3]["content"] == "[pruned]"
    assert validate_transcript(msgs) == []
    assert len(eventlog.list_events(conn, "s")) == 6                         # nothing was deleted


def test_fork_copies_up_to_event_and_never_splits_tool_pair(conn):
    eventlog.append_event(conn, "s", "user_msg", {"content": "goal"})
    call = eventlog.append_event(conn, "s", "assistant_msg", {"content": None, "tool_calls": [
        {"id": "c", "type": "function", "function": {"name": "t", "arguments": "{}"}}]})
    eventlog.append_event(conn, "s", "tool_result", {"tool_call_id": "c", "content": "r"})
    eventlog.append_event(conn, "s", "assistant_msg", {"content": "later"})
    n = eventlog.fork_events(conn, "s", "f", at_event_id=call["id"])       # fork "at" the tool call
    assert n == 1                                                          # dropped the unanswered call
    assert validate_transcript(eventlog.messages_for(conn, "f")) == []
    assert eventlog.verify_chain(conn, "f") == (True, None)
    assert eventlog.fork_events(conn, "s", "g") == 4
    with pytest.raises(KeyError):
        eventlog.fork_events(conn, "s", "h", at_event_id="nope")


def test_interrupts_become_ordered_user_messages_once(conn):
    eventlog.append_event(conn, "s", "user_msg", {"content": "goal"})
    eventlog.append_event(conn, "s", "interrupt_queued", {"content": "one"})
    eventlog.append_event(conn, "s", "interrupt_queued", {"content": "two"})
    assert eventlog.drain_interrupts(conn, "s") == ["one", "two"]
    assert eventlog.drain_interrupts(conn, "s") == []
    assert [m["content"] for m in eventlog.messages_for(conn, "s")][1:] == [
        "User Interruption: one", "User Interruption: two"]


def test_session_search_over_events(conn):
    eventlog.append_event(conn, "a", "user_msg", {"content": "why is checkout latency high"})
    eventlog.append_event(conn, "b", "assistant_msg", {"content": "redis connection pool exhausted"})
    hits = eventlog.search_events(conn, "redis pool")
    assert hits and hits[0]["session_id"] == "b"
    assert eventlog.search_events(conn, "the of") == []


def test_update_session_does_not_wipe_receipt(conn):
    create_session(conn, "s", "a", "g")
    update_session(conn, "s", "success", {"final_text": "x"})
    update_session(conn, "s", "running")               # used to set run_receipt = NULL
    assert get_session(conn, "s")["run_receipt"] == {"final_text": "x"}
    update_session(conn, "s", "failure", None)          # explicit clear still possible
    assert get_session(conn, "s")["run_receipt"] is None


def test_claim_session_is_atomic(conn):
    create_session(conn, "s", "a", "g")
    other = init_db()
    assert claim_session(conn, "s") is True
    assert claim_session(other, "s") is False
    other.close()


def test_crash_recovery_marks_stale_running_sessions(conn):
    create_session(conn, "s1", "a", "g")
    create_session(conn, "s2", "a", "g")
    update_session(conn, "s1", "running")
    update_session(conn, "s2", "running")
    assert fail_stale_running(conn, active_ids={"s2"}) == ["s1"]
    assert get_session(conn, "s1")["status"] == "failure" and get_session(conn, "s1")["outcome"] == "crashed"
    assert get_session(conn, "s2")["status"] == "running"


def test_migrates_once_uses_wal_and_creates_all_tables(tmp_path, monkeypatch):
    path = tmp_path / "x" / "db.sqlite"
    calls = []
    real = store._migrate
    monkeypatch.setattr(store, "_migrate", lambda c: (calls.append(1), real(c)))
    for _ in range(5):
        init_db(path).close()
    assert len(calls) == 1
    c = init_db(path)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"memory_entries", "sessions", "events", "approvals", "approval_rules", "schedules",
            "workflow_checkpoints", "skill_metrics", "schema_version"} <= tables
    c.close()


def test_old_database_is_upgraded_in_place(tmp_path):
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.executescript("""CREATE TABLE sessions (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, goal TEXT NOT NULL,
        status TEXT NOT NULL, environment JSON, run_receipt JSON, interruption_payload TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO sessions VALUES ('old','a','g','success','{}',NULL,NULL,'t','t');
        CREATE TABLE memory_entries (id TEXT PRIMARY KEY, content TEXT NOT NULL, authorship TEXT NOT NULL,
        provenance TEXT NOT NULL, domain TEXT NOT NULL, created_at TEXT NOT NULL, last_used_at TEXT,
        use_count INTEGER NOT NULL DEFAULT 0);""")
    raw.commit()
    raw.close()
    c = init_db(path)
    assert get_session(c, "old")["status"] == "success"
    cols = {r[1] for r in c.execute("PRAGMA table_info(sessions)")}
    assert {"parent_session_id", "outcome", "verified"} <= cols
    c.close()


def test_workflow_checkpoints_exist_on_a_real_db(conn):
    """Regression: init_db() never created workflow_checkpoints, so orchestration crashed."""
    store.save_workflow_checkpoint(conn, "wf", 0, "completed", {"a": 1})
    assert store.get_workflow_checkpoint(conn, "wf", 0) == {"status": "completed", "result_json": {"a": 1}}


class TestMemoryStore:
    def test_add_search_with_provenance(self, conn):
        store.add_memory(conn, "n1", "ArgoCD sync failures are usually webhook drift", "human-authored",
                         "human-reviewed", "devops")
        r = store.search_memory(conn, "ArgoCD sync", "devops")
        assert r == [{"id": "n1", "content": "ArgoCD sync failures are usually webhook drift",
                      "authorship": "human-authored", "provenance": "human-reviewed"}]

    def test_search_has_no_side_effects_and_use_is_explicit(self, conn):
        store.add_memory(conn, "n1", "service health readiness", "agent-created", "tool-observed", "general")
        store.search_memory(conn, "service health", "general")
        assert conn.execute("SELECT use_count FROM memory_entries").fetchone()[0] == 0
        store.record_memory_use(conn, ["n1"])
        assert conn.execute("SELECT use_count FROM memory_entries").fetchone()[0] == 1

    def test_domain_filter_includes_general_and_none_searches_all(self, conn):
        store.add_memory(conn, "d", "kubernetes pod restart", "human-authored", "user-input", "devops")
        store.add_memory(conn, "c", "kubernetes test fixture", "human-authored", "user-input", "coding")
        store.add_memory(conn, "g", "kubernetes general note", "human-authored", "user-input", "general")
        ids = {r["id"] for r in store.search_memory(conn, "kubernetes", "devops")}
        assert ids == {"d", "g"}
        assert {r["id"] for r in store.search_memory(conn, "kubernetes", None)} == {"d", "c", "g"}
        assert [r["id"] for r in store.search_memory(conn, "kubernetes", "devops", limit=1)] == ["d"]

    def test_superseded_entries_are_hidden(self, conn):
        store.add_memory(conn, "a", "old fact about redis", "agent-created", "tool-observed", "devops")
        conn.execute("UPDATE memory_entries SET superseded_by = 'b' WHERE id = 'a'")
        assert store.search_memory(conn, "redis", "devops") == []

    def test_invalid_provenance_rejected(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            store.add_memory(conn, "x", "c", "human-authored", "untrusted", "general")
