"""Memory consolidation ("dreams"): merge related agent-created memories into one summary.

Originals are never deleted: they are marked `superseded_by` the consolidated entry, so a bad
summary can be reverted. Input is chunked so the prompt stays bounded.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from core.llm import simple_completion
from core.memory.store import init_db
from core.settings import settings

CHUNK_CHARS = 8000


def _chunks(items: list[tuple[str, str]]) -> list[list[tuple[str, str]]]:
    chunks, cur, size = [], [], 0
    for item in items:
        if cur and size + len(item[1]) > CHUNK_CHARS:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(item)
        size += len(item[1])
    if cur:
        chunks.append(cur)
    return chunks


async def run_memory_consolidation(db_path=None) -> list[str]:
    st = settings()
    conn = init_db(db_path or st.db_path)
    themes: list[str] = []
    try:
        rows = conn.execute(
            """SELECT id, content, domain FROM memory_entries
            WHERE authorship = 'agent-created' AND superseded_by IS NULL
              AND content NOT LIKE 'CONSOLIDATED THEME:%' ORDER BY created_at""").fetchall()
        by_domain: dict[str, list[tuple[str, str]]] = {}
        for r in rows:
            by_domain.setdefault(r["domain"], []).append((r["id"], r["content"]))
        for domain, items in by_domain.items():
            for chunk in _chunks(items):
                if len(chunk) < 2:
                    continue
                prompt = ("You are a memory consolidation assistant. Read the memories and output one unified "
                          "summary that removes duplicates and stale configuration. Keep technical details "
                          "intact.\n\nMemories:\n" + "\n".join(f"- {c}" for _i, c in chunk))
                summary = (await simple_completion(prompt, st)).strip()
                if not summary:
                    continue
                new_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO memory_entries (id, content, authorship, provenance, domain, created_at, use_count)
                    VALUES (?, ?, 'agent-created', 'tool-observed', ?, ?, 1)""",
                    (new_id, f"CONSOLIDATED THEME: {summary}", domain, datetime.now(timezone.utc).isoformat()))
                conn.executemany("UPDATE memory_entries SET superseded_by = ? WHERE id = ?",
                                 [(new_id, i) for i, _c in chunk])
                themes.append(summary)
        conn.commit()
        return themes
    finally:
        conn.close()
