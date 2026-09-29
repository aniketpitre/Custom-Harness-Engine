"""Append-only, hash-chained session event log (SQLite).

Everything derived from a run - the model transcript, receipts, SSE streams, session
search, forks - is a projection of this table.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from core.transcript import repair_transcript

MESSAGE_TYPES = {"user_msg", "assistant_msg", "tool_result"}
SEARCH_TYPES = MESSAGE_TYPES
GENESIS = "0" * 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canon(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(prev: str, session_id: str, seq: int, type_: str, payload: str) -> str:
    """Hash chain link. With HARNESS_RECEIPT_KEY set it is an HMAC, so an attacker with database
    write access cannot simply recompute the chain."""
    data = f"{prev}|{session_id}|{seq}|{type_}|{payload}".encode()
    key = os.environ.get("HARNESS_RECEIPT_KEY")
    if key:
        return hmac.new(key.encode(), data, hashlib.sha256).hexdigest()
    return hashlib.sha256(data).hexdigest()


def _search_text(type_: str, payload: dict) -> str | None:
    if type_ not in SEARCH_TYPES:
        return None
    text = payload.get("content")
    if not text and payload.get("tool_calls"):
        text = " ".join(
            f"{tc['function']['name']} {tc['function'].get('arguments', '')}"
            for tc in payload["tool_calls"]
        )
    return text if isinstance(text, str) and text else None


def append_event(
    conn: sqlite3.Connection,
    session_id: str,
    type_: str,
    payload: dict[str, Any],
    parent_id: str | None = None,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    payload_json = _canon(payload)
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        last = conn.execute(
            "SELECT seq, hash, id FROM events WHERE session_id = ? ORDER BY seq DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        seq = (last["seq"] + 1) if last else 1
        prev = last["hash"] if last else GENESIS
        digest = _digest(prev, session_id, seq, type_, payload_json)
        event_id = str(uuid.uuid4())
        cur = conn.execute(
            """INSERT INTO events (id, session_id, seq, parent_id, type, payload, prev_hash, hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, session_id, seq, parent_id or (last["id"] if last else None), type_,
             payload_json, prev, digest, created_at or _now()),
        )
        text = _search_text(type_, payload)
        if text:
            conn.execute("INSERT INTO events_fts(rowid, text) VALUES (?, ?)", (cur.lastrowid, text))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"id": event_id, "seq": seq, "hash": digest, "type": type_, "payload": payload}


def _row(r) -> dict[str, Any]:
    return {"id": r["id"], "session_id": r["session_id"], "seq": r["seq"], "parent_id": r["parent_id"],
            "type": r["type"], "payload": json.loads(r["payload"]), "hash": r["hash"],
            "created_at": r["created_at"]}


def list_events(conn, session_id: str, after_seq: int = 0, types: set[str] | None = None,
                limit: int | None = None) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM events WHERE session_id = ? AND seq > ? ORDER BY seq" + (" LIMIT ?" if limit else ""),
        (session_id, after_seq, *([limit] if limit else [])),
    ).fetchall()
    events = [_row(r) for r in rows]
    return [e for e in events if types is None or e["type"] in types]


def last_event(conn, session_id: str) -> dict[str, Any] | None:
    r = conn.execute("SELECT * FROM events WHERE session_id = ? ORDER BY seq DESC LIMIT 1",
                     (session_id,)).fetchone()
    return _row(r) if r else None


def chain_head(conn, session_id: str) -> str | None:
    e = last_event(conn, session_id)
    return e["hash"] if e else None


def verify_chain(conn, session_id: str) -> tuple[bool, int | None]:
    """Recompute the hash chain. Returns (ok, first_bad_seq)."""
    prev = GENESIS
    for r in conn.execute("SELECT * FROM events WHERE session_id = ? ORDER BY seq", (session_id,)):
        if r["prev_hash"] != prev or _digest(prev, session_id, r["seq"], r["type"], r["payload"]) != r["hash"]:
            return False, r["seq"]
        prev = r["hash"]
    return True, None


def _to_message(e: dict[str, Any], pruned: dict[str, str]) -> dict[str, Any] | None:
    p, t = e["payload"], e["type"]
    if t == "user_msg":
        return {"role": "user", "content": p["content"]}
    if t == "assistant_msg":
        msg: dict[str, Any] = {"role": "assistant", "content": p.get("content")}
        if p.get("tool_calls"):
            msg["tool_calls"] = p["tool_calls"]
        return msg
    if t == "tool_result":
        content = pruned.get(p["tool_call_id"], p["content"])
        return {"role": "tool", "tool_call_id": p["tool_call_id"], "content": content}
    return None


def messages_for(conn, session_id: str, *, upto_seq: int | None = None) -> list[dict[str, Any]]:
    """Rebuild the model transcript (without the system prompt) from the event log."""
    return [m for _seq, m in messages_with_seqs(conn, session_id, upto_seq=upto_seq)]


def messages_with_seqs(conn, session_id: str, *, upto_seq: int | None = None) -> list[tuple[int | None, dict]]:
    """Like messages_for, but pairs each message with its event seq (None for summaries)."""
    events = list_events(conn, session_id)
    if upto_seq is not None:
        events = [e for e in events if e["seq"] <= upto_seq]
    compaction = next((e for e in reversed(events) if e["type"] == "compaction"), None)
    pruned: dict[str, str] = {}
    pairs: list[tuple[int | None, dict]] = []
    if compaction:
        cp = compaction["payload"]
        pruned = cp.get("pruned") or {}
        first_kept = cp.get("first_kept_seq", 0)
        pinned = set(cp.get("pinned_seqs") or [])
        for e in events:
            if e["seq"] in pinned and e["seq"] < first_kept and e["type"] in MESSAGE_TYPES:
                pairs.append((e["seq"], _to_message(e, pruned)))
        if cp.get("summary"):
            pairs.append((None, {"role": "user", "content": f"<summary>\n{cp['summary']}\n</summary>"}))
        body = [e for e in events if e["seq"] >= first_kept]
    else:
        body = events
    for e in body:
        if e["type"] in MESSAGE_TYPES:
            m = _to_message(e, pruned)
            if m:
                pairs.append((e["seq"], m))
    repaired = repair_transcript([m for _s, m in pairs])
    if len(repaired) == len(pairs):
        return [(s_, r) for (s_, _m), r in zip(pairs, repaired, strict=True)]
    return [(None, m) for m in repaired]  # repairs inserted messages: seqs no longer align


def drain_interrupts(conn, session_id: str) -> list[str]:
    """Convert queued interrupts into user messages, in order. Returns their texts."""
    events = list_events(conn, session_id, types={"interrupt_queued", "user_msg"})
    consumed = {e["payload"].get("queued_id") for e in events if e["type"] == "user_msg"}
    texts = []
    for e in events:
        if e["type"] == "interrupt_queued" and e["id"] not in consumed:
            text = e["payload"]["content"]
            append_event(conn, session_id, "user_msg",
                         {"content": f"User Interruption: {text}", "queued_id": e["id"]})
            texts.append(text)
    return texts


def fork_events(conn, source_id: str, target_id: str, at_event_id: str | None = None) -> int:
    """Copy events (up to and including `at_event_id`) to a new session. Returns count."""
    events = list_events(conn, source_id)
    if at_event_id:
        cut = next((e["seq"] for e in events if e["id"] == at_event_id), None)
        if cut is None:
            raise KeyError(f"event {at_event_id} not found in session {source_id}")
        events = [e for e in events if e["seq"] <= cut]
    # never end a fork between a tool call and its results
    while events and events[-1]["type"] == "assistant_msg" and events[-1]["payload"].get("tool_calls"):
        events.pop()
    for e in events:
        append_event(conn, target_id, e["type"], e["payload"], created_at=e["created_at"])
    return len(events)


def search_events(conn, query: str, limit: int = 10) -> list[dict[str, Any]]:
    from core.memory.store import _normalize_fts_query

    q = _normalize_fts_query(query)
    if not q:
        return []
    rows = conn.execute(
        """SELECT e.session_id, e.seq, e.type, e.payload, snippet(events_fts, 0, '[', ']', '...', 12) AS snip
        FROM events_fts f JOIN events e ON e.rowid = f.rowid
        WHERE events_fts MATCH ? ORDER BY rank LIMIT ?""",
        (q, limit),
    ).fetchall()
    return [{"session_id": r["session_id"], "seq": r["seq"], "type": r["type"], "snippet": r["snip"]}
            for r in rows]
