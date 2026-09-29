"""Compaction: token-based trigger, cut safety (property test), pruning, replay from the log."""
import random

import pytest

from core import eventlog
from core.compaction import (apply_pruned, deterministic_summary, estimate_tokens, find_cut, needs_compaction,
                             plan_compaction, prune_tool_outputs, serialize)
from core.loop import run_agent
from core.memory.store import init_db
from core.transcript import validate_transcript
from tests.helpers import context, install_llm, msg


def _transcript(rng, turns):
    """system + user goal + random tool-using turns (parallel calls, long/short results)."""
    m = [{"role": "system", "content": "sys"}, {"role": "user", "content": "goal " * 20}]
    n = 0
    for _ in range(turns):
        k = rng.choice([0, 1, 1, 2, 3])
        if k == 0:
            m.append({"role": "assistant", "content": "thinking " * rng.randint(1, 30)})
            m.append({"role": "user", "content": "follow up " * rng.randint(1, 30)})
            continue
        calls = []
        for _ in range(k):
            n += 1
            calls.append({"id": f"c{n}", "type": "function", "function": {"name": "read", "arguments": '{"path": "f"}'}})
        m.append({"role": "assistant", "content": None, "tool_calls": calls})
        for c in calls:
            m.append({"role": "tool", "tool_call_id": c["id"], "content": "out " * rng.choice([5, 50, 500])})
    return m


def test_needs_compaction_is_token_based_not_count_based():
    short_many = [{"role": "user", "content": "x"}] * 200
    assert not needs_compaction(short_many, window=100_000, reserve=1000)
    big = [{"role": "user", "content": "x" * 4000}] * 20
    assert needs_compaction(big, window=10_000, reserve=1000)
    assert needs_compaction([{"role": "user", "content": "x"}], 100_000, 1000, last_prompt_tokens=120_000)


def test_find_cut_never_lands_on_a_tool_message():
    rng = random.Random(1)
    for _ in range(300):
        m = _transcript(rng, rng.randint(2, 30))
        cut = find_cut(m, keep_recent_tokens=rng.choice([50, 300, 2000]))
        if cut is not None:
            assert m[cut]["role"] in {"user", "assistant"} and cut >= 1


async def _summ(prompt):
    assert "<conversation>" in prompt
    return "SUMMARY"


async def test_property_compaction_keeps_transcript_valid():
    """1,000 random tool transcripts stay valid after compaction, replayed from the event log."""
    rng = random.Random(42)
    checked = 0
    for i in range(1000):
        conn = init_db(":memory:")
        m = _transcript(rng, rng.randint(2, 25))
        seqs = [None]
        for msg_ in m[1:]:
            if msg_["role"] == "user":
                e = eventlog.append_event(conn, "s", "user_msg", {"content": msg_["content"]})
            elif msg_["role"] == "assistant":
                e = eventlog.append_event(conn, "s", "assistant_msg",
                                          {"content": msg_.get("content"), "tool_calls": msg_.get("tool_calls")})
            else:
                e = eventlog.append_event(conn, "s", "tool_result",
                                          {"tool_call_id": msg_["tool_call_id"], "content": msg_["content"]})
            seqs.append(e["seq"])
        pruned = prune_tool_outputs(m[1:], 200)
        pm = [m[0]] + apply_pruned(m[1:], pruned)
        plan = await plan_compaction(pm, rng.choice([100, 500, 3000]), _summ, can_cut=lambda k: seqs[k] is not None)
        if plan is None:
            continue
        eventlog.append_event(conn, "s", "compaction", {
            "summary": plan.summary, "first_kept_seq": seqs[plan.first_kept_index], "pinned_seqs": [seqs[1]],
            "pruned": pruned})
        rebuilt = eventlog.messages_for(conn, "s")
        assert validate_transcript([m[0]] + rebuilt) == [], (i, plan.first_kept_index)
        assert rebuilt[0]["content"] == m[1]["content"]                 # first user message pinned
        assert rebuilt[-1] == pm[-1] or rebuilt[-1]["role"] in {"assistant", "tool", "user"}
        assert len(rebuilt) < len(m) or estimate_tokens(rebuilt) <= estimate_tokens(m)
        checked += 1
        conn.close()
    assert checked > 300


def test_prune_only_touches_old_large_tool_results():
    m = [{"role": "system", "content": "s"}, {"role": "user", "content": "g"},
         {"role": "assistant", "content": None, "tool_calls": [
             {"id": "a", "type": "function", "function": {"name": "kubectl_logs", "arguments": "{}"}}]},
         {"role": "tool", "tool_call_id": "a", "content": "L" * 5000},
         {"role": "assistant", "content": None, "tool_calls": [
             {"id": "b", "type": "function", "function": {"name": "kubectl_logs", "arguments": "{}"}}]},
         {"role": "tool", "tool_call_id": "b", "content": "R" * 5000}]
    pruned = prune_tool_outputs(m, keep_recent_tokens=1500)
    assert list(pruned) == ["a"] and "kubectl_logs pruned; 5000 chars" in pruned["a"]
    assert apply_pruned(m, pruned)[3]["content"] == pruned["a"] and apply_pruned(m, pruned)[5]["content"] == "R" * 5000


def test_serialize_keeps_tool_calls_and_truncates_results():
    m = [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": "argocd_app_get", "arguments": '{"app_name": "web"}'}}]},
         {"role": "tool", "tool_call_id": "a", "content": "Z" * 9000}]
    s = serialize(m)
    assert "argocd_app_get" in s and "web" in s and "[truncated]" in s and len(s) < 2600


async def test_summariser_failure_falls_back_to_deterministic_summary():
    m = [{"role": "system", "content": "s"}, {"role": "user", "content": "goal " * 50}] + \
        [x for i in range(6) for x in ({"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
                                       {"role": "tool", "tool_call_id": f"c{i}", "content": "r" * 400})]

    async def broken(_):
        raise RuntimeError("provider down")

    plan = await plan_compaction(m, 300, broken)
    assert plan and "automatic summary" in plan.summary and "read" in plan.summary
    assert "read" in deterministic_summary(m)


@pytest.mark.integration
async def test_loop_prunes_then_compacts_by_tokens_and_stays_valid(engine, monkeypatch, workspace):
    (workspace / "big.txt").write_text("line\n" * 3000)
    monkeypatch.setenv("HARNESS_CONTEXT_WINDOW", "6000")
    monkeypatch.setenv("HARNESS_RESERVE_TOKENS", "500")
    monkeypatch.setenv("HARNESS_KEEP_RECENT_TOKENS", "800")
    script = [msg(tool_calls=[("read", {"path": "big.txt", "offset": 1 + i * 100, "limit": 400})])
              for i in range(10)] + [msg("SUMMARY TEXT"), msg("final")]

    def summariser(kw):
        return msg("Goal: x. Progress: read big.txt in chunks.")

    calls = install_llm(monkeypatch, script[:6] + [summariser] + script[6:])
    from core.loop import DBSink
    from core.memory.store import create_session

    conn = init_db()
    create_session(conn, "s", "a", "goal")
    r = None
    from core.loop import run_agent_generator

    async for ev in run_agent_generator("s", context(), ["Read"], engine=engine, sink=DBSink(conn, "s")):
        if ev["type"] == "final_receipt":
            r = ev["receipt"]
    assert r["outcome"] == "completed"
    comps = eventlog.list_events(conn, "s", types={"compaction"})
    assert comps, "compaction should have triggered on tokens, not message count"
    assert all(validate_transcript(c["messages"]) == [] for c in calls)


@pytest.mark.integration
async def test_context_overflow_error_triggers_compaction_and_retry(engine, monkeypatch, workspace):
    import litellm

    (workspace / "f.txt").write_text("x\n" * 400)
    monkeypatch.setenv("HARNESS_KEEP_RECENT_TOKENS", "50")
    overflow = litellm.ContextWindowExceededError("too long", "m", "p")
    install_llm(monkeypatch, [
        msg(tool_calls=[("read", {"path": "f.txt"})]), msg(tool_calls=[("read", {"path": "f.txt", "offset": 5})]),
        overflow, msg("summary of work"), msg("recovered")], validate=True)
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["final_text"] == "recovered"
