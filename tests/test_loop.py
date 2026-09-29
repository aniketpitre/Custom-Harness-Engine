"""Agent loop: streaming/parallel, errors as results, budgets, outcomes, transcript validity."""
import json

import pytest

from core.loop import run_agent, run_agent_generator
from core.primitives.agent import AgentProfile
from tests.helpers import context, install_llm, msg

pytestmark = pytest.mark.integration


async def test_plain_answer_completes(engine, monkeypatch):
    install_llm(monkeypatch, [msg("hello there")])
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "completed" and r["final_text"] == "hello there"
    assert r["verified"] is None


async def test_tool_call_roundtrip_and_action_record(engine, monkeypatch, workspace):
    (workspace / "a.txt").write_text("alpha\nbeta\n")
    calls = install_llm(monkeypatch, [msg(tool_calls=[("read", {"path": "a.txt"})]), msg("done")])
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "completed"
    assert r["actions"][0].tool == "filesystem" and r["actions"][0].action == "read"
    tool_msg = [m for m in calls[1]["messages"] if m["role"] == "tool"][0]
    assert "alpha" in tool_msg["content"]


async def test_tool_errors_go_back_to_the_model(engine, monkeypatch):
    """Bad JSON, unknown tools, missing files and denied tools must not kill the run."""
    def bad_json(kw):
        m = msg(tool_calls=[("read", {})])
        m.choices[0].message.tool_calls[0].function.arguments = "{not json"
        return m

    calls = install_llm(monkeypatch, [
        bad_json,
        msg(tool_calls=[("nonexistent_tool", {})]),
        msg(tool_calls=[("read", {"path": "missing.txt"})]),
        msg(tool_calls=[("write", {"path": "x", "content": "y"})]),   # Write not allowed for this agent
        msg("recovered"),
    ])
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "completed" and r["final_text"] == "recovered"
    results = [m["content"] for m in calls[-1]["messages"] if m["role"] == "tool"]
    assert any("Invalid JSON" in c for c in results)
    assert any("Unknown tool" in c for c in results)
    assert any("FileNotFoundError" in c for c in results)
    assert any("not allowed" in c for c in results)


async def test_loop_guard_stops_repeated_identical_failures(engine, monkeypatch):
    install_llm(monkeypatch, [msg(tool_calls=[("read", {"path": "nope"})])] * 6)
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "loop_guard"


async def test_budget_exhausted_is_not_success(engine, monkeypatch):
    install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})], tokens=250_000)])
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "budget_exhausted"
    from core.receipts import derive_status

    assert derive_status(r["outcome"], r["verified"]) == "failure"


async def test_final_answer_over_budget_is_still_a_completed_run(engine, monkeypatch):
    install_llm(monkeypatch, [msg("answer", tokens=250_000)])
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "completed"


async def test_budget_exhausted_with_pending_tool_calls_keeps_transcript_valid(engine, monkeypatch):
    install_llm(monkeypatch, [msg(tool_calls=[("read", {"path": "."})], tokens=250_000)])
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "budget_exhausted"
    from core.transcript import validate_transcript

    assert validate_transcript([{"role": "system", "content": "s"}] + r["message_history"]) == []


async def test_turn_limit(engine, monkeypatch, workspace):
    (workspace / "f").write_text("x")
    responses = [msg(tool_calls=[("read", {"path": "f", "offset": i + 1})]) for i in range(10)]
    install_llm(monkeypatch, responses)
    profile = AgentProfile(id="p", domain="devops", system_prompt="x", allowed_tools=["Read"], max_turns=3)
    r = await run_agent(context(), ["Read"], profile, engine=engine)
    assert r["outcome"] == "turn_limit"


async def test_llm_failure_becomes_error_outcome_not_exception(engine, monkeypatch):
    import core.llm as llm

    async def nosleep(_):
        return None

    monkeypatch.setattr(llm, "_sleep", nosleep)
    install_llm(monkeypatch, [RuntimeError("boom")] * 5)
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "error" and "boom" in r["final_text"]


async def test_verification_failure_marks_failure(engine, monkeypatch, workspace):
    install_llm(monkeypatch, [msg("done")])
    ctx = context(live_state={"verification": {"path": str(workspace / "out.txt"), "expected_content": "hi"}})
    r = await run_agent(ctx, ["Read"], engine=engine)
    assert r["outcome"] == "completed" and r["verified"] is False
    from core.receipts import derive_status

    assert derive_status(r["outcome"], r["verified"]) == "failure"


async def test_verification_pass(engine, monkeypatch, workspace):
    (workspace / "out.txt").write_text("hi\n")
    install_llm(monkeypatch, [msg("done")])
    ctx = context(live_state={"verification": {"path": str(workspace / "out.txt"), "expected_content": "hi"}})
    r = await run_agent(ctx, ["Read"], engine=engine)
    assert r["verified"] is True


async def test_parallel_readonly_tools_run_concurrently(engine, monkeypatch, workspace):
    import asyncio
    import time

    from core.plugins.base import Plugin
    from core.primitives.policy import RiskTier
    from core.tools import ToolSpec

    async def slow(args, ctx):
        await asyncio.sleep(0.3)
        return "ok"

    class P(Plugin):
        name = "slow"

        def register(self, ctx):
            ctx.tool(ToolSpec("slow", "s", {"type": "object", "properties": {}}, slow, capability="Read",
                              risk=RiskTier.R0, read_only=True, parallel_safe=True))

    await engine.plugins.load(P())
    install_llm(monkeypatch, [msg(tool_calls=[("slow", {})] * 5), msg("done")])
    t0 = time.monotonic()
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "completed"
    assert time.monotonic() - t0 < 1.0   # five 0.3s calls in parallel, not 1.5s


async def test_streaming_assembles_tool_calls(engine, monkeypatch):
    from types import SimpleNamespace as NS

    import litellm

    monkeypatch.setenv("HARNESS_STREAM", "true")
    seen = []

    def chunk(content=None, tc=None, usage=None):
        return NS(choices=[NS(delta=NS(content=content, tool_calls=tc))], usage=usage)

    async def gen_tool():
        yield chunk("thi")
        yield chunk("nk", [NS(index=0, id="c1", function=NS(name="read_dir", arguments='{"pa'))])
        yield chunk(None, [NS(index=0, id=None, function=NS(name="ectory", arguments='th": "."}'))])
        yield NS(choices=[], usage=NS(total_tokens=20, prompt_tokens=15, completion_tokens=5))

    async def gen_text():
        yield chunk("all done")

    responses = [gen_tool(), gen_text()]

    async def fake(**kw):
        seen.append(kw)
        return responses.pop(0)

    monkeypatch.setattr(litellm, "acompletion", fake)
    events = [e async for e in run_agent_generator(None, context(), ["Read"], engine=engine)]
    types = [e["type"] for e in events]
    assert "message_delta" in types and "tool_call" in types
    assert events[-1]["receipt"]["final_text"] == "all done"
    assert seen[0]["stream"] is True


async def test_interrupts_are_delivered_in_order(engine, monkeypatch):
    from core import eventlog
    from core.loop import DBSink
    from core.memory.store import create_session, init_db

    conn = init_db()
    create_session(conn, "s1", "a", "goal")
    eventlog.append_event(conn, "s1", "interrupt_queued", {"content": "first"})
    eventlog.append_event(conn, "s1", "interrupt_queued", {"content": "second"})
    calls = install_llm(monkeypatch, [msg("ok")])
    events = [e async for e in run_agent_generator("s1", context(), ["Read"], engine=engine, sink=DBSink(conn, "s1"))]
    got = [e["content"] for e in events if e["type"] == "interruption_received"]
    assert got == ["first", "second"]
    users = [m["content"] for m in calls[0]["messages"] if m["role"] == "user"]
    assert users[-2:] == ["User Interruption: first", "User Interruption: second"]


async def test_resume_rebuilds_transcript_from_the_log(engine, monkeypatch):
    from core.loop import DBSink
    from core.memory.store import create_session, init_db

    conn = init_db()
    create_session(conn, "s2", "a", "goal")
    install_llm(monkeypatch, [msg("first answer")])
    _ = [e async for e in run_agent_generator("s2", context("goal one"), ["Read"], engine=engine, sink=DBSink(conn, "s2"))]
    calls = install_llm(monkeypatch, [msg("second answer")])
    _ = [e async for e in run_agent_generator("s2", context("goal two"), ["Read"], engine=engine, sink=DBSink(conn, "s2"))]
    contents = json.dumps(calls[0]["messages"])
    assert "first answer" in contents and "goal two" in contents


async def test_stop_hook_can_force_continuation(engine, monkeypatch):
    engine.hooks.on("stop", lambda p: {"continue": "run the checklist first"} if "checked" not in p["final_text"] else None)
    calls = install_llm(monkeypatch, [msg("finished"), msg("checked, finished")])
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["final_text"] == "checked, finished"
    assert any("run the checklist" in json.dumps(m) for m in calls[1]["messages"])


async def test_model_failover_uses_fallback(engine, monkeypatch):
    import litellm

    import core.llm as llm

    async def nosleep(_):
        return None

    monkeypatch.setattr(llm, "_sleep", nosleep)
    monkeypatch.setenv("HARNESS_FALLBACK_MODELS", "backup/model")
    monkeypatch.setenv("HARNESS_LLM_RETRIES", "2")
    used = []

    async def fake(**kw):
        used.append(kw["model"])
        if kw["model"] != "backup/model":
            raise litellm.RateLimitError("429", "p", "primary/model")
        return msg("from backup")

    monkeypatch.setattr(litellm, "acompletion", fake)
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["final_text"] == "from backup"
    assert used.count("backup/model") == 1 and len(used) == 3
