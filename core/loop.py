"""The agent loop: streaming, errors-as-results, parallel read-only tools, retries/failover,
budgets, token-based compaction, interrupts, verification and receipts - all over the event log."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from core import eventlog
from core.compaction import apply_pruned, estimate_tokens, needs_compaction, plan_compaction, prune_tool_outputs
from core.engine import Engine, expand_capabilities, get_engine
from core.llm import ContextOverflow, LLMError, ToolCall, complete, simple_completion
from core.memory.store import init_db, record_memory_use
from core.policy import parse_rule
from core.primitives.agent import AgentProfile
from core.primitives.context import ContextPacket
from core.primitives.execution import ActionRecord
from core.primitives.verification import VerificationResult
from core.prompt import build_prompt, build_system_prompt
from core.settings import settings as get_settings
from core.telemetry import get_tracer, init_tracing, run_counter
from core.tools import Budget, RunCtx, ToolResult, invoke
from core.verifiers import run_verification

log = logging.getLogger("harness.loop")
LOOP_GUARD_REPEATS = 3
MAX_STOP_CONTINUATIONS = 2


@dataclass
class RunState:
    outcome: str = "error"
    final_text: str = ""
    model: str = ""
    error: str | None = None
    usage: dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0, "turns": 0})
    started: float = field(default_factory=time.monotonic)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DBSink:
    """Event sink over the SQLite log. An in-memory database is used for sessionless runs."""

    def __init__(self, conn, session_id: str) -> None:
        self.conn, self.session_id = conn, session_id

    def append(self, type_: str, payload: dict) -> dict:
        return eventlog.append_event(self.conn, self.session_id, type_, payload)

    def pairs(self):
        return eventlog.messages_with_seqs(self.conn, self.session_id)

    def drain_interrupts(self) -> list[str]:
        return eventlog.drain_interrupts(self.conn, self.session_id)

    def events(self, types: set[str] | None = None):
        return eventlog.list_events(self.conn, self.session_id, types=types)


def _seed_history(sink: DBSink, history: list[dict]) -> None:
    for m in history:
        role = m.get("role")
        if role == "system":
            continue
        if role == "user":
            sink.append("user_msg", {"content": m["content"]})
        elif role == "assistant":
            sink.append("assistant_msg", {"content": m.get("content"), "tool_calls": m.get("tool_calls")})
        elif role == "tool":
            sink.append("tool_result", {"tool_call_id": m["tool_call_id"], "content": m["content"],
                                        "is_error": False})


def _parse_args(tc: ToolCall) -> tuple[dict | None, str | None]:
    try:
        args = json.loads(tc.arguments or "{}")
    except json.JSONDecodeError as error:
        return None, f"Invalid JSON arguments: {error}"
    return (args, None) if isinstance(args, dict) else (None, "Arguments must be a JSON object")


async def _execute_calls(engine, snapshot, calls: list[tuple[ToolCall, dict | None, str | None]],
                         ctx: RunCtx, sem: asyncio.Semaphore) -> list[ToolResult]:
    """Run tool calls: consecutive parallel-safe read-only calls together, the rest in order."""
    results: list[ToolResult | None] = [None] * len(calls)

    async def one(i: int) -> None:
        tc, args, err = calls[i]
        if err:
            results[i] = ToolResult(err, True, None)
            return
        async with sem:
            results[i] = await invoke(snapshot, tc.id, tc.name, args, ctx)

    def parallel(i: int) -> bool:
        spec = snapshot.get(calls[i][0].name)
        return bool(spec and spec.parallel_safe and spec.read_only and not calls[i][2])

    i = 0
    while i < len(calls):
        j = i
        while j < len(calls) and parallel(j):
            j += 1
        if j > i + 1:
            await asyncio.gather(*(one(k) for k in range(i, j)))
            i = j
        else:
            await one(i)
            i += 1
    return [r for r in results if r is not None]


async def _summarize(prompt: str, st, model: str) -> str:
    return await simple_completion(prompt, st, model=st.compact_model or model)


async def _flush_memory(engine, snapshot, ctx: RunCtx, messages: list[dict], models: list[str], st) -> None:
    """Ask the model to persist durable facts before compaction discards old context."""
    spec = snapshot.get("memory")
    if not (st.memory_flush and spec and spec.capability in ctx.allowed):
        return
    prompt = {"role": "user", "content": (
        "Context is about to be compacted. Save any durable facts worth remembering with the "
        "memory tool now (short, factual). If there is nothing to save, reply DONE.")}
    try:
        res = await complete(models, messages + [prompt], [spec.schema()], st)
    except LLMError:
        return
    ctx.budget.add(res.total_tokens)
    for tc in res.tool_calls:
        args, err = _parse_args(tc)
        if not err and tc.name == "memory":
            await invoke(snapshot, tc.id, "memory", args, ctx)


async def run_agent_generator(
    session_id: str | None,
    context: ContextPacket,
    allowed_tools: list[str],
    agent_profile: AgentProfile | None = None,
    initial_history: list[dict[str, Any]] | None = None,
    *,
    engine: Engine | None = None,
    sink: DBSink | None = None,
    budget: Budget | None = None,
    depth: int = 0,
    agent_id: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    init_tracing()
    engine = engine or get_engine()
    await engine.ensure_started()
    st = get_settings()
    own_conn = None
    if sink is None:
        own_conn = init_db(st.db_path if session_id else ":memory:")
        sink = DBSink(own_conn, session_id or "ephemeral")
    state = RunState()
    profile = agent_profile
    models = [(profile.model if profile and profile.model else None) or st.model, *st.fallback_models]
    state.model = models[0]
    domain = (profile.domain if profile else None) or context.goal.domain
    ctx = RunCtx(
        session_id=session_id, agent_id=agent_id or (profile.id if profile else "default-agent"),
        allowed=expand_capabilities(allowed_tools), settings=st, broker=engine.broker, hooks=engine.hooks,
        rules=[parse_rule(r) for r in (profile.rules if profile else [])],
        deny_tools=set(profile.deny_tools) if profile else set(),
        budget=budget or Budget((profile.token_budget if profile and profile.token_budget else st.token_budget)),
        domain=domain, depth=depth, engine=engine, extras={"sink": sink, "context": context})
    max_turns = (profile.max_turns if profile and profile.max_turns else st.max_turns)
    snapshot = engine.snapshot()
    tools = snapshot.schemas(ctx.allowed, ctx.deny_tools)
    prompt_conn = init_db(st.db_path)  # curated memory always comes from the real database
    try:
        system = {"role": "system", "content": build_system_prompt(
            profile, conn=prompt_conn, domain=domain, workspace=st.workspace, memory_limit=st.memory_limit_chars)}
    finally:
        prompt_conn.close()

    if initial_history and not sink.pairs():
        _seed_history(sink, initial_history)
    pairs = sink.pairs()
    if not pairs or pairs[-1][1]["role"] == "assistant":
        sink.append("user_msg", {"content": build_prompt(context)})
        hits = [h["id"] for h in context.memory_hits if "id" in h]
        if hits:
            use_conn = init_db(st.db_path)
            try:
                record_memory_use(use_conn, hits)
            finally:
                use_conn.close()
    sink.append("run_start", {"model": state.model, "agent_id": ctx.agent_id, "goal": context.goal.raw_input,
                              "system_sha256": hashlib.sha256(system["content"].encode()).hexdigest(),
                              "tools": [t["function"]["name"] for t in tools], "generation": snapshot.generation})
    await engine.hooks.emit("session_start", {"session_id": session_id, "agent_id": ctx.agent_id})
    run_counter.add(1, {"agent": ctx.agent_id})
    sem = asyncio.Semaphore(st.max_parallel_tools)
    stop_forced = 0
    last_prompt_tokens = 0
    loop_key, loop_count = None, 0
    span_cm = get_tracer("harness.loop").start_as_current_span("harness_agent_run")
    span = span_cm.__enter__()
    span.set_attribute("agent.goal", context.goal.raw_input)
    span.set_attribute("agent.domain", domain)
    span.set_attribute("agent.trigger_source", context.goal.source.value)

    async def compact(force: bool = False) -> bool:
        nonlocal system
        cur = sink.pairs()
        msgs = [system] + [m for _s, m in cur]
        if not force and not needs_compaction(msgs, st.context_window, st.reserve_tokens, last_prompt_tokens):
            return False
        await engine.hooks.emit("pre_compact", {"session_id": session_id, "tokens": estimate_tokens(msgs)})
        await _flush_memory(engine, snapshot, ctx, msgs, models, st)
        prev = next((e for e in reversed(sink.events({"compaction"}))), None)
        prev_pruned = dict((prev or {"payload": {}})["payload"].get("pruned") or {})
        pruned = {**prev_pruned, **prune_tool_outputs(msgs[1:], st.keep_recent_tokens)}
        if pruned != prev_pruned:
            pruned_msgs = [system] + apply_pruned([m for _s, m in cur], pruned)
            if not needs_compaction(pruned_msgs, st.context_window, st.reserve_tokens) and not force:
                sink.append("compaction", {"summary": None, "first_kept_seq": 0, "pinned_seqs": [], "pruned": pruned})
                yield_events.append({"type": "message", "content": "Pruned old tool outputs to free context."})
                return True
            msgs = pruned_msgs
        seqs = [None] + [s for s, _m in cur]
        first_user_seq = next((s for s, m in cur if m["role"] == "user" and s is not None), None)
        pinned_idx = (1 + next(i for i, (s, _m) in enumerate(cur) if s == first_user_seq),) if first_user_seq else (1,)
        plan = await plan_compaction(
            msgs, st.keep_recent_tokens, lambda p: _summarize(p, st, models[0]),
            can_cut=lambda i: seqs[i] is not None, pinned_indexes=pinned_idx)
        if plan is None:
            if pruned != prev_pruned:
                sink.append("compaction", {"summary": None, "first_kept_seq": 0, "pinned_seqs": [], "pruned": pruned})
                return True
            return False
        sink.append("compaction", {"summary": plan.summary, "first_kept_seq": seqs[plan.first_kept_index],
                                   "pinned_seqs": [first_user_seq] if first_user_seq else [], "pruned": pruned})
        await engine.hooks.emit("post_compact", {"session_id": session_id})
        yield_events.append({"type": "message", "content": "Compacted conversation history to fit the context window."})
        return True

    yield_events: list[dict] = []
    try:
        while True:
            state.usage["turns"] = ctx_turns = state.usage["turns"] + 1
            if ctx_turns > max_turns:
                state.outcome, state.final_text = "turn_limit", "Execution stopped: turn limit reached"
                break
            if ctx.budget.exhausted:
                state.outcome, state.final_text = "budget_exhausted", "Execution blocked: Token budget exceeded"
                yield {"type": "message", "content": "Token budget exceeded."}
                break
            if time.monotonic() - state.started > st.max_seconds:
                state.outcome, state.final_text = "time_limit", "Execution stopped: time limit reached"
                break
            for text in sink.drain_interrupts():
                yield {"type": "interruption_received", "content": text}
            if ctx.extras.pop("refresh_tools", False):  # this run registered a tool: expose it next turn
                snapshot = engine.snapshot()
                tools = snapshot.schemas(ctx.allowed, ctx.deny_tools)
            await engine.hooks.emit("before_turn", {"session_id": session_id, "turn": ctx_turns})
            await compact()
            for ev in yield_events:
                yield ev
            yield_events.clear()
            messages = [system] + [m for _s, m in sink.pairs()]
            deltas: list[str] = []
            try:
                try:
                    result = await complete(models, messages, tools or None, st, on_delta=deltas.append)
                except ContextOverflow:
                    if not await compact(force=True):
                        raise
                    for ev in yield_events:
                        yield ev
                    yield_events.clear()
                    messages = [system] + [m for _s, m in sink.pairs()]
                    result = await complete(models, messages, tools or None, st, on_delta=deltas.append)
            except LLMError as error:
                state.outcome, state.error = "error", str(error)
                state.final_text = f"Run failed: {error}"
                break
            for piece in deltas:
                yield {"type": "message_delta", "content": piece}
            ctx.budget.add(result.total_tokens)
            last_prompt_tokens = result.prompt_tokens
            state.usage["prompt"] += result.prompt_tokens
            state.usage["completion"] += result.completion_tokens
            state.model = result.model or state.model
            assistant = {"content": result.content}
            if result.tool_calls:
                assistant["tool_calls"] = [{"id": tc.id, "type": "function",
                                            "function": {"name": tc.name, "arguments": tc.arguments}}
                                           for tc in result.tool_calls]
            sink.append("assistant_msg", assistant)
            if result.content:
                yield {"type": "message", "content": result.content}
            if ctx.budget.exhausted and result.tool_calls:
                # answer the pending calls so the transcript stays valid, then stop
                for tc in result.tool_calls:
                    sink.append("tool_result", {"tool_call_id": tc.id, "is_error": True,
                                                "content": "Not executed: token budget exceeded"})
                state.outcome, state.final_text = "budget_exhausted", "Execution blocked: Token budget exceeded"
                yield {"type": "message", "content": "Token budget exceeded."}
                break
            if not result.tool_calls:
                hook = await engine.hooks.emit("stop", {"session_id": session_id, "final_text": result.content or ""})
                if hook.force_continue and stop_forced < MAX_STOP_CONTINUATIONS:
                    stop_forced += 1
                    sink.append("user_msg", {"content": f"[stop hook] {hook.force_continue}"})
                    continue
                state.outcome, state.final_text = "completed", result.content or ""
                break

            parsed = [(tc, *_parse_args(tc)) for tc in result.tool_calls]
            for tc, args, _err in parsed:
                yield {"type": "tool_call", "name": tc.name, "arguments": args or {}}
            tool_results = await _execute_calls(engine, snapshot, parsed, ctx, sem)
            guard_hit = False
            for (tc, _args, _err), tr in zip(parsed, tool_results, strict=True):
                if tr.record:
                    sink.append("action", json.loads(tr.record.model_dump_json()))
                sink.append("tool_result", {"tool_call_id": tc.id, "content": tr.content, "is_error": tr.is_error})
                preview = tr.content[:256] + ("..." if len(tr.content) > 256 else "")
                yield {"type": "tool_result", "name": tc.name, "result_summary": preview, "is_error": tr.is_error}
                key = (tc.name, tc.arguments, tr.content[:200]) if tr.is_error else None
                loop_key, loop_count = (key, loop_count + 1) if key and key == loop_key else (key, 1 if key else 0)
                if loop_count >= LOOP_GUARD_REPEATS:
                    guard_hit = True
            if guard_hit:
                state.outcome = "loop_guard"
                state.final_text = "Execution stopped: the same failing tool call was repeated"
                break
    except asyncio.CancelledError:
        state.outcome = "cancelled"
        await _finish(ctx, sink, state, engine, span_cm, quiet=True)
        raise
    except Exception as error:  # noqa: BLE001
        log.exception("run failed")
        state.outcome, state.error = "error", f"{type(error).__name__}: {error}"
        state.final_text = f"Run failed: {state.error}"
    verification, teardown = await _finish(ctx, sink, state, engine, span_cm)
    history = [m for _s, m in sink.pairs()]
    actions = [ActionRecord.model_validate(e["payload"]) for e in sink.events({"action"})]
    yield {"type": "final_receipt", "receipt": {
        "events": [], "final_text": state.final_text, "model_used": state.model,
        "message_history": history, "actions": actions, "verification": verification,
        "outcome": state.outcome, "verified": None if verification is None else verification.passed,
        "teardown_tasks": teardown, "usage": state.usage, "error": state.error,
        "chain_head": eventlog.chain_head(sink.conn, sink.session_id), "started_at": state.started_at}}
    if own_conn is not None:
        own_conn.close()


async def _finish(ctx: RunCtx, sink: DBSink, state: RunState, engine: Engine, span_cm, quiet: bool = False):
    verification: VerificationResult | None = None
    if state.outcome == "completed":
        context: ContextPacket = ctx.extras["context"]
        spec = context.live_state.get("verification")
        profile_spec = None
        if spec is None:
            agent = engine.extras.get("agents")
            profile = agent.get_agent(ctx.agent_id) if agent else None
            profile_spec = profile.verification if profile else None
        if isinstance(spec, dict) or profile_spec:
            verification = await run_verification(spec if isinstance(spec, dict) else profile_spec)
            sink.append("verification", json.loads(verification.model_dump_json()))
        agents = engine.extras.get("agents")
        prof = agents.get_agent(ctx.agent_id) if agents else None
        if (verification is None or verification.passed) and prof and prof.verify_with_agent and ctx.depth == 0:
            from core.verifiers import verify_with_agent

            verification = await verify_with_agent(ctx, state.final_text)
            sink.append("verification", json.loads(verification.model_dump_json()))
    teardown = await ctx.effects.rollback()
    sink.append("outcome", {"outcome": state.outcome, "verified": None if verification is None else verification.passed,
                            "error": state.error, "usage": state.usage, "teardown": teardown,
                            "skills_used": sorted(ctx.extras.get("skills_used", []))})
    await engine.hooks.emit("session_end", {"session_id": ctx.session_id, "outcome": state.outcome})
    try:
        span_cm.__exit__(None, None, None)
    except Exception:  # noqa: BLE001
        pass
    return verification, teardown


async def run_agent(context: ContextPacket, allowed_tools: list[str], agent_profile: AgentProfile | None = None,
                    initial_history: list[dict[str, Any]] | None = None, **kwargs) -> dict[str, Any]:
    """Run to completion and return the final receipt dict."""
    async for event in run_agent_generator(None, context, allowed_tools, agent_profile, initial_history, **kwargs):
        if event["type"] == "final_receipt":
            return event["receipt"]
    raise RuntimeError("Agent terminated without producing a final receipt")
