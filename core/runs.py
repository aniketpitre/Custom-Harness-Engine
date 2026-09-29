"""Detached session runs: execution is separate from observation.

`RunManager.start()` claims a pending session atomically and runs it as a tracked background
task that writes to the event log. SSE endpoints only tail the log / live buffer, so a client
disconnect never cancels a run. `cancel()` stops it; the session is always finalised.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Coroutine

from core import eventlog
from core.engine import Engine, get_engine
from core.gateway.webhooks import dispatch_webhook
from core.loop import DBSink, run_agent_generator
from core.memory.store import claim_session, fail_stale_running, get_session, init_db, search_memory, update_session
from core.primitives.context import ContextPacket
from core.primitives.goal import Goal, TriggerSource
from core.receipts import build_receipt, receipt_json
from core.registry import AgentRegistry

log = logging.getLogger("harness.runs")
BUFFER_SIZE = 2000
_background: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """create_task with a strong reference so tasks are not garbage-collected mid-flight."""
    task = asyncio.get_running_loop().create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


class LiveBuffer:
    """Ring buffer of live events with ids, so SSE clients can resume with Last-Event-ID."""

    def __init__(self) -> None:
        self.events: deque[tuple[int, dict]] = deque(maxlen=BUFFER_SIZE)
        self.next_id = 1
        self.closed = False
        self._cond: asyncio.Condition | None = None

    def _c(self) -> asyncio.Condition:
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    async def publish(self, event: dict | None) -> None:
        async with self._c():
            if event is None:
                self.closed = True
            else:
                self.events.append((self.next_id, event))
                self.next_id += 1
            self._c().notify_all()

    async def tail(self, after: int = 0, keepalive: float = 15.0):
        cursor = after
        while True:
            pending = [(i, e) for i, e in self.events if i > cursor]
            for i, e in pending:
                cursor = i
                yield i, e
            if self.closed and not [1 for i, _ in self.events if i > cursor]:
                return
            async with self._c():
                try:
                    await asyncio.wait_for(self._c().wait(), keepalive)
                except asyncio.TimeoutError:
                    yield None, {"type": "keepalive"}


def _json_event(event: dict) -> dict:
    out = dict(event)
    if event.get("type") == "final_receipt":
        r = dict(event["receipt"])
        r["actions"] = [a.model_dump(mode="json") if hasattr(a, "model_dump") else a for a in r.get("actions", [])]
        v = r.get("verification")
        r["verification"] = v.model_dump(mode="json") if hasattr(v, "model_dump") else v
        r.pop("events", None)
        r.pop("started_at", None)
        out["receipt"] = r
    return json.loads(json.dumps(out, default=str))


class RunManager:
    def __init__(self, engine: Engine | None = None, agents: AgentRegistry | None = None) -> None:
        self.engine = engine or get_engine()
        self.agents = agents
        self.tasks: dict[str, asyncio.Task] = {}
        self.buffers: dict[str, LiveBuffer] = {}

    def is_active(self, session_id: str) -> bool:
        t = self.tasks.get(session_id)
        return bool(t and not t.done())

    def active_ids(self) -> set[str]:
        return {sid for sid in self.tasks if self.is_active(sid)}

    def recover(self) -> list[str]:
        """Crash recovery on startup: sessions left `running` by a dead process become failures."""
        conn = init_db()
        try:
            return fail_stale_running(conn, self.active_ids())
        finally:
            conn.close()

    async def start(self, session_id: str) -> bool:
        conn = init_db()
        try:
            if not claim_session(conn, session_id):
                return False
        finally:
            conn.close()
        self.buffers[session_id] = LiveBuffer()
        self.tasks[session_id] = spawn(self._guarded(session_id))
        return True

    def cancel(self, session_id: str) -> bool:
        task = self.tasks.get(session_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def wait(self, session_id: str) -> None:
        task = self.tasks.get(session_id)
        if task:
            await asyncio.gather(task, return_exceptions=True)

    async def run_inline(self, session_id: str) -> dict:
        """Claim and run to completion in the caller's task (CLI, subagent-free callers)."""
        if not await self.start(session_id):
            raise RuntimeError(f"Session {session_id} is not pending")
        await self.wait(session_id)
        conn = init_db()
        try:
            return get_session(conn, session_id)
        finally:
            conn.close()

    async def _guarded(self, session_id: str) -> None:
        try:
            await self._run(session_id)
        except asyncio.CancelledError:
            conn = init_db()
            try:
                update_session(conn, session_id, "failure", outcome="cancelled")
            finally:
                conn.close()
            spawn(dispatch_webhook(session_id, "failure"))
        except Exception:  # noqa: BLE001
            log.exception("session %s crashed", session_id)
            conn = init_db()
            try:
                update_session(conn, session_id, "failure", outcome="error")
            finally:
                conn.close()
            spawn(dispatch_webhook(session_id, "failure"))
        finally:
            buf = self.buffers.get(session_id)
            if buf:
                await buf.publish(None)

    async def _run(self, session_id: str) -> None:
        conn = init_db()
        try:
            session = get_session(conn, session_id)
            profile = self.agents.get_agent(session["agent_id"]) if self.agents else None
            if profile is None:
                update_session(conn, session_id, "failure", outcome="error")
                await self.buffers[session_id].publish({"type": "error", "message": "Agent not found"})
                return
            goal = Goal(id=session_id, source=TriggerSource.api, raw_input=session["goal"],
                        created_at=datetime.now(timezone.utc), domain=profile.domain)
            live: dict[str, Any] = {}
            if session.get("verification"):
                live["verification"] = session["verification"]
            if session.get("environment"):
                live["environment"] = session["environment"]   # visible to the agent in its first prompt
            context = ContextPacket(goal=goal, memory_hits=search_memory(conn, session["goal"], profile.domain),
                                    live_state=live)
            sink = DBSink(conn, session_id)
            buf = self.buffers[session_id]
            final = None
            async for event in run_agent_generator(session_id, context, profile.allowed_tools, profile,
                                                   engine=self.engine, sink=sink,
                                                   mode=session.get("permission_mode")):
                if event["type"] == "final_receipt":
                    final = event
                await buf.publish(_json_event(event))
            if final is None:
                raise RuntimeError("run ended without a receipt")
            r = final["receipt"]
            receipt = build_receipt(conn, session_id, goal, profile.id, model_used=r["model_used"],
                                    final_text=r["final_text"], outcome=r["outcome"],
                                    verification=r["verification"], started_at=goal.created_at,
                                    teardown_tasks=r["teardown_tasks"], usage=r.get("usage"))
            self._record_skill_outcomes(conn, session_id, r)
            data = receipt_json(receipt)
            update_session(conn, session_id, receipt.status, data, outcome=r["outcome"], verified=r["verified"],
                           usage=r.get("usage"))
            spawn(dispatch_webhook(session_id, receipt.status, data))
        finally:
            conn.close()

    @staticmethod
    def _record_skill_outcomes(conn, session_id: str, r: dict) -> None:
        from core.memory.curator import record_skill_outcome

        used = next((e["payload"].get("skills_used") for e in eventlog.list_events(conn, session_id, types={"outcome"})
                     if e["payload"].get("skills_used")), None) or []
        ok = r["outcome"] == "completed" and r["verified"] is not False
        for name in used:
            record_skill_outcome(conn, name, ok)
