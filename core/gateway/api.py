import asyncio
import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

from core.registry import AgentRegistry
from core.memory.store import init_db, create_session, get_session, update_session
from core.agent_engine import run_agent
from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.primitives.execution import RunReceipt
from core.memory.store import search_memory
from core.primitives.learning import draft_skill_if_warranted


app = FastAPI(title="Harness Engine Control Plane API")
registry = AgentRegistry()


class CreateSessionRequest(BaseModel):
    agent_id: str
    goal: str
    environment: Dict[str, str] = {}


def build_context(raw_text: str, conn: Any) -> ContextPacket:
    goal = Goal(
        id=str(uuid.uuid4()),
        source=TriggerSource.cli,
        raw_input=raw_text,
        created_at=datetime.now(timezone.utc),
    )
    return ContextPacket(
        goal=goal,
        memory_hits=search_memory(conn, raw_text, goal.domain),
        live_state={},
        recent_history=[],
        tool_catalog=[],
    )


async def execute_session(session_id: str, agent_id: str, goal_text: str):
    """Background task to run the agent engine and update session state."""
    conn = init_db()

    try:
        update_session(conn, session_id, "running")
        context = build_context(goal_text, conn)
        goal = context.goal

        agent_profile = registry.get_agent(agent_id)
        if not agent_profile:
            update_session(conn, session_id, "failure")
            return

        result = await run_agent(context, allowed_tools=agent_profile.allowed_tools, agent_profile=agent_profile)
        verification = result.get("verification")

        # Build RunReceipt
        receipt = RunReceipt(
            run_id=session_id,
            goal=goal,
            agent_id=agent_id,
            model_used=result.get("model_used", agent_profile.model or "unknown"),
            actions=result.get("actions", []),
            final_text=result.get("final_text", ""),
            status="success" if getattr(verification, "passed", True) else "failure",
            verification=verification,
            started_at=goal.created_at,
            finished_at=datetime.now(timezone.utc),
        )
        receipt.candidate_skill = draft_skill_if_warranted(receipt)

        # Update database with final transaction state
        update_session(
            conn,
            session_id,
            status=receipt.status,
            run_receipt=json.loads(receipt.model_dump_json())
        )
    except Exception as e:
        update_session(conn, session_id, "failure")
    finally:
        conn.close()


@app.get("/agents")
def list_agents():
    return registry.list_agents()


@app.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@app.post("/sessions", status_code=201)
def start_session(req: CreateSessionRequest, background_tasks: BackgroundTasks):
    agent = registry.get_agent(req.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    session_id = str(uuid.uuid4())
    conn = init_db()
    try:
        create_session(
            conn,
            session_id,
            req.agent_id,
            req.goal,
            req.environment
        )
    finally:
        conn.close()

    background_tasks.add_task(
        execute_session,
        session_id=session_id,
        agent_id=req.agent_id,
        goal_text=req.goal
    )

    return {"session_id": session_id, "status": "pending"}


@app.get("/sessions/{session_id}")
def retrieve_session(session_id: str):
    conn = init_db()
    try:
        session = get_session(conn, session_id)
    finally:
        conn.close()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session
