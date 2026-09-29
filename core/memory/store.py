"""SQLite storage: memory, sessions, approvals, schedules, checkpoints.

The schema is migrated once per database path per process (`init_db`), and every
connection uses WAL. The append-only event log lives in `core/eventlog.py` on top of
the `events` table created here.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/memory.db")
_FTS_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_STOP_WORDS = {"a", "an", "and", "are", "is", "of", "the", "to", "what"}
SCHEMA_VERSION = 2
_migrated: set[str] = set()
_migrate_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    authorship TEXT NOT NULL CHECK (authorship IN ('human-authored','agent-created')),
    provenance TEXT NOT NULL CHECK (provenance IN ('user-input','tool-observed','external-fetched','human-reviewed')),
    domain TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    use_count INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content, content='memory_entries', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS memory_entries_ai AFTER INSERT ON memory_entries BEGIN
    INSERT INTO memory_fts(rowid, content) VALUES (new.rowid, new.content);
END;
CREATE TRIGGER IF NOT EXISTS memory_entries_ad AFTER DELETE ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
END;
CREATE TRIGGER IF NOT EXISTS memory_entries_au AFTER UPDATE OF content ON memory_entries BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, content) VALUES ('delete', old.rowid, old.content);
    INSERT INTO memory_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    environment JSON,
    run_receipt JSON,
    interruption_payload TEXT,
    parent_session_id TEXT,
    parent_event_id TEXT,
    outcome TEXT,
    verified INTEGER,
    verification JSON,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    parent_id TEXT,
    type TEXT NOT NULL,
    payload JSON NOT NULL,
    prev_hash TEXT,
    hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS ev_session ON events(session_id, seq);
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(text, tokenize='unicode61');

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    tool TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    rendered TEXT NOT NULL,
    risk_tier TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_by TEXT,
    scope TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS approval_rules (
    tool TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tool, args_hash)
);

CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'cron',
    cron TEXT,
    interval_minutes INTEGER,
    timezone TEXT,
    agent_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    environment JSON,
    paused INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_checkpoints (
    workflow_id TEXT,
    phase_index INTEGER,
    status TEXT,
    result_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (workflow_id, phase_index)
);

CREATE TABLE IF NOT EXISTS skill_metrics (
    skill_id TEXT PRIMARY KEY,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0
);
"""

# Columns added after the first release; applied idempotently to old databases.
_ADD_COLUMNS = {
    "sessions": {
        "parent_session_id": "TEXT",
        "parent_event_id": "TEXT",
        "outcome": "TEXT",
        "verified": "INTEGER",
        "verification": "JSON",
    },
    "memory_entries": {"superseded_by": "TEXT"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    for table, columns in _ADD_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    if not conn.execute("SELECT 1 FROM schema_version").fetchone():
        conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
    else:
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
    conn.commit()


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection (WAL). The schema is migrated once per path per process."""
    if db_path is None:
        from core.settings import settings

        db_path = settings().db_path
    path = Path(db_path)
    if str(db_path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path) if str(db_path) == ":memory:" else path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    if str(db_path) == ":memory:":
        _migrate(conn)
        return conn
    key = str(path.resolve())
    with _migrate_lock:
        if key not in _migrated or not path.exists():
            _migrate(conn)
            _migrated.add(key)
    return conn


def forget_migrations() -> None:
    """Test helper: force the next init_db per path to re-run migrations."""
    _migrated.clear()


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------
def add_memory(
    conn: sqlite3.Connection,
    id_: str,
    content: str,
    authorship: str,
    provenance: str,
    domain: str,
) -> None:
    conn.execute(
        """INSERT INTO memory_entries (id, content, authorship, provenance, domain, created_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (id_, content, authorship, provenance, domain, _now()),
    )
    conn.commit()


def search_memory(
    conn: sqlite3.Connection,
    query: str,
    domain: str | None,
    limit: int = 5,
) -> list[dict[str, object]]:
    """FTS search. Matches `domain` or the shared 'general' domain; `None` searches all.

    Searching has no side effects; call `record_memory_use` for entries actually used.
    """
    if limit < 1:
        return []
    fts_query = _normalize_fts_query(query)
    if not fts_query:
        return []
    sql = """SELECT e.id, e.content, e.authorship, e.provenance
        FROM memory_fts AS f JOIN memory_entries AS e ON f.rowid = e.rowid
        WHERE memory_fts MATCH ? AND e.superseded_by IS NULL"""
    params: list[object] = [fts_query]
    if domain is not None:
        sql += " AND e.domain IN (?, 'general')"
        params.append(domain)
    sql += " ORDER BY (e.domain = ?) DESC, rank LIMIT ?"
    params += [domain or "", limit]
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": r["id"],
            "content": r["content"],
            "authorship": r["authorship"],
            "provenance": r["provenance"],
        }
        for r in rows
    ]


def record_memory_use(conn: sqlite3.Connection, ids: list[str]) -> None:
    if not ids:
        return
    now = _now()
    conn.executemany(
        "UPDATE memory_entries SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
        [(now, i) for i in ids],
    )
    conn.commit()


def _normalize_fts_query(query: str) -> str:
    tokens = [t for t in _FTS_TOKEN.findall(query.lower()) if t not in _STOP_WORDS]
    return " OR ".join(f'"{t}"' for t in tokens)


# ---------------------------------------------------------------------------
# Workflow checkpoints
# ---------------------------------------------------------------------------
def get_workflow_checkpoint(conn, workflow_id: str, phase_index: int) -> dict | None:
    row = conn.execute(
        "SELECT status, result_json FROM workflow_checkpoints WHERE workflow_id = ? AND phase_index = ?",
        (workflow_id, phase_index),
    ).fetchone()
    if row:
        return {
            "status": row["status"],
            "result_json": json.loads(row["result_json"]) if row["result_json"] else None,
        }
    return None


def save_workflow_checkpoint(conn, workflow_id, phase_index, status, result_json=None) -> None:
    conn.execute(
        """INSERT INTO workflow_checkpoints (workflow_id, phase_index, status, result_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(workflow_id, phase_index) DO UPDATE SET
            status=excluded.status, result_json=excluded.result_json, updated_at=excluded.updated_at""",
        (workflow_id, phase_index, status, json.dumps(result_json) if result_json is not None else None, _now()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def create_session(
    conn,
    session_id: str,
    agent_id: str,
    goal: str,
    environment: dict | None = None,
    parent_session_id: str | None = None,
    parent_event_id: str | None = None,
    verification: dict | None = None,
) -> None:
    now = _now()
    conn.execute(
        """INSERT INTO sessions (id, agent_id, goal, status, environment, parent_session_id,
            parent_event_id, verification, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)""",
        (session_id, agent_id, goal, json.dumps(environment or {}), parent_session_id,
         parent_event_id, json.dumps(verification) if verification else None, now, now),
    )
    conn.commit()


def _session_row(row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "goal": row["goal"],
        "status": row["status"],
        "environment": json.loads(row["environment"]) if row["environment"] else {},
        "run_receipt": json.loads(row["run_receipt"]) if row["run_receipt"] else None,
        "parent_session_id": row["parent_session_id"],
        "parent_event_id": row["parent_event_id"] if "parent_event_id" in keys else None,
        "outcome": row["outcome"] if "outcome" in keys else None,
        "verification": json.loads(row["verification"]) if "verification" in keys and row["verification"] else None,
        "verified": (None if row["verified"] is None else bool(row["verified"]))
        if "verified" in keys else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_session(conn, session_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return _session_row(row) if row else None


_UNSET = object()


def update_session(
    conn,
    session_id: str,
    status: str,
    run_receipt=_UNSET,
    *,
    outcome: str | None = None,
    verified=_UNSET,
) -> None:
    """Update status. The stored receipt is only touched when `run_receipt` is passed."""
    sets, params = ["status = ?", "updated_at = ?"], [status, _now()]
    if run_receipt is not _UNSET:
        sets.append("run_receipt = ?")
        params.append(json.dumps(run_receipt) if run_receipt is not None else None)
    if outcome is not None:
        sets.append("outcome = ?")
        params.append(outcome)
    if verified is not _UNSET:
        sets.append("verified = ?")
        params.append(None if verified is None else int(bool(verified)))
    params.append(session_id)
    conn.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()


def claim_session(conn, session_id: str) -> bool:
    """Atomically move pending/idle -> running. False if someone else already runs it."""
    cur = conn.execute(
        "UPDATE sessions SET status = 'running', updated_at = ? WHERE id = ? AND status IN ('pending')",
        (_now(), session_id),
    )
    conn.commit()
    return cur.rowcount == 1


def fail_stale_running(conn, active_ids: set[str], reason: str = "crashed") -> list[str]:
    """Crash recovery: sessions marked running with no live task become failures."""
    rows = conn.execute("SELECT id FROM sessions WHERE status = 'running'").fetchall()
    stale = [r["id"] for r in rows if r["id"] not in active_ids]
    for sid in stale:
        update_session(conn, sid, "failure", outcome=reason)
    return stale


# Interruptions are events (see core/eventlog.py); these helpers keep the old API shape.
def set_session_interruption(conn, session_id: str, message: str) -> None:
    from core.eventlog import append_event

    append_event(conn, session_id, "interrupt_queued", {"content": message})


def get_and_clear_interruption(conn, session_id: str) -> str | None:
    from core.eventlog import drain_interrupts

    pending = drain_interrupts(conn, session_id)
    return "\n".join(pending) if pending else None
