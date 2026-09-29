"""Approvals work with no setup: a live terminal prompt chained with the API and Telegram."""
import asyncio
import builtins

import pytest

from core.approvals import ApprovalBroker, ApprovalRequest
from core.gateway import channels

pytestmark = pytest.mark.unit


def _req(i="r1", tool="shell_exec"):
    return ApprovalRequest(id=i, session_id="s", tool=tool, risk_tier="R2", rendered="rm -rf x",
                           args_hash="h" + i)


def test_terminal_is_off_without_a_tty_and_can_be_disabled(monkeypatch):
    monkeypatch.setattr(channels.sys.stdin, "isatty", lambda: False, raising=False)
    assert channels.terminal_channel(ApprovalBroker(timeout=2)) is None
    monkeypatch.setattr(channels.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setenv("HARNESS_TERMINAL_APPROVALS", "off")
    assert not channels.terminal_enabled()


async def test_terminal_answer_resolves_the_request(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "y")
    broker = ApprovalBroker(timeout=5)
    dispose = channels.terminal_channel(broker, force=True)
    result = await broker.request(_req())
    assert result.approved and result.approver == "cli:terminal"
    dispose()
    assert broker.channels == []


async def test_default_is_deny(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _p="": "")
    broker = ApprovalBroker(timeout=5)
    channels.terminal_channel(broker, force=True)
    assert not (await broker.request(_req())).approved


async def test_api_answer_wins_and_the_stale_prompt_is_ignored(monkeypatch):
    gate = asyncio.Event()
    loop = asyncio.get_running_loop()

    def slow_input(_p=""):
        asyncio.run_coroutine_threadsafe(gate.wait(), loop).result(5)
        return "y"                                    # the user answers late, after the API already said no

    monkeypatch.setattr(builtins, "input", slow_input)
    broker = ApprovalBroker(timeout=5)
    channels.terminal_channel(broker, force=True)
    task = asyncio.create_task(broker.request(_req()))
    await asyncio.sleep(0.2)
    assert broker.resolve("r1", False, "api:someone")
    result = await task
    gate.set()
    await asyncio.sleep(0.2)
    assert not result.approved and result.approver == "api:someone"


async def test_prompts_are_asked_one_at_a_time(monkeypatch):
    asked = []
    monkeypatch.setattr(builtins, "input", lambda _p="": asked.append(1) or "y")
    broker = ApprovalBroker(timeout=5)
    channels.terminal_channel(broker, force=True)
    results = await asyncio.gather(broker.request(_req("a")), broker.request(_req("b")))
    assert all(r.approved for r in results) and len(asked) == 2


def test_serve_lifespan_registers_and_disposes_the_terminal_channel(monkeypatch):
    from fastapi.testclient import TestClient

    from core.gateway import api

    monkeypatch.setattr(channels.sys.stdin, "isatty", lambda: True, raising=False)
    with TestClient(api.app) as client:
        assert client.get("/health").status_code == 200
        assert len(api.engine.broker.channels) >= 1
    assert api.engine.broker.channels == []
