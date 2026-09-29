"""Policy engine: hard blocklist -> rules (deny > ask > allow) -> argument-aware tier -> taint.

Hooks may tighten a decision but never loosen a DENY (see core/tools.py).
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from typing import Any

from core.primitives.policy import PolicyDecision, RiskTier

_ORDER = [RiskTier.R0, RiskTier.R1, RiskTier.R2, RiskTier.R3, RiskTier.R4]


@dataclass(frozen=True)
class Rule:
    effect: str  # deny | ask | allow
    tool: str
    arg: str | None = None

    def matches(self, tool: str, arg_text: str) -> bool:
        if not fnmatch.fnmatch(tool, self.tool):
            return False
        return self.arg is None or fnmatch.fnmatch(arg_text, self.arg)


def parse_rule(text: str) -> Rule:
    """`deny:bash(rm *)`, `ask:web_fetch`, `allow:kubectl_get_*`."""
    effect, _, spec = text.partition(":")
    effect = effect.strip().lower()
    if effect not in {"deny", "ask", "allow"} or not spec:
        raise ValueError(f"Invalid policy rule: {text!r}")
    tool, arg = spec.strip(), None
    if tool.endswith(")") and "(" in tool:
        tool, _, arg = tool[:-1].partition("(")
    return Rule(effect, tool.strip(), arg)


def bump(tier: RiskTier) -> RiskTier:
    return _ORDER[min(_ORDER.index(tier) + 1, len(_ORDER) - 1)]


def arg_text(args: dict[str, Any]) -> str:
    for key in ("command", "path", "url", "app_name", "tool_name", "query", "file_path"):
        if isinstance(args.get(key), str):
            return args[key]
    return json.dumps(args, sort_keys=True, default=str)


def decide(
    *,
    name: str,
    policy_tool: str,
    policy_action: str,
    tier: RiskTier,
    read_only: bool,
    args: dict[str, Any],
    rules: list[Rule],
    tainted: bool,
    pre_approved: bool = False,
    hard_deny_reason: str | None = None,
    mode: str = "default",
) -> PolicyDecision:
    def make(decision: str, tier_: RiskTier, reason: str, approved_by: str | None = None):
        return PolicyDecision(decision=decision, risk_tier=tier_, reason=reason,
                              tool=policy_tool, action=policy_action, approved_by=approved_by)

    if hard_deny_reason:
        return make("DENY", RiskTier.R4, f"Blocked: {hard_deny_reason}")
    text = arg_text(args)
    for rule in rules:
        if rule.effect == "deny" and rule.matches(name, text):
            return make("DENY", tier, f"Denied by rule deny:{rule.tool}")
    if tier is RiskTier.R4:
        return make("DENY", tier, "Destructive actions are denied by default")
    if mode in {"plan", "read-only"} and not read_only:
        hint = " Investigate, then call exit_plan_mode with your plan." if mode == "plan" else ""
        return make("DENY", tier, f"{mode} mode allows read-only tools only.{hint}")
    effective = tier
    if mode == "strict":
        pre_approved = False
        rules = [r for r in rules if r.effect != "allow"]
    if tainted and not read_only:
        effective = min(bump(tier), RiskTier.R3)  # untrusted content entered the context this run
    for rule in rules:
        if rule.effect == "ask" and rule.matches(name, text):
            return make("REQUIRE_APPROVAL", max(effective, RiskTier.R2), f"Approval required by rule ask:{rule.tool}")
    if effective in {RiskTier.R2, RiskTier.R3}:
        if pre_approved and effective is not RiskTier.R3:
            return make("ALLOW", effective, "Previously approved for these exact arguments", "remembered")
        for rule in rules:
            if rule.effect == "allow" and rule.matches(name, text) and not tainted and effective is RiskTier.R2:
                return make("ALLOW", effective, f"Allowed by rule allow:{rule.tool}", "rule")
        why = "Human approval is required for this risk tier"
        if tainted and effective is not tier:
            why += " (raised because untrusted content entered the context)"
        return make("REQUIRE_APPROVAL", effective, why)
    if mode == "strict" and not read_only:
        return make("REQUIRE_APPROVAL", effective, "strict mode: every change needs approval")
    return make("ALLOW", effective, "Action is allowed by the policy table")
