"""Control-plane API: authenticated (fail closed), scoped, rate limited; runs are detached from clients."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from core import eventlog
from core.background.scheduler import (
    add_agent_cron_job,
    add_heartbeat,
    list_jobs,
    remove_job,
    scheduler,
    set_paused,
    start_scheduler,
)
from core.engine import get_engine
from core.home import load_env
from core.memory.dreamer import run_memory_consolidation
from core.memory.store import create_session, get_session, init_db, update_session
from core.registry import AgentRegistry
from core.runs import RunManager
from core.secrets import get_secret
from core.settings import settings
from core.skills import discover_skills

load_env()  # $HARNESS_HOME/.env written by `harness init` (real env vars win)
security = HTTPBearer(auto_error=False)
registry = AgentRegistry()
engine = get_engine()
engine.extras["agents"] = registry
runs = RunManager(engine, registry)
_rate: dict[str, deque] = defaultdict(deque)
_telegram = None


# ---------------------------------------------------------------------------
# Authentication, scopes, rate limiting
# ---------------------------------------------------------------------------
def _configured_tokens() -> dict[str, tuple[str, ...]]:
    tokens = dict(settings().api_tokens)
    if not tokens:
        try:  # optional Vault-stored admin token
            tokens[get_secret("harness", "api_token")] = ("*",)
        except Exception:  # noqa: BLE001
            pass
    return tokens


def _scope_ok(scopes: tuple[str, ...], needed: str) -> bool:
    return any(s == "*" or s == needed or (s.endswith(":*") and needed.startswith(s[:-1])) for s in scopes)


def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict[str, Any]:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    tokens = _configured_tokens()
    if not tokens:  # fail closed: there is no default token
        raise HTTPException(status_code=503, detail="API token is not configured (set HARNESS_API_TOKEN)")
    supplied = credentials.credentials.encode()
    match = None
    for token, scopes in tokens.items():
        if hmac.compare_digest(supplied, token.encode()):
            match = (token, scopes)
    if match is None:
        raise HTTPException(status_code=401, detail="Invalid API token")
    ident = hashlib.sha256(match[0].encode()).hexdigest()[:8]
    window, limit = _rate[ident], settings().api_rate_limit
    now = time.monotonic()
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    window.append(now)
    return {"id": ident, "scopes": match[1]}


def scope(needed: str):
    def dependency(auth: dict = Depends(authenticate)) -> dict:
        if not _scope_ok(auth["scopes"], needed):
            raise HTTPException(status_code=403, detail=f"Token lacks scope {needed}")
        return auth

    return dependency


verify_token = authenticate  # backwards-compatible name


# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _telegram
    from core.gateway.channels import start_telegram, terminal_channel

    await engine.ensure_started()
    runs.recover()
    start_scheduler(runs)
    _telegram = start_telegram(engine.broker)
    terminal = terminal_channel(engine.broker)      # live prompt when `harness serve` runs in a terminal
    yield
    if terminal:
        terminal()
    for sid in list(runs.active_ids()):
        runs.cancel(sid)
    if _telegram:
        await _telegram.stop()
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await engine.shutdown()


app = FastAPI(title="Harness Engine Control Plane API", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


# -- agents -----------------------------------------------------------------------------
@app.get("/agents", dependencies=[Depends(scope("agents:read"))])
def list_agents():
    return registry.list_agents()


@app.get("/agents/{agent_id}", dependencies=[Depends(scope("agents:read"))])
def get_agent(agent_id: str):
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


# -- sessions ---------------------------------------------------------------------------
class CreateSessionRequest(BaseModel):
    agent_id: str
    goal: str
    environment: Dict[str, str] = {}
    verification: Optional[Dict[str, Any]] = None
    run: bool = False
    permission_mode: Optional[str] = None   # default | plan | read-only | strict


def _conn():
    return init_db()


@app.post("/sessions", status_code=201, dependencies=[Depends(scope("sessions:write"))])
async def start_session(req: CreateSessionRequest):
    if not registry.get_agent(req.agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    from core.modes import normalize

    try:
        mode = normalize(req.permission_mode)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session_id = str(uuid.uuid4())
    conn = _conn()
    try:
        create_session(conn, session_id, req.agent_id, req.goal, req.environment, verification=req.verification,
                       permission_mode=mode)
    finally:
        conn.close()
    if req.run:
        await runs.start(session_id)
        return {"session_id": session_id, "status": "running"}
    return {"session_id": session_id, "status": "pending"}


@app.post("/sessions/{session_id}/run", status_code=202, dependencies=[Depends(scope("sessions:write"))])
async def run_session(session_id: str):
    _require(session_id)
    if not await runs.start(session_id):
        raise HTTPException(status_code=409, detail="Session is not pending (already running or finished)")
    return {"session_id": session_id, "status": "running"}


def _require(session_id: str) -> dict:
    conn = _conn()
    try:
        session = get_session(conn, session_id)
    finally:
        conn.close()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/sessions", dependencies=[Depends(scope("sessions:read"))])
def list_sessions(limit: int = 50, status: Optional[str] = None, agent_id: Optional[str] = None,
                  include_children: bool = False):
    """Recent sessions, newest first, with tokens and cost (no transcripts)."""
    where, params = [], []
    if not include_children:
        where.append("parent_session_id IS NULL")
    if status:
        where.append("status = ?")
        params.append(status)
    if agent_id:
        where.append("agent_id = ?")
        params.append(agent_id)
    sql = ("SELECT id, agent_id, goal, status, outcome, verified, parent_session_id, prompt_tokens, "
           "completion_tokens, cost_usd, created_at, updated_at FROM sessions"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated_at DESC LIMIT ?")
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute(sql, (*params, max(1, min(limit, 500)))).fetchall()]
    finally:
        conn.close()
    for r in rows:
        r["verified"] = None if r["verified"] is None else bool(r["verified"])
        r["active"] = runs.is_active(r["id"])
    return rows


@app.get("/usage", dependencies=[Depends(scope("sessions:read"))])
def usage(days: int = 30, by: str = "model"):
    """Tokens and USD from the event log, grouped by model, agent, day or session."""
    from datetime import timedelta

    from core.memory.store import usage_summary

    if by not in {"model", "agent", "day", "session"}:
        raise HTTPException(status_code=422, detail="by must be model, agent, day or session")
    since = (datetime.now(timezone.utc) - timedelta(days=max(days, 1))).isoformat()
    conn = _conn()
    try:
        rows = usage_summary(conn, since=since, group_by=by)
    finally:
        conn.close()
    return {"days": days, "by": by, "rows": rows,
            "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
            "total_tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows),
            "unpriced_calls": sum(r["unpriced_calls"] for r in rows)}


@app.get("/sessions/{session_id}", dependencies=[Depends(scope("sessions:read"))])
def retrieve_session(session_id: str):
    session = _require(session_id)
    session["active"] = runs.is_active(session_id)
    return session


@app.get("/sessions/{session_id}/events", dependencies=[Depends(scope("sessions:read"))])
def session_events(session_id: str, after: int = 0):
    _require(session_id)
    conn = _conn()
    try:
        return eventlog.list_events(conn, session_id, after_seq=after)
    finally:
        conn.close()


@app.get("/sessions/{session_id}/verify-chain", dependencies=[Depends(scope("sessions:read"))])
def verify_chain(session_id: str):
    _require(session_id)
    conn = _conn()
    try:
        ok, bad = eventlog.verify_chain(conn, session_id)
        return {"ok": ok, "first_bad_seq": bad, "head": eventlog.chain_head(conn, session_id)}
    finally:
        conn.close()


class InterruptRequest(BaseModel):
    message: str


@app.post("/sessions/{session_id}/interrupt", dependencies=[Depends(scope("sessions:write"))])
def interrupt_session(session_id: str, req: InterruptRequest):
    _require(session_id)
    conn = _conn()
    try:
        eventlog.append_event(conn, session_id, "interrupt_queued", {"content": req.message})
    finally:
        conn.close()
    return {"status": "interruption_queued"}


@app.post("/sessions/{session_id}/cancel", dependencies=[Depends(scope("sessions:write"))])
def cancel_session(session_id: str):
    _require(session_id)
    return {"status": "cancelling" if runs.cancel(session_id) else "not_running"}


class ForkSessionRequest(BaseModel):
    goal_override: str | None = None
    event_id: str | None = None


@app.post("/sessions/{session_id}/fork", status_code=201, dependencies=[Depends(scope("sessions:write"))])
def fork_session(session_id: str, req: ForkSessionRequest):
    session = _require(session_id)
    new_id = str(uuid.uuid4())
    conn = _conn()
    try:
        goal = req.goal_override or session["goal"]
        create_session(conn, new_id, session["agent_id"], goal, session["environment"],
                       parent_session_id=session_id, parent_event_id=req.event_id,
                       verification=session.get("verification"), permission_mode=session.get("permission_mode"))
        try:
            copied = eventlog.fork_events(conn, session_id, new_id, req.event_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if copied == 0 and (session.get("run_receipt") or {}).get("message_history"):
            for m in session["run_receipt"]["message_history"]:  # legacy receipts without an event log
                if m.get("role") == "user":
                    eventlog.append_event(conn, new_id, "user_msg", {"content": m["content"]})
                elif m.get("role") == "assistant" and not m.get("tool_calls"):
                    eventlog.append_event(conn, new_id, "assistant_msg", {"content": m.get("content")})
        if req.goal_override:
            eventlog.append_event(conn, new_id, "user_msg", {"content": req.goal_override})
    finally:
        conn.close()
    return {"session_id": new_id, "status": "pending"}


class RewindRequest(BaseModel):
    action_index: int


@app.post("/sessions/{session_id}/rewind", dependencies=[Depends(scope("sessions:write"))])
def rewind(session_id: str, req: RewindRequest):
    """Restore a file changed by a write/edit action from its recorded checkpoint."""
    from domains.generic.fs import restore_checkpoint

    _require(session_id)
    conn = _conn()
    try:
        actions = eventlog.list_events(conn, session_id, types={"action"})
    finally:
        conn.close()
    if not 0 <= req.action_index < len(actions):
        raise HTTPException(status_code=404, detail="No such action")
    pre = actions[req.action_index]["payload"].get("pre_state_snapshot")
    if not pre or not pre.get("rollback"):
        raise HTTPException(status_code=400, detail="Action has no checkpoint")
    return {"result": restore_checkpoint(pre)}


def _replay_events(session_id: str, session: dict):
    """Durable-log replay for sessions without a live buffer (finished, or after a restart)."""
    conn = _conn()
    try:
        for e in eventlog.list_events(conn, session_id):
            p, t = e["payload"], e["type"]
            if t == "user_msg":
                yield {"type": "user_message", "content": p["content"]}
            elif t == "assistant_msg":
                if p.get("content"):
                    yield {"type": "message", "content": p["content"]}
                for tc in p.get("tool_calls") or []:
                    yield {"type": "tool_call", "name": tc["function"]["name"],
                           "arguments": json.loads(tc["function"].get("arguments") or "{}")}
            elif t == "tool_result":
                yield {"type": "tool_result", "result_summary": p["content"][:256], "is_error": p.get("is_error")}
            elif t == "compaction":
                yield {"type": "message", "content": "Compacted conversation history."}
    finally:
        conn.close()
    if session.get("run_receipt"):
        yield {"type": "final_receipt", "receipt": session["run_receipt"]}


@app.get("/sessions/{session_id}/stream", dependencies=[Depends(scope("sessions:read"))])
async def stream_session(session_id: str, request: Request):
    session = _require(session_id)
    if session["status"] == "pending" and not runs.is_active(session_id):
        if not registry.get_agent(session["agent_id"]):
            conn = _conn()
            try:
                update_session(conn, session_id, "failure", outcome="error")
            finally:
                conn.close()
            raise HTTPException(status_code=404, detail="Agent not found")
        await runs.start(session_id)  # the run is detached: closing this stream does not cancel it
    last_id = int(request.headers.get("last-event-id") or 0)
    buf = runs.buffers.get(session_id)

    async def sse():
        if buf is None:
            for ev in _replay_events(session_id, _require(session_id)):
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            return
        async for eid, event in buf.tail(last_id):
            if event.get("type") == "keepalive":
                yield ": keepalive\n\n"
                continue
            yield f"id: {eid}\ndata: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


# -- approvals --------------------------------------------------------------------------
@app.get("/approvals", dependencies=[Depends(scope("approvals:read"))])
def pending_approvals():
    return engine.broker.pending()


class ApprovalDecision(BaseModel):
    approved: bool
    scope: str = "once"
    note: str | None = None


@app.post("/approvals/{approval_id}", dependencies=[Depends(scope("approvals:write"))])
def decide_approval(approval_id: str, decision: ApprovalDecision, auth: dict = Depends(authenticate)):
    approver = f"api:{auth['id']}"
    if not engine.broker.resolve(approval_id, decision.approved, approver, decision.scope, decision.note):
        raise HTTPException(status_code=409, detail="Unknown, already resolved, or approver not authorised")
    return {"status": "approved" if decision.approved else "denied", "approver": approver}


# -- scheduling -------------------------------------------------------------------------
class CreateCronRequest(BaseModel):
    cron: str
    agent_id: str
    goal: str
    environment: Dict[str, str] = {}
    timezone: str | None = None


@app.post("/cron", status_code=201, dependencies=[Depends(scope("cron:write"))])
def create_cron(req: CreateCronRequest):
    if not registry.get_agent(req.agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        job_id = add_agent_cron_job(req.cron, req.agent_id, req.goal, req.environment, req.timezone)
    except Exception as e:  # noqa: BLE001 - bad cron expression / timezone
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"job_id": job_id, "status": "scheduled"}


@app.get("/cron", dependencies=[Depends(scope("cron:read"))])
def get_cron():
    return list_jobs()


@app.delete("/cron/{job_id}", dependencies=[Depends(scope("cron:write"))])
def delete_cron(job_id: str):
    if not remove_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "deleted"}


@app.post("/cron/{job_id}/{action}", dependencies=[Depends(scope("cron:write"))])
def pause_cron(job_id: str, action: str):
    if action not in {"pause", "resume"}:
        raise HTTPException(status_code=404, detail="Unknown action")
    if not set_paused(job_id, action == "pause"):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": action + "d"}


class HeartbeatRequest(BaseModel):
    agent_id: str
    interval_minutes: int
    goal: str = "Heartbeat check"


@app.post("/heartbeat", status_code=201, dependencies=[Depends(scope("cron:write"))])
def create_heartbeat(req: HeartbeatRequest):
    if not registry.get_agent(req.agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        return {"job_id": add_heartbeat(req.agent_id, req.interval_minutes, req.goal)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# -- memory, skills, admin --------------------------------------------------------------
@app.post("/memory/dream", dependencies=[Depends(scope("memory:write"))])
async def trigger_memory_dream():
    themes = await run_memory_consolidation()
    return {"status": "success", "consolidated_themes": themes or []}


@app.get("/skills", dependencies=[Depends(scope("skills:read"))])
def list_skills():
    return [{"name": s.name, "description": s.description, "version": s.version, "authorship": s.authorship}
            for s in discover_skills()]


@app.post("/sessions/{session_id}/skill/promote", dependencies=[Depends(scope("skills:write"))])
async def promote_skill(session_id: str):
    from core.primitives.learning import CandidateSkill, promote_candidate_skill

    receipt = _require(session_id).get("run_receipt") or {}
    if not receipt.get("candidate_skill"):
        raise HTTPException(status_code=404, detail="No candidate skill for this session")
    candidate = await promote_candidate_skill(CandidateSkill.model_validate(receipt["candidate_skill"]))
    return {"status": candidate.status.value, "name": candidate.name}


@app.get("/admin/plugins", dependencies=[Depends(scope("admin"))])
def plugin_status():
    return engine.plugins.status()


@app.post("/admin/reload", dependencies=[Depends(scope("admin"))])
async def reload_all():
    from core.plugins.dynamic import load_dynamic_tools

    agents_ok = registry.reload()
    await load_dynamic_tools(engine)
    return {"agents": agents_ok, "plugins": engine.plugins.status()}
