"""Phased multi-agent workflows: fan-out per phase, checkpoints for resume, shared budget."""
from __future__ import annotations

import asyncio
import copy
import json
from typing import Any

from core.engine import Engine, expand_capabilities, get_engine
from core.memory.store import get_workflow_checkpoint, init_db, save_workflow_checkpoint
from core.primitives.context import ContextPacket
from core.primitives.orchestration import OrchestrationPlan, Phase
from core.settings import settings
from core.subagents import run_subagent
from core.tools import Budget, RunCtx


async def execute_phase(phase: Phase, context: ContextPacket, engine: Engine | None = None,
                        budget: Budget | None = None) -> list[dict[str, Any]]:
    engine = engine or get_engine()
    await engine.ensure_started()
    st = settings()
    allowed = set().union(*(expand_capabilities(s.tool_scope) for s in phase.subagent_specs)) | {"Subagents"}
    parent = RunCtx(session_id=None, agent_id=f"workflow:{phase.name}", allowed=allowed, settings=st,
                    broker=engine.broker, hooks=engine.hooks, budget=budget or Budget(st.token_budget),
                    domain=context.goal.domain, engine=engine, extras={"context": copy.deepcopy(context)})
    agents = engine.extras.get("agents")

    async def one(spec) -> dict[str, Any]:
        profile = agents.get_agent(spec.agent_id) if (agents and spec.agent_id) else None
        result = await run_subagent(parent, spec.goal, profile=profile, capabilities=spec.tool_scope or None,
                                    label=spec.id)
        return {"subagent_id": spec.id, **result}

    results = await asyncio.gather(*(one(s) for s in phase.subagent_specs), return_exceptions=True)
    return [({"subagent_id": phase.subagent_specs[i].id, "error": str(r), "status": "failure"}
             if isinstance(r, BaseException) else r) for i, r in enumerate(results)]


async def execute_plan(plan: OrchestrationPlan, context: ContextPacket, engine: Engine | None = None,
                       db_path=None) -> list[list[dict[str, Any]]]:
    conn = init_db(db_path) if db_path else init_db()
    budget = Budget(settings().token_budget)
    all_results: list[list[dict[str, Any]]] = []
    try:
        for idx, phase in enumerate(plan.phases):
            checkpoint = get_workflow_checkpoint(conn, plan.id, idx)
            if checkpoint and checkpoint["status"] == "completed":
                all_results.append(checkpoint["result_json"])
                continue
            save_workflow_checkpoint(conn, plan.id, idx, "in_progress")
            phase_context = copy.deepcopy(context)  # never mutate the caller's context
            if all_results:
                phase_context.live_state["previous_phase_results"] = json.dumps(all_results[-1], default=str)
            results = await execute_phase(phase, phase_context, engine, budget)
            save_workflow_checkpoint(conn, plan.id, idx, "completed", results)
            all_results.append(results)
        return all_results
    finally:
        conn.close()
