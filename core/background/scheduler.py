"""Persistent scheduling: cron jobs and heartbeats are stored in SQLite and restored on startup."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.memory.store import create_session, init_db
from core.settings import settings

log = logging.getLogger("harness.scheduler")
scheduler = AsyncIOScheduler()
_runs = None  # RunManager, injected by the API lifespan / CLI


def set_run_manager(runs) -> None:
    global _runs
    _runs = runs


async def scheduled_session_job(agent_id: str, goal: str, environment: dict):
    if _runs is None:
        log.warning("scheduled job fired without a RunManager; skipping")
        return None
    sid = str(uuid.uuid4())
    conn = init_db()
    try:
        create_session(conn, sid, agent_id, goal, environment)
    finally:
        conn.close()
    await _runs.start(sid)
    return sid


async def heartbeat_job(agent_id: str, goal: str, environment: dict):
    """Periodic background turn: follow HEARTBEAT.md standing instructions; skip if empty."""
    path = settings().workspace / settings().heartbeat_file
    text = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    if not text:
        return None
    return await scheduled_session_job(
        agent_id, f"{goal}\n\nStanding instructions:\n{text}", environment)


def _persist(row: dict) -> None:
    conn = init_db()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO schedules (id, kind, cron, interval_minutes, timezone, agent_id, goal,
            environment, paused, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (row["id"], row["kind"], row.get("cron"), row.get("interval_minutes"), row.get("timezone"),
             row["agent_id"], row["goal"], json.dumps(row.get("environment") or {}), int(row.get("paused", 0)),
             datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


def _schedule(row: dict):
    env = row.get("environment") or {}
    if row["kind"] == "heartbeat":
        trigger = IntervalTrigger(minutes=int(row["interval_minutes"]))
        job = scheduler.add_job(heartbeat_job, trigger=trigger, id=row["id"], replace_existing=True,
                                args=[row["agent_id"], row["goal"], env])
    else:
        trigger = CronTrigger.from_crontab(row["cron"], timezone=row.get("timezone") or None)
        job = scheduler.add_job(scheduled_session_job, trigger=trigger, id=row["id"], replace_existing=True,
                                args=[row["agent_id"], row["goal"], env])
    if row.get("paused"):
        job.pause()
    return job


def add_agent_cron_job(cron_expr: str, agent_id: str, goal: str, environment: dict | None = None,
                       timezone: str | None = None, persist: bool = True) -> str:
    row = {"id": str(uuid.uuid4()), "kind": "cron", "cron": cron_expr, "timezone": timezone,
           "agent_id": agent_id, "goal": goal, "environment": environment or {}}
    job = _schedule(row)  # raises ValueError for a bad expression before anything is stored
    if persist:
        _persist(row)
    return job.id


def add_heartbeat(agent_id: str, interval_minutes: int, goal: str = "Heartbeat check",
                  environment: dict | None = None) -> str:
    if interval_minutes < 1:
        raise ValueError("interval_minutes must be >= 1")
    row = {"id": str(uuid.uuid4()), "kind": "heartbeat", "interval_minutes": interval_minutes,
           "agent_id": agent_id, "goal": goal, "environment": environment or {}}
    job = _schedule(row)
    _persist(row)
    return job.id


def remove_job(job_id: str) -> bool:
    conn = init_db()
    try:
        cur = conn.execute("DELETE FROM schedules WHERE id = ?", (job_id,))
        conn.commit()
    finally:
        conn.close()
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        return True
    return cur.rowcount > 0


def set_paused(job_id: str, paused: bool) -> bool:
    conn = init_db()
    try:
        cur = conn.execute("UPDATE schedules SET paused = ? WHERE id = ?", (int(paused), job_id))
        conn.commit()
    finally:
        conn.close()
    job = scheduler.get_job(job_id)
    if job:
        job.pause() if paused else job.resume()
    return cur.rowcount > 0


def list_jobs() -> list[dict]:
    conn = init_db()
    try:
        rows = conn.execute("SELECT * FROM schedules ORDER BY created_at").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        job = scheduler.get_job(r["id"])
        out.append({"id": r["id"], "kind": r["kind"], "cron": r["cron"], "interval_minutes": r["interval_minutes"],
                    "timezone": r["timezone"], "agent_id": r["agent_id"], "goal": r["goal"],
                    "paused": bool(r["paused"]),
                    "next_run": str(job.next_run_time) if job and job.next_run_time else None})
    return out


def load_persisted_jobs() -> int:
    conn = init_db()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM schedules")]
    finally:
        conn.close()
    for row in rows:
        row["environment"] = json.loads(row["environment"] or "{}")
        try:
            _schedule(row)
        except Exception as error:  # noqa: BLE001
            log.warning("could not restore schedule %s: %s", row["id"], error)
    return len(rows)


def curate_job() -> None:
    from core.memory.curator import prune_agent_created_skills

    conn = init_db()
    try:
        prune_agent_created_skills(conn)
    finally:
        conn.close()


def start_scheduler(runs=None) -> None:
    if runs is not None:
        set_run_manager(runs)
    if not scheduler.running:
        scheduler.start()
    load_persisted_jobs()
    scheduler.add_job(curate_job, CronTrigger.from_crontab("0 3 * * 0"), id="curator", replace_existing=True)
