"""The default plugin set. Domain packs load lazily: heavy imports happen inside handlers."""
from __future__ import annotations

from core.plugins.base import Plugin


def builtin_plugins() -> list[Plugin]:
    from core.plugins.advisor import AdvisorPlugin
    from core.plugins.dynamic import SelfEditPlugin
    from core.plugins.memory_tool import MemoryPlugin
    from core.plugins.skills_tool import SkillsPlugin
    from core.plugins.subagents_tool import SubagentsPlugin
    from domains.devops.plugin import DevOpsPlugin
    from domains.generic.fs import FsPlugin
    from domains.generic.shell import ShellPlugin
    from domains.generic.web import WebPlugin

    return [FsPlugin(), WebPlugin(), ShellPlugin(), MemoryPlugin(), SkillsPlugin(), AdvisorPlugin(),
            SubagentsPlugin(), SelfEditPlugin(), DevOpsPlugin(), PlanPlugin()]


class PlanPlugin(Plugin):
    """`exit_plan_mode`: only offered to runs in plan mode (capability "Plan" is granted by the loop)."""
    name = "plan"

    def register(self, ctx) -> None:
        from core.modes import exit_plan_mode
        from core.primitives.policy import RiskTier
        from core.tools import ToolSpec

        ctx.tool(ToolSpec(
            "exit_plan_mode", "Present your plan for approval. Call this once you have investigated and know "
            "exactly what you will change; on approval you may carry it out.",
            {"type": "object", "properties": {"plan": {"type": "string", "description": "Step-by-step plan, "
             "including the exact changes and how you will verify them"}},
             "required": ["plan"], "additionalProperties": False},
            exit_plan_mode, capability="Plan", risk=RiskTier.R0, read_only=True, policy_tool="harness",
            policy_action="exit_plan_mode", timeout=24 * 3600))
