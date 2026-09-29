"""Permission modes: plan (read-only until the plan is approved), read-only, strict."""
import asyncio

import pytest

from core import modes
from core.approvals import ApprovalBroker, set_broker
from core.loop import run_agent_generator
from core.memory.store import create_session, get_session, init_db
from core.policy import decide, parse_rule
from core.primitives.agent import AgentProfile
from core.primitives.policy import RiskTier
from tests.helpers import context, install_llm, msg

pytestmark = pytest.mark.integration


def _d(mode, tier=RiskTier.R1, read_only=False, rules=(), pre=False):
    return decide(name="write", policy_tool="filesystem", policy_action="write", tier=tier, read_only=read_only,
                  args={"path": "x"}, rules=[parse_rule(r) for r in rules], tainted=False, pre_approved=pre, mode=mode)


@pytest.mark.unit
def test_policy_matrix():
    assert _d("default").decision == "ALLOW"
    assert _d("plan").decision == "DENY" and "exit_plan_mode" in _d("plan").reason
    assert _d("read-only").decision == "DENY" and "exit_plan_mode" not in _d("read-only").reason
    assert _d("plan", read_only=True, tier=RiskTier.R0).decision == "ALLOW"
    assert _d("strict").decision == "REQUIRE_APPROVAL"
    assert _d("strict", read_only=True, tier=RiskTier.R0).decision == "ALLOW"
    assert _d("default", tier=RiskTier.R2, pre=True).decision == "ALLOW"
    assert _d("strict", tier=RiskTier.R2, pre=True).decision == "REQUIRE_APPROVAL"        # memory ignored
    assert _d("default", tier=RiskTier.R2, rules=["allow:write"]).decision == "ALLOW"
    assert _d("strict", tier=RiskTier.R2, rules=["allow:write"]).decision == "REQUIRE_APPROVAL"  # allow ignored
    assert _d("strict", tier=RiskTier.R4).decision == "DENY"


@pytest.mark.unit
def test_normalize(monkeypatch):
    assert modes.normalize("READ_ONLY") == "read-only" and modes.normalize(None) is None
    with pytest.raises(ValueError):
        modes.normalize("yolo")
    monkeypatch.setenv("HARNESS_PERMISSION_MODE", "strict")
    assert modes.default_mode() == "strict"
    monkeypatch.setenv("HARNESS_PERMISSION_MODE", "nonsense")
    assert modes.default_mode() == "default"
    assert modes.child_mode("plan") == "read-only" and modes.child_mode("strict") == "strict"


async def _run(engine, script, monkeypatch, mode, sid="s-plan", tools=("Read", "Write")):
    calls = install_llm(monkeypatch, script)
    conn = init_db()
    create_session(conn, sid, "a", "g", permission_mode=mode)
    from core.loop import DBSink

    events = []
    async for ev in run_agent_generator(sid, context(), list(tools), engine=engine, sink=DBSink(conn, sid), mode=mode):
        events.append(ev)
    conn.close()
    return calls, events[-1]["receipt"], events


def _tool_names(call):
    return {t["function"]["name"] for t in call.get("tools") or []}


async def test_plan_mode_hides_writes_until_the_plan_is_approved(engine, monkeypatch, workspace):
    broker = ApprovalBroker(timeout=5)
    set_broker(broker)
    engine.broker = broker

    async def approver(req):
        assert req.tool == "exit_plan_mode" and "write hello" in req.rendered
        asyncio.get_running_loop().call_soon(broker.resolve, req.id, True, "cli:test")

    broker.add_channel(approver)
    calls, receipt, _ = await _run(engine, [
        msg(tool_calls=[("write", {"path": "a.txt", "content": "x"})]),        # tries to write while planning
        msg(tool_calls=[("exit_plan_mode", {"plan": "1. write hello to a.txt"})]),
        msg(tool_calls=[("write", {"path": "a.txt", "content": "hello"})]),
        msg("done"),
    ], monkeypatch, "plan")
    first, after = _tool_names(calls[0]), _tool_names(calls[3])
    assert "exit_plan_mode" in first and "write" not in first and "read" in first
    assert "write" in after and "exit_plan_mode" not in after
    denied = [m["content"] for m in calls[1]["messages"] if m["role"] == "tool"][0]
    assert "plan mode allows read-only tools only" in denied
    assert "[Plan mode]" in calls[0]["messages"][1]["content"]
    assert receipt["outcome"] == "completed" and (workspace / "a.txt").read_text() == "hello"
    conn = init_db()
    from core.eventlog import list_events

    change = list_events(conn, "s-plan", types={"mode_change"})
    assert change[0]["payload"]["to"] == "default" and change[0]["payload"]["approved_by"] == "cli:test"
    conn.close()


async def test_rejected_plan_keeps_the_agent_read_only(engine, monkeypatch, workspace):
    broker = ApprovalBroker(timeout=5)
    set_broker(broker)
    engine.broker = broker

    async def reject(req):
        asyncio.get_running_loop().call_soon(lambda: broker.resolve(req.id, False, "cli:test", note="too risky"))

    broker.add_channel(reject)
    calls, receipt, _ = await _run(engine, [
        msg(tool_calls=[("exit_plan_mode", {"plan": "delete everything"})]),
        msg(tool_calls=[("write", {"path": "a.txt", "content": "x"})]),
        msg("ok, stopping"),
    ], monkeypatch, "plan", sid="s-rej")
    result = [m["content"] for m in calls[1]["messages"] if m["role"] == "tool"][0]
    assert "not approved (too risky)" in result
    assert "write" not in _tool_names(calls[1]) and not (workspace / "a.txt").exists()


async def test_read_only_mode_has_no_exit(engine, monkeypatch, workspace):
    calls, receipt, _ = await _run(engine, [msg(tool_calls=[("exit_plan_mode", {"plan": "p"})]), msg("done")],
                                   monkeypatch, "read-only", sid="s-ro")
    assert "exit_plan_mode" not in _tool_names(calls[0]) and "write" not in _tool_names(calls[0])
    assert "not allowed" in [m["content"] for m in calls[1]["messages"] if m["role"] == "tool"][0]


async def test_strict_mode_asks_for_an_ordinary_edit(engine, monkeypatch, workspace):
    broker = ApprovalBroker(timeout=5)
    set_broker(broker)
    engine.broker = broker
    asked = []

    async def deny(req):
        asked.append(req.tool)
        asyncio.get_running_loop().call_soon(broker.resolve, req.id, False, "cli:test")

    broker.add_channel(deny)
    await _run(engine, [msg(tool_calls=[("write", {"path": "a.txt", "content": "x"})]), msg("done")],
               monkeypatch, "strict", sid="s-strict")
    assert asked == ["write"] and not (workspace / "a.txt").exists()


async def test_profile_and_env_mode(engine, monkeypatch, workspace):
    from core.loop import run_agent

    install_llm(monkeypatch, [msg(tool_calls=[("write", {"path": "a.txt", "content": "x"})]), msg("done")])
    prof = AgentProfile(id="p", domain="devops", system_prompt="t", allowed_tools=["Read", "Write"],
                        permission_mode="read-only")
    await run_agent(context(), ["Read", "Write"], prof, engine=engine)
    assert not (workspace / "a.txt").exists()
    monkeypatch.setenv("HARNESS_PERMISSION_MODE", "read-only")
    install_llm(monkeypatch, [msg(tool_calls=[("write", {"path": "b.txt", "content": "x"})]), msg("done")])
    await run_agent(context(), ["Read", "Write"], engine=engine)
    assert not (workspace / "b.txt").exists()


def test_api_accepts_and_validates_mode(monkeypatch):
    from fastapi.testclient import TestClient

    from core.gateway import api
    from tests.test_api import H, _wait

    old = api.registry._agents
    api.registry._agents = {"w": AgentProfile(id="w", domain="devops", system_prompt="t", allowed_tools=["Read", "Write"])}
    try:
        install_llm(monkeypatch, [msg(tool_calls=[("write", {"path": "a.txt", "content": "x"})]), msg("done")])
        with TestClient(api.app, headers=H) as client:
            bad = client.post("/sessions", json={"agent_id": "w", "goal": "g", "permission_mode": "yolo"})
            assert bad.status_code == 422
            sid = client.post("/sessions", json={"agent_id": "w", "goal": "g", "run": True,
                                                 "permission_mode": "read_only"}).json()["session_id"]
            s = _wait(client, sid)
            assert s["permission_mode"] == "read-only"
            evs = client.get(f"/sessions/{sid}/events").json()
            assert next(e for e in evs if e["type"] == "run_start")["payload"]["mode"] == "read-only"
    finally:
        api.registry._agents = old


def test_session_row_keeps_the_mode():
    conn = init_db()
    create_session(conn, "m1", "a", "g", permission_mode="plan")
    assert get_session(conn, "m1")["permission_mode"] == "plan"
    conn.close()
