import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path("data/memory.db")
_FTS_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "is",
    "of",
    "the",
    "to",
    "what",
}


def init_db(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_entries (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            authorship TEXT NOT NULL CHECK (authorship IN ('human-authored','agent-created')),
            provenance TEXT NOT NULL CHECK (provenance IN ('user-input','tool-observed','external-fetched','human-reviewed')),
            domain TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            use_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            content,
            content='memory_entries',
            content_rowid='rowid'
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
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_checkpoints (
            workflow_id TEXT,
            phase_index INTEGER,
            status TEXT,
            result_json TEXT,
            updated_at TEXT,
            PRIMARY KEY (workflow_id, phase_index)
        );
        """
    )
    conn.commit()
    return conn


def add_memory(
    conn: sqlite3.Connection,
    id_: str,
    content: str,
    authorship: str,
    provenance: str,
    domain: str,
) -> None:
    conn.execute(
        """
        INSERT INTO memory_entries
            (id, content, authorship, provenance, domain, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            id_,
            content,
            authorship,
            provenance,
            domain,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def search_memory(
    conn: sqlite3.Connection,
    query: str,
    domain: str,
    limit: int = 5,
) -> list[dict[str, object]]:
    if limit < 1:
        return []
    fts_query = _normalize_fts_query(query)
    if not fts_query:
        return []

    rows = conn.execute(
        """
        SELECT e.id, e.content, e.authorship, e.provenance
        FROM memory_fts AS f
        JOIN memory_entries AS e ON f.rowid = e.rowid
        WHERE memory_fts MATCH ? AND e.domain = ?
        ORDER BY rank
        LIMIT ?
        """,
        (fts_query, domain, limit),
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        UPDATE memory_entries
        SET last_used_at = ?, use_count = use_count + 1
        WHERE id = ?
        """,
        [(now, row["id"]) for row in rows],
    )
    conn.commit()
    return [
        {
            "id": row["id"],
            "content": row["content"],
            "authorship": row["authorship"],
            "provenance": row["provenance"],
        }
        for row in rows
    ]


def _normalize_fts_query(query: str) -> str:
    tokens = [token for token in _FTS_TOKEN.findall(query.lower()) if token not in _STOP_WORDS]
    return " OR ".join(f'"{token}"' for token in tokens)
import json

def get_workflow_checkpoint(conn: sqlite3.Connection, workflow_id: str, phase_index: int) -> dict | None:
    row = conn.execute(
        "SELECT status, result_json FROM workflow_checkpoints WHERE workflow_id = ? AND phase_index = ?",
        (workflow_id, phase_index)
    ).fetchone()
    if row:
        return {
            "status": row["status"],
            "result_json": json.loads(row["result_json"]) if row["result_json"] else None
        }
    return None

def save_workflow_checkpoint(conn: sqlite3.Connection, workflow_id: str, phase_index: int, status: str, result_json: dict | list | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO workflow_checkpoints (workflow_id, phase_index, status, result_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(workflow_id, phase_index) DO UPDATE SET
            status=excluded.status,
            result_json=excluded.result_json,
            updated_at=excluded.updated_at
        """,
        (workflow_id, phase_index, status, json.dumps(result_json) if result_json else None, now)
    )
    conn.commit()


def create_session(conn: sqlite3.Connection, session_id: str, agent_id: str, goal: str, environment: dict = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        '''
        INSERT INTO sessions (id, agent_id, goal, status, environment, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (session_id, agent_id, goal, "pending", json.dumps(environment or {}), now, now)
    )
    conn.commit()

def get_session(conn: sqlite3.Connection, session_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "goal": row["goal"],
            "status": row["status"],
            "environment": json.loads(row["environment"]) if row["environment"] else {},
            "run_receipt": json.loads(row["run_receipt"]) if row["run_receipt"] else None,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }
    return None

def update_session(conn: sqlite3.Connection, session_id: str, status: str, run_receipt: dict | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        '''
        UPDATE sessions
        SET status = ?, run_receipt = ?, updated_at = ?
        WHERE id = ?
        ''',
        (status, json.dumps(run_receipt) if run_receipt else None, now, session_id)
    )
    conn.commit()
