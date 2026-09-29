"""`harness chat`: multi-turn history, slash commands, stopping a turn, resume, mode switches."""
import io

import pytest

from cli.chat import Chat
from core.engine import set_engine
from core.eventlog import list_events
from core.memory.store import get_session, init_db
from tests.helpers import install_llm, msg

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def fresh_engine():
    set_engine(None)
    yield
    set_engine(None)


def scripted(*lines):
    queue = list(lines)

    def read(_prompt=""):
        if not queue:
            raise EOFError
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return read


def chat(*lines, **kw):
    out = io.StringIO()
    c = Chat(out=out, read=scripted(*lines), **kw)
    code = c.run()
    return c, code, out.getvalue()


def test_two_turns_share_history_and_track_cost(monkeypatch):
    calls = install_llm(monkeypatch, [msg("hi there", tokens=100), msg("second answer", tokens=100)])
    c, code, out = chat("hello", "/cost", "what did I say?", "/exit")
    assert code == 0 and "harness" in out and "hi there" in out and "second answer" in out
    second = [m["content"] for m in calls[1]["messages"] if m["role"] in ("user", "assistant")]
    assert any("hello" in (t or "") for t in second) and "hi there" in second
    assert "100 input" not in out and "tokens," in out and "$" in out           # /cost line
    conn = init_db()
    s = get_session(conn, c.session_id)
    conn.close()
    assert s["status"] == "success" and s["prompt_tokens"] == 100 and s["cost_usd"] > 0
    assert f"harness chat --resume {c.session_id}" in out


def test_slash_commands(monkeypatch):
    install_llm(monkeypatch, [])
    c, code, out = chat("/help", "/mode", "/mode plan", "/tools", "/mode yolo", "/model some/model",
                        "/theme nope", "/theme ember", "/session", "/bogus", "/quit")
    assert "/mode [NAME]" in out and "mode: default" in out and "mode: default" in out
    assert "tools in plan mode" in out and "exit_plan_mode" in out and "write" not in out.split("tools in plan mode")[1].split("\n")[0]
    assert "Unknown permission mode" in out and "model: some/model" in out
    assert "unknown theme" in out and "theme: ember" in out and c.session_id in out and "unknown command /bogus" in out
    conn = init_db()
    ev = list_events(conn, c.session_id, types={"mode_change"})
    conn.close()
    assert ev[0]["payload"] == {"from": "default", "to": "plan", "approved_by": "user:/mode"}


def test_mode_switch_applies_to_the_next_turn(monkeypatch, workspace):
    install_llm(monkeypatch, [msg(tool_calls=[("write", {"path": "a.txt", "content": "x"})]), msg("blocked")])
    chat("/mode read-only", "write a file", "/exit", agent_id="devops_agent")
    assert not (workspace / "a.txt").exists()


def test_ctrl_c_stops_the_turn_and_the_session_keeps_working(monkeypatch, workspace):
    import asyncio

    import litellm

    calls = install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})]), msg("still here")])
    scripted_llm = litellm.acompletion

    def boom():
        raise KeyboardInterrupt        # what SIGINT does: raised in the main thread while the loop waits

    async def slow_second_call(**kw):
        if len(calls) == 1:            # second model call: hang until "Ctrl+C"
            calls.append(kw)
            asyncio.get_running_loop().call_later(0.1, boom)
            await asyncio.sleep(30)
        return await scripted_llm(**kw)

    monkeypatch.setattr(litellm, "acompletion", slow_second_call)
    c, code, out = chat("look around", "are you there?", "/exit")
    assert code == 0 and "turn stopped" in out and "still here" in out
    last = calls[-1]["messages"]
    assert last[-1]["role"] == "user" and "are you there?" in last[-1]["content"]


def test_ctrl_c_at_the_prompt_does_not_quit(monkeypatch):
    install_llm(monkeypatch, [msg("ok")])
    c, code, out = chat(KeyboardInterrupt(), "hi", "/exit")
    assert "Ctrl+D or /exit" in out and "ok" in out


def test_resume_continues_the_same_session(monkeypatch):
    install_llm(monkeypatch, [msg("remembered: blue")])
    first, _, _ = chat("my colour is blue", "/exit")
    calls = install_llm(monkeypatch, [msg("blue")])
    second, code, out = chat("what is my colour?", resume=first.session_id)
    assert code == 0 and second.session_id == first.session_id
    texts = " ".join(str(m.get("content")) for m in calls[0]["messages"])
    assert "my colour is blue" in texts and "remembered: blue" in texts


def test_unknown_agent_and_unknown_session():
    assert Chat(agent_id="nope", out=io.StringIO(), read=scripted()).run() == 2
    assert Chat(resume="missing", out=io.StringIO(), read=scripted()).run() == 2


def test_cli_entry_point(monkeypatch, capsys):
    from cli.main import main

    install_llm(monkeypatch, [msg("from main")])
    monkeypatch.setattr("builtins.input", scripted("hello", "/exit"))
    assert main(["chat", "--mode", "strict"]) == 0
    assert "from main" in capsys.readouterr().out


def test_real_sigint_cancels_only_the_turn(monkeypatch):
    import asyncio
    import os
    import signal

    import litellm

    calls = install_llm(monkeypatch, [msg("second turn fine")])
    scripted_llm = litellm.acompletion
    state = {"n": 0}

    async def first_hangs(**kw):
        state["n"] += 1
        if state["n"] == 1:
            asyncio.get_running_loop().call_later(0.1, os.kill, os.getpid(), signal.SIGINT)
            await asyncio.sleep(30)
        return await scripted_llm(**kw)

    monkeypatch.setattr(litellm, "acompletion", first_hangs)
    c, code, out = chat("hang please", "again", "/exit")
    assert code == 0 and "turn stopped" in out and "second turn fine" in out
    assert signal.getsignal(signal.SIGINT) is not None and calls
    conn = init_db()
    outcomes = [e["payload"]["outcome"] for e in list_events(conn, c.session_id, types={"outcome"})]
    conn.close()
    assert outcomes == ["cancelled", "completed"]
