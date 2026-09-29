"""Subagents: typed profiles, capability intersection, shared budget, concurrency and time limits,
child sessions linked to the parent, and results returned as data."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from core.memory.store import create_session, init_db, update_session
from core.primitives.agent import AgentProfile
from core.primitives.context import ContextPacket
from core.primitives.goal import Goal
from core.tools import RunCtx

MAX_DEPTH = 2


async def run_subagent(parent: RunCtx, goal: str, *, profile: AgentProfile | None = None,
                       capabilities: list[str] | None = None, label: str = "subagent") -> dict[str, Any]:
    from core.loop import DBSink, run_agent_generator
    from core.modes import child_mode
    from core.receipts import derive_status

    st = parent.settings
    engine = parent.engine
    if parent.depth >= MAX_DEPTH:
        return {"status": "failure", "error": f"Subagent depth limit ({MAX_DEPTH}) reached", "final_text": ""}
    requested = set(capabilities) if capabilities else (set(profile.allowed_tools) if profile else set(parent.allowed))
    from core.engine import expand_capabilities

    allowed = expand_capabilities(requested) & parent.allowed          # never more than the parent has
    if parent.depth + 1 >= MAX_DEPTH:
        allowed.discard("Subagents")
    sem: asyncio.Semaphore = engine.extras.setdefault("subagent_sem", asyncio.Semaphore(st.max_subagents))
    session_id = str(uuid.uuid4())
    conn = init_db(st.db_path)
    try:
        create_session(conn, session_id, profile.id if profile else f"{parent.agent_id}:{label}", goal,
                       parent_session_id=parent.session_id)
        sink = DBSink(conn, session_id)
        context = ContextPacket(goal=Goal(id=session_id, source=parent.extras["context"].goal.source,
                                          raw_input=goal, created_at=datetime.now(timezone.utc),
                                          domain=(profile.domain if profile else parent.domain)),
                                live_state={k: v for k, v in parent.extras["context"].live_state.items()
                                            if k != "verification"})
        final: dict[str, Any] | None = None

        async def go() -> None:
            nonlocal final
            async for ev in run_agent_generator(session_id, context, sorted(allowed), profile, engine=engine,
                                                sink=sink, budget=parent.budget, depth=parent.depth + 1,
                                                mode=child_mode(parent.mode)):
                if ev["type"] == "final_receipt":
                    final = ev["receipt"]

        async with sem:
            update_session(conn, session_id, "running")
            try:
                await asyncio.wait_for(go(), st.subagent_timeout)
            except asyncio.TimeoutError:
                update_session(conn, session_id, "failure", outcome="time_limit")
                return {"session_id": session_id, "status": "failure", "error": "subagent timed out", "final_text": ""}
        assert final is not None
        status = derive_status(final["outcome"], final["verified"])
        update_session(conn, session_id, status, outcome=final["outcome"], verified=final["verified"],
                       usage=final.get("usage"))
        return {"session_id": session_id, "status": status, "outcome": final["outcome"],
                "final_text": final["final_text"], "actions": len(final["actions"]),
                "model_used": final["model_used"]}
    finally:
        conn.close()
