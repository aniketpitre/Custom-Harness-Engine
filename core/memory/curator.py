"""Skill metrics and pruning. Only agent-created skills are ever removed; human-authored ones never."""
from __future__ import annotations

import shutil
import sqlite3

from core.skills import discover_skills


def init_skill_metrics(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS skill_metrics (
        skill_id TEXT PRIMARY KEY, successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0)""")
    conn.commit()


def record_skill_outcome(conn: sqlite3.Connection, skill_id: str, succeeded: bool) -> None:
    column = "successes" if succeeded else "failures"
    conn.execute(
        f"""INSERT INTO skill_metrics (skill_id, {column}) VALUES (?, 1)
        ON CONFLICT(skill_id) DO UPDATE SET {column} = {column} + 1""", (skill_id,))
    conn.commit()


def prune_agent_created_skills(conn: sqlite3.Connection, min_success_rate: float = 0.5,
                               min_uses: int = 3, dirs=None) -> list[str]:
    """Delete agent-created skills (files) and legacy memory entries with a poor success rate."""
    removed: list[str] = []
    skills = {s.name: s for s in discover_skills(dirs)}
    rows = conn.execute("SELECT skill_id, successes, failures FROM skill_metrics").fetchall()
    for skill_id, successes, failures in rows:
        uses = successes + failures
        if uses < min_uses or successes / uses >= min_success_rate:
            continue
        skill = skills.get(skill_id)
        if skill is not None:
            if skill.authorship != "agent-created":
                continue  # human-authored skills are never touched
            shutil.rmtree(skill.path.parent, ignore_errors=True)
        else:
            entry = conn.execute("SELECT authorship FROM memory_entries WHERE id = ?", (skill_id,)).fetchone()
            if entry is None or entry[0] != "agent-created":
                continue
            conn.execute("DELETE FROM memory_entries WHERE id = ?", (skill_id,))
        conn.execute("DELETE FROM skill_metrics WHERE skill_id = ?", (skill_id,))
        removed.append(skill_id)
    conn.commit()
    return removed
