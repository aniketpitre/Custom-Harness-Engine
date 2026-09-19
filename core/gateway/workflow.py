import asyncio
import uuid
import sys
import argparse
from datetime import datetime
from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.primitives.orchestration import OrchestrationPlan, Phase, SubagentSpec
from core.orchestration.executor import execute_plan

async def run_audit_workflow(resume=False):
    # Step 12.5 Test Case Plan
    spec_audit = SubagentSpec(
        id="auditor",
        goal="Audit every Kubernetes namespace for pods with privileged: true or missing resource limits.",
        tool_scope=["DevOpsRead"]
    )
    phase_audit = Phase(name="Audit Cluster", subagent_specs=[spec_audit])

    spec_verify = SubagentSpec(
        id="cross-checker",
        goal="Cross-check the privileged pod findings from the previous phase against Git manifests. Report only confirmed issues that exist both in live clusters and in Git.",
        tool_scope=["DevOpsRead", "Read"]
    )
    phase_verify = Phase(name="Adversarial Cross Check", subagent_specs=[spec_verify])

    plan = OrchestrationPlan(
        id="audit-wf-v1" if resume else f"audit-wf-{uuid.uuid4().hex[:8]}",
        goal="Security audit of infrastructure across live state and git manifests",
        phases=[phase_audit, phase_verify]
    )

    context = ContextPacket(
        goal=Goal(
            id=str(uuid.uuid4()),
            source=TriggerSource.cli,
            raw_input=plan.goal,
            created_at=datetime.utcnow(),
            domain="devops"
        ),
        memory_hits=[],
        live_state={},
        recent_history=[],
        tool_catalog=[]
    )

    print(f"Starting orchestration plan: {plan.goal}")
    print(f"Workflow ID: {plan.id}\n")
    
    try:
        results = await execute_plan(plan, context)
        print("\n=== FINAL CONFIRMED ISSUES ===")
        # The final phase contains the cross-checked issues
        for idx, subagent_res in enumerate(results[-1]):
            if "error" in subagent_res:
                print(f"Subagent Error: {subagent_res['error']}")
            else:
                print(subagent_res.get("final_text", "No final text returned."))
    except Exception as e:
        print(f"Workflow failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Phase 12 Security Audit Workflow")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoints if available")
    args = parser.parse_args()
    asyncio.run(run_audit_workflow(resume=args.resume))
