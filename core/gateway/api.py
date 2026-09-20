from core.gateway.webhooks import dispatch_webhook
import asyncio
import asyncio
import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.registry import AgentRegistry
from core.memory.store import init_db, create_session, get_session, update_session, set_session_interruption
from core.agent_engine import run_agent, run_agent_generator
from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.primitives.execution import RunReceipt
from core.memory.store import search_memory
from core.primitives.learning import draft_skill_if_warranted


app = FastAPI(title="Harness Engine Control Plane API")
registry = AgentRegistry()



class CreateCronRequest(BaseModel):
    cron: str
    agent_id: str
    goal: str
    environment: Dict[str, str] = {}

from core.background.scheduler import start_scheduler, add_agent_cron_job

@app.on_event("startup")
def startup_event():
    start_scheduler()

@app.post("/cron", status_code=201)
def create_cron(req: CreateCronRequest):
    agent = registry.get_agent(req.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    try:
        job_id = add_agent_cron_job(req.cron, req.agent_id, req.goal, req.environment)
        return {"job_id": job_id, "status": "scheduled"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
        receipt_dict = json.loads(receipt.model_dump_json())
        update_session(
            conn,
            session_id,
            status=receipt.status,
            run_receipt=receipt_dict
        )
        asyncio.create_task(dispatch_webhook(session_id, receipt.status, receipt_dict))
    except Exception as e:
        update_session(conn, session_id, "failure")
        asyncio.create_task(dispatch_webhook(session_id, "failure"))
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

    # Removed BackgroundTasks for Phase 15. The client initiates streaming by calling GET /stream

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

class InterruptRequest(BaseModel):
    message: str

@app.post("/sessions/{session_id}/interrupt")
def interrupt_session(session_id: str, req: InterruptRequest):
    conn = init_db()
    try:
        session = get_session(conn, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        set_session_interruption(conn, session_id, req.message)
    finally:
        conn.close()
    return {"status": "interruption_queued"}

@app.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str):
    conn = init_db()
    try:
        session = get_session(conn, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session["status"] not in ("pending", "running"):
            raise HTTPException(status_code=400, detail="Session already completed")
            
        update_session(conn, session_id, "running")
        context = build_context(session["goal"], conn)
        goal = context.goal
        
        agent_profile = registry.get_agent(session["agent_id"])
        if not agent_profile:
            update_session(conn, session_id, "failure")
            raise HTTPException(status_code=404, detail="Agent not found")
    finally:
        conn.close()

    async def sse_generator():
        try:
            async for event in run_agent_generator(
                session_id=session_id,
                context=context,
                allowed_tools=agent_profile.allowed_tools,
                agent_profile=agent_profile
            ):
                if event["type"] == "final_receipt":
                    # Update DB
                    conn = init_db()
                    try:
                        receipt_dict = event["receipt"]
                        verification = receipt_dict.get("verification")
                        
                        receipt = RunReceipt(
                            run_id=session_id,
                            goal=goal,
                            agent_id=session["agent_id"],
                            model_used=receipt_dict.get("model_used", agent_profile.model or "unknown"),
                            actions=receipt_dict.get("actions", []),
                            final_text=receipt_dict.get("final_text", ""),
                            status="success" if getattr(verification, "passed", True) else "failure",
                            verification=verification,
                            started_at=goal.created_at,
                            finished_at=datetime.now(timezone.utc),
                        )
                        receipt.candidate_skill = draft_skill_if_warranted(receipt)
                        receipt_dict_dump = json.loads(receipt.model_dump_json())
                        update_session(conn, session_id, status=receipt.status, run_receipt=receipt_dict_dump)
                        asyncio.create_task(dispatch_webhook(session_id, receipt.status, receipt_dict_dump))
                    finally:
                        conn.close()
                    # Strip raw events from SSE stream to avoid serialization errors of LiteLLM MockResponse
                    event_to_yield = dict(event)
                    if "receipt" in event_to_yield and "events" in event_to_yield["receipt"]:
                        receipt_copy = dict(event_to_yield["receipt"])
                        receipt_copy["events"] = []
                        event_to_yield["receipt"] = receipt_copy
                    yield f"data: {json.dumps(event_to_yield)}\n\n"
                else:
                    yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            conn = init_db()
            try:
                update_session(conn, session_id, "failure")
                asyncio.create_task(dispatch_webhook(session_id, "failure"))
            finally:
                conn.close()
            raise
        except Exception as e:
            conn = init_db()
            try:
                update_session(conn, session_id, "failure")
                asyncio.create_task(dispatch_webhook(session_id, "failure"))
            finally:
                conn.close()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


from core.memory.dreamer import run_memory_consolidation

@app.post("/memory/dream")
async def trigger_memory_dream():
    themes = await run_memory_consolidation()
    return {"status": "success", "consolidated_themes": themes or []}
