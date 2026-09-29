"""Permission modes: how much the agent may do without asking, on top of the policy table.

- default:   R0/R1 run, R2/R3 ask, R4 is denied (the policy table as configured).
- plan:      read-only. The agent investigates, then calls `exit_plan_mode` with its plan; a human approves it
             (terminal, API or Telegram) and the run continues in `after_plan` mode (default: `default`).
             Rejecting returns the note to the agent so it can revise the plan.
- read-only: read-only for the whole run, with no way out. For investigations, audits and CI checks.
- strict:    every non-read-only action needs approval, including R1 edits; remembered approvals and allow
             rules are ignored.

There is deliberately no "bypass" mode: R4 stays denied and R3 always asks.
Subagents inherit the mode; a subagent of a planning run is read-only.
"""
from __future__ import annotations

import os

MODES = ("default", "plan", "read-only", "strict")
READ_ONLY_MODES = {"plan", "read-only"}


NOTES = {
    "plan": "\n\n[Plan mode] You can only use read-only tools. Investigate, then call exit_plan_mode with a "
            "concrete plan; you may make changes only after it is approved.",
    "read-only": "\n\n[Read-only mode] Only read-only tools are available. Report findings and recommendations; "
                 "do not attempt changes.",
}


def normalize(mode: str | None) -> str | None:
    if not mode:
        return None
    m = mode.strip().lower().replace("_", "-")
    m = {"readonly": "read-only", "ro": "read-only"}.get(m, m)
    if m not in MODES:
        raise ValueError(f"Unknown permission mode {mode!r}; choose from {', '.join(MODES)}")
    return m


def default_mode() -> str:
    try:
        return normalize(os.environ.get("HARNESS_PERMISSION_MODE")) or "default"
    except ValueError:
        return "default"


def child_mode(mode: str) -> str:
    """Mode for a subagent spawned under `mode`."""
    return "read-only" if mode in READ_ONLY_MODES else mode


async def exit_plan_mode(args: dict, ctx) -> str:
    """Ask a human to approve the plan; on approval the run leaves plan mode."""
    from core.approvals import ApprovalRequest, args_hash

    if ctx.mode != "plan":
        return f"Not in plan mode (current mode: {ctx.mode}); carry on."
    plan = str(args.get("plan", "")).strip()
    if not plan:
        return "Write the plan in the `plan` argument."
    result = await ctx.broker.request(ApprovalRequest(
        tool="exit_plan_mode", args_hash=args_hash("exit_plan_mode", {"plan": plan}),
        rendered=f"PLAN (approve to let the agent carry it out):\n\n{plan}", risk_tier="R2",
        session_id=ctx.session_id))
    if not result.approved:
        why = "no response before the timeout" if result.status == "timed_out" else (result.note or "no reason given")
        return f"Plan not approved ({why}). Stay in plan mode: revise the plan and call exit_plan_mode again."
    new_mode = ctx.extras.get("after_plan") or "default"
    ctx.mode = new_mode
    ctx.allowed.discard("Plan")
    ctx.extras["refresh_tools"] = True
    sink = ctx.extras.get("sink")
    if sink is not None:
        sink.append("mode_change", {"from": "plan", "to": new_mode, "approved_by": result.approver, "plan": plan})
    return (f"Plan approved by {result.approver}. You are now in {new_mode} mode: carry out the plan. "
            "Actions still go through the normal policy and approvals.")
