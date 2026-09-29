"""advisor_consultation: a secondary model gives strategic guidance (credentials resolved per model)."""
from __future__ import annotations

from core.llm import simple_completion
from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.settings import settings
from core.tools import ToolSpec


async def advisor(args: dict, ctx) -> str:
    st = settings()
    prompt = ("You are the Harness Strategy Advisor. The primary agent paused to consult you.\n\n"
              f"Context provided:\n{args['context']}\n\nAgent's query:\n{args['query']}\n\n"
              "Give direct, sharp strategic advice on how the agent should proceed.")
    return "Advisor says: " + await simple_completion(prompt, st, model=st.advisor_model or st.model)


class AdvisorPlugin(Plugin):
    name = "advisor"

    def register(self, ctx: PluginContext) -> None:
        ctx.tool(ToolSpec(
            "advisor_consultation", "Consult a secondary advisor model for strategic guidance.",
            {"type": "object", "properties": {"query": {"type": "string"}, "context": {"type": "string"}},
             "required": ["query", "context"], "additionalProperties": False},
            advisor, capability="Advisor", risk=RiskTier.R1, read_only=True, policy_tool="advisor",
            policy_action="advisor_consultation"))
