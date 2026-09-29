from __future__ import annotations

import json

from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.subagents import run_subagent
from core.tools import ToolSpec


async def spawn_agent(args: dict, ctx) -> str:
    profile = None
    if args.get("agent_id"):
        agents = ctx.engine.extras.get("agents")
        profile = agents.get_agent(args["agent_id"]) if agents else None
        if profile is None:
            raise ValueError(f"Unknown agent profile: {args['agent_id']}")
    result = await run_subagent(ctx, args["goal"], profile=profile, capabilities=args.get("tools"))
    return json.dumps(result, default=str)


class SubagentsPlugin(Plugin):
    name = "subagents"

    def register(self, ctx: PluginContext) -> None:
        ctx.tool(ToolSpec(
            "spawn_agent", "Delegate a goal to a subagent (optionally a named profile). It can use at most "
            "the capabilities you have and shares your token budget.",
            {"type": "object", "properties": {"goal": {"type": "string"}, "agent_id": {"type": "string"},
                                              "tools": {"type": "array", "items": {"type": "string"}}},
             "required": ["goal"], "additionalProperties": False},
            spawn_agent, capability="Subagents", risk=RiskTier.R1, policy_tool="subagents",
            policy_action="spawn", timeout=3600))
