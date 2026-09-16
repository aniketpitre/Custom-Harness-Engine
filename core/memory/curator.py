import sqlite3


def init_skill_metrics(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS skill_metrics (
            skill_id TEXT PRIMARY KEY,
            successes INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def record_skill_outcome(conn: sqlite3.Connection, skill_id: str, succeeded: bool) -> None:
    init_skill_metrics(conn)
    column = "successes" if succeeded else "failures"
    conn.execute(
        f"""INSERT INTO skill_metrics (skill_id, {column}) VALUES (?, 1)
        ON CONFLICT(skill_id) DO UPDATE SET {column} = {column} + 1""",
        (skill_id,),
    )
    conn.commit()


def prune_agent_created_skills(
    conn: sqlite3.Connection,
    min_success_rate: float = 0.5,
    min_uses: int = 3,
) -> list[str]:
    init_skill_metrics(conn)
    rows = conn.execute(
        """
        SELECT e.id, m.successes, m.failures
        FROM memory_entries AS e
        JOIN skill_metrics AS m ON m.skill_id = e.id
        WHERE e.authorship = 'agent-created'
        """
    ).fetchall()
    removed: list[str] = []
    for skill_id, successes, failures in rows:
        uses = successes + failures
        rate = successes / uses if uses else 0.0
        if uses >= min_uses and rate < min_success_rate:
            conn.execute("DELETE FROM memory_entries WHERE id = ?", (skill_id,))
            conn.execute("DELETE FROM skill_metrics WHERE skill_id = ?", (skill_id,))
            removed.append(skill_id)
    conn.commit()
    return removed
