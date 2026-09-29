"""Cost accounting: prices, the USD budget, per-call events, stored totals, CLI and API reports."""
import json

import pytest

from core import cost
from core.llm import Completion
from core.tools import Budget

pytestmark = pytest.mark.unit


def test_known_local_unknown_and_overridden_prices(monkeypatch):
    assert cost.cost_usd("openai/gpt-4o", 1_000_000, 0) == pytest.approx(2.5)
    assert cost.cost_usd("ollama_chat/llama3.1", 10**6, 10**6) == 0.0
    assert cost.cost_usd("madeup/model", 10, 10) is None
    monkeypatch.setenv("HARNESS_PRICES", json.dumps({"madeup/model": {"input": 1, "output": 2}}))
    assert cost.cost_usd("madeup/model", 1_000_000, 1_000_000) == pytest.approx(3.0)
    monkeypatch.setenv("HARNESS_PRICES", "not json")
    assert cost.cost_usd("madeup/model", 10, 10) is None


def test_completion_and_budget():
    c = Completion("hi", [], 1_000_000, 0, "openai/gpt-4o")
    assert c.cost_usd == pytest.approx(2.5)
    b = Budget(10**9, cost_limit=5.0)
    b.charge(c)
    assert not b.exhausted
    b.charge(c)
    assert b.exhausted and b.cost_exhausted and b.reason() == "Cost budget exceeded"
    b2 = Budget(10**9)
    b2.add(10, None)
    assert b2.unpriced_calls == 1 and not b2.exhausted and b2.reason() == "Token budget exceeded"


def test_fmt():
    assert cost.fmt(None) == "n/a" and cost.fmt(0) == "$0" and cost.fmt(0.01234) == "$0.0123"
    assert cost.fmt(1234.5) == "$1,234.50"


# -- loop / storage / reports ----------------------------------------------------------------
from tests.helpers import context, install_llm, msg  # noqa: E402

GROQ = "groq/openai/gpt-oss-120b"           # the default model; priced in LiteLLM's map


@pytest.mark.integration
async def test_run_records_cost_per_call_and_in_the_receipt(engine, monkeypatch):
    from core.loop import run_agent

    install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})], tokens=2000, prompt=1000), msg("ok")])
    r = await run_agent(context(), ["Read"], engine=engine)
    expected = cost.cost_usd(GROQ, 1000, 1000) + cost.cost_usd(GROQ, 5, 5)
    assert r["usage"]["cost_usd"] == pytest.approx(expected) and r["usage"]["unpriced_calls"] == 0


@pytest.mark.integration
async def test_cost_budget_stops_the_run(engine, monkeypatch):
    from core.loop import run_agent
    from core.primitives.agent import AgentProfile

    install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})], tokens=2_000_000)] * 3)
    profile = AgentProfile(id="a", domain="devops", system_prompt="t", allowed_tools=["Read"], max_cost_usd=0.1)
    r = await run_agent(context(), ["Read"], profile, engine=engine)
    assert r["outcome"] == "budget_exhausted" and "Cost budget" in r["final_text"]


@pytest.mark.integration
async def test_env_cost_limit_applies(engine, monkeypatch):
    from core.loop import run_agent

    monkeypatch.setenv("HARNESS_MAX_COST_USD", "0.0001")
    install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})], tokens=100_000)] * 3)
    r = await run_agent(context(), ["Read"], engine=engine)
    assert r["outcome"] == "budget_exhausted"


@pytest.mark.integration
def test_api_lists_sessions_with_cost_and_reports_usage(monkeypatch):
    from fastapi.testclient import TestClient

    from core.gateway import api
    from core.primitives.agent import AgentProfile
    from tests.test_api import H, _wait

    old = api.registry._agents
    api.registry._agents = {"reader": AgentProfile(id="reader", domain="devops", system_prompt="t",
                                                   allowed_tools=["Read"])}
    try:
        install_llm(monkeypatch, [msg("done", tokens=2000, prompt=1500)])
        with TestClient(api.app, headers=H) as client:
            sid = client.post("/sessions", json={"agent_id": "reader", "goal": "g", "run": True}).json()["session_id"]
            s = _wait(client, sid)
            assert s["cost_usd"] == pytest.approx(cost.cost_usd(GROQ, 1500, 500)) and s["prompt_tokens"] == 1500
            listed = client.get("/sessions").json()
            assert listed[0]["id"] == sid and listed[0]["cost_usd"] == pytest.approx(s["cost_usd"])
            assert client.get("/sessions", params={"status": "running"}).json() == []
            u = client.get("/usage", params={"by": "agent"}).json()
            assert u["rows"][0]["key"] == "reader" and u["total_cost_usd"] == pytest.approx(s["cost_usd"])
            assert client.get("/usage", params={"by": "nope"}).status_code == 422
            assert client.get("/usage", headers={"Authorization": "Bearer bad"}).status_code == 401
    finally:
        api.registry._agents = old


@pytest.mark.integration
async def test_cli_cost_report(engine, monkeypatch, capsys):
    from cli.main import main
    from core.eventlog import append_event
    from core.memory.store import create_session, init_db

    conn = init_db()
    create_session(conn, "s1", "reader", "g")
    append_event(conn, "s1", "llm_call", {"model": GROQ, "prompt_tokens": 100, "completion_tokens": 50, "cost_usd": 0.5})
    append_event(conn, "s1", "llm_call", {"model": "x/y", "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": None})
    conn.close()
    assert main(["cost"]) == 0
    out = capsys.readouterr().out
    assert GROQ in out and "$0.5000" in out and "1 unpriced" in out and "no known price" in out
    assert main(["cost", "--by", "agent", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["rows"][0]["key"] == "reader" and data["rows"][0]["calls"] == 2
