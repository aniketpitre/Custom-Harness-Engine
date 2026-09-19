import asyncio
from typing import Any
from core.primitives.orchestration import Phase, OrchestrationPlan
from core.primitives.context import ContextPacket
from core.primitives.goal import Goal
from core.agent_engine import run_agent
from core.memory.store import get_workflow_checkpoint, save_workflow_checkpoint, init_db
import copy

async def execute_phase(phase: Phase, context: ContextPacket) -> list[dict[str, Any]]:
    tasks = []
    for spec in phase.subagent_specs:
        sub_context = copy.deepcopy(context)
        sub_context.goal = Goal(
            id=f"{context.goal.id}-{spec.id}",
            source=context.goal.source,
            raw_input=spec.goal,
            domain=context.goal.domain,
            created_at=context.goal.created_at
        )
        tasks.append(run_agent(sub_context, allowed_tools=spec.tool_scope))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    final_results = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            final_results.append({"error": str(r), "subagent_id": phase.subagent_specs[i].id})
        else:
            # Strip non-serializable elements before returning for checkpointing
            clean_result = {
                "subagent_id": phase.subagent_specs[i].id,
                "final_text": r.get("final_text"),
                "model_used": r.get("model_used"),
                "actions": [a.model_dump() for a in r.get("actions", [])] if r.get("actions") else [],
            }
            final_results.append(clean_result)
    return final_results

async def execute_plan(plan: OrchestrationPlan, context: ContextPacket) -> list[list[dict[str, Any]]]:
    conn = init_db()
    all_results = []
    
    for _idx, phase in enumerate(plan.phases):
        checkpoint = get_workflow_checkpoint(conn, plan.id, _idx)
        if checkpoint and checkpoint["status"] == "completed":
            print(f"Skipping phase {_idx} ('{phase.name}'), already completed.")
            all_results.append(checkpoint["result_json"])
            continue

        print(f"Executing phase {_idx} ('{phase.name}') with {len(phase.subagent_specs)} subagents...")
        save_workflow_checkpoint(conn, plan.id, _idx, "in_progress")
        
        # Determine if this needs to use results of previous phase as evidence
        if all_results:
            # We add a summary of the previous phase results to the context
            prev_results_summary = f"Results from previous phases: {repr(all_results[-1])}"
            context.live_state["previous_phase_results"] = prev_results_summary

        phase_results = await execute_phase(phase, context)
        save_workflow_checkpoint(conn, plan.id, _idx, "completed", phase_results)
        all_results.append(phase_results)

    return all_results
