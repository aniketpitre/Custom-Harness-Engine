"""Tool registry and the single `invoke()` path every tool goes through.

capability check -> arg validation -> pre_tool hooks -> policy (rules, argument-aware tier,
taint) -> approval broker (args-hash bound) -> pre-state -> handler (timeout, thread for
sync handlers) -> post-state -> output limit/spill/untrusted wrapping -> verify -> post_tool
hook -> ActionRecord.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

from core.approvals import ApprovalBroker, ApprovalRequest, args_hash, get_broker
from core.effects import Disposer, EffectStack
from core.hooks import HookBus
from core.policy import Rule, decide
from core.primitives.execution import ActionRecord
from core.primitives.policy import PolicyDecision, RiskTier
from core.settings import Settings
from core.settings import settings as get_settings
from core.telemetry import get_tracer, tool_counter

_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤﻿\U000e0000-\U000e007f]")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    capability: str = "Generic"
    risk: RiskTier | Callable[[dict, "RunCtx"], RiskTier] = RiskTier.R1
    read_only: bool = False
    parallel_safe: bool = False
    output_limit: int | None = None
    untrusted: bool = False
    policy_tool: str | None = None
    policy_action: str | None = None
    hard_deny: Callable[[dict], str | None] | None = None
    render: Callable[[dict], str] | None = None
    snapshot: tuple[Callable[[dict], dict], Callable[[dict], dict]] | None = None
    verify: Callable[[dict, str], bool] | None = None
    timeout: float | None = None
    owner: str = ""

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}

    def tier(self, args: dict, ctx: "RunCtx") -> RiskTier:
        return self.risk(args, ctx) if callable(self.risk) else self.risk


class RegistrySnapshot:
    """Immutable view of the registry, taken at run start so concurrent runs never interleave."""

    def __init__(self, tools: dict[str, ToolSpec], generation: int) -> None:
        self.tools = MappingProxyType(dict(tools))
        self.generation = generation

    def get(self, name: str) -> ToolSpec | None:
        return self.tools.get(name)

    def schemas(self, allowed: set[str], deny: set[str] = frozenset()) -> list[dict]:
        specs = [s for s in self.tools.values() if s.capability in allowed and s.name not in deny]
        return [s.schema() for s in sorted(specs, key=lambda s: s.name)]


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._generation = 0

    def register(self, spec: ToolSpec) -> Disposer:
        existing = self._tools.get(spec.name)
        if existing is not None and existing.owner != spec.owner:
            raise ValueError(f"Tool name already registered by {existing.owner or 'core'}: {spec.name}")
        tools = dict(self._tools)
        tools[spec.name] = spec
        self._tools, self._generation = tools, self._generation + 1

        def dispose() -> None:
            if self._tools.get(spec.name) is spec:
                remaining = dict(self._tools)
                remaining.pop(spec.name)
                self._tools, self._generation = remaining, self._generation + 1

        return dispose

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(self._tools, self._generation)

    def names(self) -> list[str]:
        return sorted(self._tools)


@dataclass
class Budget:
    """Token budget shared between a run and its subagents."""
    limit: int
    used: int = 0

    def add(self, tokens: int) -> None:
        self.used += max(tokens, 0)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


@dataclass
class RunCtx:
    session_id: str | None
    agent_id: str
    allowed: set[str]
    settings: Settings = field(default_factory=get_settings)
    broker: ApprovalBroker = field(default_factory=get_broker)
    hooks: HookBus = field(default_factory=HookBus)
    rules: list[Rule] = field(default_factory=list)
    deny_tools: set[str] = field(default_factory=set)
    tainted: bool = False
    session_approvals: set[tuple[str, str]] = field(default_factory=set)
    effects: EffectStack = field(default_factory=EffectStack)
    budget: Budget = field(default_factory=lambda: Budget(200_000))
    domain: str = "general"
    depth: int = 0
    engine: Any = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def workspace(self) -> Path:
        return self.settings.workspace


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    record: ActionRecord | None = None


# ---------------------------------------------------------------------------
def sanitize_untrusted(text: str) -> str:
    return _INVISIBLE.sub("", text)


def limit_output(text: str, limit: int, session_id: str | None, tag: str, spill_dir: Path) -> str:
    """Head + tail preview; the full output is written to the spill directory."""
    if len(text) <= limit:
        return text
    spill_dir.mkdir(parents=True, exist_ok=True)
    path = spill_dir / f"{session_id or 'anon'}_{tag}_{uuid.uuid4().hex[:8]}.txt"
    path.write_text(text, encoding="utf-8")
    head, tail = limit // 3, limit - limit // 3
    return (f"{text[:head]}\n...[TRUNCATED {len(text) - limit} chars. Full output: {path}; "
            f"use read_spill to page through it]...\n{text[-tail:]}")


def _validate(schema: dict, args: Any) -> str | None:
    if not isinstance(args, dict):
        return "Arguments must be a JSON object"
    try:
        import jsonschema

        jsonschema.validate(args, schema)
    except ImportError:  # minimal fallback
        missing = [k for k in schema.get("required", []) if k not in args]
        return f"Missing required arguments: {missing}" if missing else None
    except jsonschema.ValidationError as error:
        return f"Invalid arguments: {error.message}"
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record(decision: PolicyDecision, started: datetime, raw: str, *, digest: str | None,
            is_error: bool, pre=None, post=None) -> ActionRecord:
    return ActionRecord(
        tool=decision.tool, action=decision.action, policy_decision=decision,
        approved_by=decision.approved_by, started_at=started, finished_at=_now(),
        raw_result=raw, pre_state_snapshot=pre, post_state_snapshot=post,
        rollback_available=bool(pre and pre.get("rollback")), args_hash=digest, is_error=is_error)


def _deny(name: str, tool: str, action: str, reason: str, tier: RiskTier, started: datetime,
          digest: str | None, message: str | None = None) -> ToolResult:
    decision = PolicyDecision(decision="DENY", risk_tier=tier, reason=reason, tool=tool, action=action)
    content = message or f"DENIED by policy: {reason}"
    return ToolResult(content, True, _record(decision, started, content, digest=digest, is_error=True))


async def _run_handler(spec: ToolSpec, args: dict, ctx: RunCtx) -> Any:
    timeout = spec.timeout or ctx.settings.tool_timeout
    if inspect.iscoroutinefunction(spec.handler):
        coro = spec.handler(args, ctx)
    else:
        coro = asyncio.to_thread(spec.handler, args, ctx)
    return await asyncio.wait_for(coro, timeout)


async def invoke(snapshot: RegistrySnapshot, call_id: str, name: str, args: Any, ctx: RunCtx) -> ToolResult:
    started = _now()
    spec = snapshot.get(name)
    if spec is None:
        return ToolResult(f"Unknown tool: {name}", True, None)
    tool_label = spec.policy_tool or spec.owner or "harness"
    action_label = spec.policy_action or name
    with get_tracer("harness.tools").start_as_current_span(f"tool.{name}") as span:
        span.set_attribute("tool.name", name)
        tool_counter.add(1, {"tool": name})
        if spec.capability not in ctx.allowed or name in ctx.deny_tools:
            return _deny(name, tool_label, action_label, f"Tool is not allowed for this agent: {name}",
                         RiskTier.R4, started, None)
        problem = _validate(spec.parameters, args)
        if problem:
            return ToolResult(problem, True, None)

        pre = await ctx.hooks.emit("pre_tool", {"tool": name, "args": args, "session_id": ctx.session_id})
        if pre.updated_input is not None:
            args = pre.updated_input
            problem = _validate(spec.parameters, args)
            if problem:
                return ToolResult(problem, True, None)
        digest = args_hash(name, args)
        tier = spec.tier(args, ctx)
        hard = spec.hard_deny(args) if spec.hard_deny else None
        remembered = (name, digest) in ctx.session_approvals or ctx.broker.is_remembered(name, digest)
        decision = decide(name=name, policy_tool=tool_label, policy_action=action_label, tier=tier,
                          read_only=spec.read_only, args=args, rules=ctx.rules, tainted=ctx.tainted,
                          pre_approved=remembered, hard_deny_reason=hard)
        from core.telemetry import policy_counter

        policy_counter.add(1, {"decision": decision.decision})
        if pre.decision == "deny":
            decision = decision.model_copy(update={"decision": "DENY", "reason": pre.reason or "Denied by hook"})
        elif pre.decision == "ask" and decision.decision == "ALLOW":
            decision = decision.model_copy(update={
                "decision": "REQUIRE_APPROVAL", "risk_tier": max(decision.risk_tier, RiskTier.R2),
                "reason": pre.reason or "Approval required by hook"})
        span.set_attribute("policy.decision", decision.decision)
        if decision.decision == "DENY":
            return _deny(name, tool_label, action_label, decision.reason, decision.risk_tier, started, digest)

        if decision.decision == "REQUIRE_APPROVAL":
            rendered = spec.render(args) if spec.render else f"{name}\n{arg_preview(args)}"
            result = await ctx.broker.request(ApprovalRequest(
                tool=name, args_hash=digest, rendered=rendered, risk_tier=str(decision.risk_tier),
                session_id=ctx.session_id))
            if not result.approved:
                why = ("Approval timed out; denied" if result.status == "timed_out"
                       else f"Human rejected this action: {result.note or 'no reason given'}")
                return _deny(name, tool_label, action_label, why, decision.risk_tier, started, digest,
                             message=why)
            if args_hash(name, args) != digest:  # arguments must not change after approval
                return _deny(name, tool_label, action_label, "Arguments changed after approval",
                             decision.risk_tier, started, digest)
            if result.scope == "session":
                ctx.session_approvals.add((name, digest))
            decision = decision.model_copy(update={"decision": "ALLOW", "approved_by": result.approver})

        pre_state = post_state = None
        is_error = False
        try:
            if spec.snapshot:
                pre_state = await asyncio.to_thread(spec.snapshot[0], args)
            raw = await _run_handler(spec, args, ctx)
            if spec.snapshot:
                post_state = await asyncio.to_thread(spec.snapshot[1], args)
            content = raw if isinstance(raw, str) else str(raw)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            content, is_error = f"Tool error (Timeout): {name} exceeded its time limit", True
        except PermissionError as error:
            content, is_error = f"DENIED: {error}", True
        except Exception as error:  # noqa: BLE001 - errors go back to the model
            content, is_error = f"Tool error ({type(error).__name__}): {error}", True

        limit = spec.output_limit or ctx.settings.tool_output_limit
        if spec.untrusted and not is_error:
            content = sanitize_untrusted(content)
        content = limit_output(content, limit, ctx.session_id, name, ctx.settings.spill_dir)
        if spec.untrusted and not is_error:
            ctx.tainted = True
            content = f'<external source="{name}" trust="untrusted">\n{content}\n</external>'
        if spec.verify and not is_error:
            try:
                if not spec.verify(args, content):
                    content += "\n[verification failed: post-condition not met]"
                    is_error = True
            except Exception as error:  # noqa: BLE001
                content += f"\n[verification error: {error}]"
        record = _record(decision, started, content, digest=digest, is_error=is_error,
                         pre=pre_state, post=post_state)
        post = await ctx.hooks.emit("post_tool", {"tool": name, "args": args, "result": content,
                                                  "is_error": is_error, "session_id": ctx.session_id})
        if post.additional_context:
            content += "\n" + "\n".join(post.additional_context)
        return ToolResult(content, is_error, record)


def arg_preview(args: dict, limit: int = 1500) -> str:
    import json

    text = json.dumps(args, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + "\n...[truncated]"
