"""`harness chat`: an interactive, multi-turn session on the same engine, policy and event log as every run.

Each message you type becomes a turn in one durable session, so the whole conversation is resumable
(`--resume ID`), searchable and tamper-evident like any other run. Approvals appear inline; Ctrl+C stops the
current turn (the session stays usable); Ctrl+D or /exit leaves. Type /help for the commands.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Callable, TextIO

from core import theme
from core.cost import fmt

COMMANDS = {
    "/help": "show this help",
    "/cost": "tokens and USD spent in this chat",
    "/mode [NAME]": "show or switch the permission mode: default, plan, read-only, strict",
    "/model [NAME]": "show or switch the model for the next turns",
    "/tools": "tools this agent can use in the current mode",
    "/theme [NAME]": "show or switch the terminal theme",
    "/session": "show the session id (resume later with `harness chat --resume ID`)",
    "/new": "start a fresh session",
    "/exit": "leave (Ctrl+D also works)",
}


class Chat:
    def __init__(self, agent_id: str = "devops_agent", mode: str | None = None, model: str | None = None,
                 resume: str | None = None, out: TextIO | None = None,
                 read: Callable[[str], str] | None = None) -> None:
        self.agent_id, self.model = agent_id, model
        self.requested_mode = mode
        self.out = out or sys.stdout
        self.read = read or input
        self.session_id = resume
        self.loop = asyncio.new_event_loop()
        self.engine = self.agents = self.profile = self.budget = None
        self.usage = {"prompt": 0, "completion": 0, "turns": 0, "cost_usd": 0.0, "unpriced_calls": 0}
        self.turns = 0
        self._disposers: list = []

    # -- output helpers ------------------------------------------------------------------------
    def say(self, text: str = "", role: str | None = None) -> None:
        print(theme.paint(text, role, self.out) if role else text, file=self.out, flush=True)

    def g(self, name: str) -> str:
        return theme.glyph(name, self.out)

    # -- lifecycle -------------------------------------------------------------------------------
    def setup(self) -> int:
        from core.engine import get_engine
        from core.gateway.channels import start_telegram, terminal_channel
        from core.memory.store import create_session, get_session, init_db
        from core.modes import normalize
        from core.registry import AgentRegistry
        from core.settings import settings
        from core.tools import Budget

        self.agents = AgentRegistry()
        self.profile = self.agents.get_agent(self.agent_id)
        if self.profile is None:
            print(f"Unknown agent: {self.agent_id}", file=sys.stderr)
            return 2
        self.requested_mode = normalize(self.requested_mode)
        self.engine = get_engine()
        self.engine.extras["agents"] = self.agents
        self.loop.run_until_complete(self.engine.ensure_started())
        st = settings()
        self.budget = Budget(self.profile.token_budget or st.token_budget,
                             cost_limit=self.profile.max_cost_usd or st.max_cost_usd)
        conn = init_db()
        try:
            if self.session_id:
                existing = get_session(conn, self.session_id)
                if not existing:
                    print(f"No session {self.session_id}", file=sys.stderr)
                    return 2
                self.agent_id = existing["agent_id"]
                self.profile = self.agents.get_agent(self.agent_id) or self.profile
                self.requested_mode = self.requested_mode or existing.get("permission_mode")
                self._load_usage(conn)
            else:
                self.session_id = str(uuid.uuid4())
                create_session(conn, self.session_id, self.agent_id, "(interactive chat)",
                               permission_mode=self.requested_mode)
        finally:
            conn.close()

        async def channels():
            tg = start_telegram(self.engine.broker)
            term = terminal_channel(self.engine.broker)
            return tg, term

        tg, term = self.loop.run_until_complete(channels())
        if term:
            self._disposers.append(term)
        if tg:
            self._disposers.append(lambda: self.loop.run_until_complete(tg.stop()))
        return 0

    def _load_usage(self, conn) -> None:
        from core.memory.store import usage_summary

        rows = usage_summary(conn, group_by="session")
        row = next((r for r in rows if r["key"] == self.session_id), None)
        if row:
            self.usage.update(prompt=row["prompt_tokens"], completion=row["completion_tokens"],
                              cost_usd=row["cost_usd"], unpriced_calls=row["unpriced_calls"])
            self.budget.add(row["prompt_tokens"] + row["completion_tokens"], row["cost_usd"])

    def close(self) -> None:
        for dispose in self._disposers:
            try:
                dispose()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.loop.run_until_complete(self.engine.shutdown()) if self.engine else None
        finally:
            self.loop.close()

    # -- state ------------------------------------------------------------------------------------
    def current_mode(self) -> str:
        from core.eventlog import list_events
        from core.memory.store import init_db
        from core.modes import default_mode

        conn = init_db()
        try:
            changes = list_events(conn, self.session_id, types={"mode_change"})
        finally:
            conn.close()
        if changes:
            return changes[-1]["payload"]["to"]
        return self.requested_mode or self.profile.permission_mode or default_mode()

    def current_model(self) -> str:
        from core.settings import settings

        return self.model or self.profile.model or settings().model

    def status_line(self) -> str:
        tokens = self.usage["prompt"] + self.usage["completion"]
        unpriced = f" +{self.usage['unpriced_calls']} unpriced" if self.usage["unpriced_calls"] else ""
        return (f"[{self.current_mode()}] {self.current_model()} · {tokens:,} tok · "
                f"{fmt(self.usage['cost_usd'])}{unpriced} · {self.session_id[:8]}")

    # -- the REPL ---------------------------------------------------------------------------------
    def run(self) -> int:
        code = self.setup()
        if code:
            self.loop.close()
            return code
        try:
            banner = theme.banner(__import__("core").__version__, self.out)
            if banner:
                self.out.write(banner)
            self.say(f"Chatting with {self.agent_id}. /help for commands, Ctrl+C stops a turn, Ctrl+D quits.", "dim")
            self.say(self.status_line(), "dim")
            while True:
                try:
                    line = self.read(theme.paint("› ", "brand", self.out))
                except EOFError:
                    self.say()
                    break
                except KeyboardInterrupt:
                    self.say("\n(Ctrl+D or /exit to leave)", "dim")
                    continue
                line = line.strip()
                if not line:
                    continue
                if line.startswith("/"):
                    if self.command(line) == "exit":
                        break
                    continue
                self.turn(line)
        finally:
            self.close()
        self.say(f"Session {self.session_id} saved. Resume with: harness chat --resume {self.session_id}", "dim")
        return 0

    def turn(self, text: str) -> None:
        import signal

        task = self.loop.create_task(self._turn(text))
        handled = False
        try:   # Ctrl+C cancels the turn cleanly instead of raising wherever the code happens to be
            self.loop.add_signal_handler(signal.SIGINT, task.cancel)
            handled = True
        except (NotImplementedError, RuntimeError, ValueError):   # Windows, or not the main thread
            pass
        try:
            self.loop.run_until_complete(task)
        except (KeyboardInterrupt, asyncio.CancelledError):
            task.cancel()
            try:   # let the run record its cancellation, but never hang on a broken task
                self.loop.run_until_complete(asyncio.wait({task}, timeout=10))
            except KeyboardInterrupt:
                pass
            self.say(f"\n{self.g('deny')} turn stopped".strip(), "warn")
            self._save("cancelled")
        finally:
            if handled:
                self.loop.remove_signal_handler(signal.SIGINT)

    async def _turn(self, text: str) -> None:
        from core.loop import DBSink, run_agent_generator
        from core.memory.store import init_db, search_memory
        from core.modes import NOTES
        from core.primitives.context import ContextPacket
        from core.primitives.goal import Goal, TriggerSource
        from core.prompt import build_prompt

        conn = init_db()
        profile = self.profile.model_copy(update={"model": self.model}) if self.model else self.profile
        try:
            goal = Goal(id=self.session_id, source=TriggerSource.cli, raw_input=text,
                        created_at=datetime.now(timezone.utc), domain=profile.domain)
            context = ContextPacket(goal=goal, memory_hits=search_memory(conn, text, profile.domain))
            # always a new user message, even after a stopped turn left the transcript ending in a tool result
            sink = DBSink(conn, self.session_id)
            sink.append("user_msg", {"content": build_prompt(context) + NOTES.get(self.current_mode(), "")})
            outcome = "error"
            async for ev in run_agent_generator(self.session_id, context, profile.allowed_tools, profile,
                                                engine=self.engine, sink=sink,
                                                budget=self.budget, mode=self.requested_mode):
                outcome = self.render(ev) or outcome
        finally:
            conn.close()
        self._save(outcome)

    def render(self, ev: dict) -> str | None:
        t = ev.get("type")
        if t == "message":
            self.say(f"{theme.paint('harness', 'brand', self.out)} {self.g('arrow')} {ev['content']}")
        elif t == "tool_call":
            args = ", ".join(f"{k}={str(v)[:60]}" for k, v in (ev.get("arguments") or {}).items())
            self.say(f"  {self.g('tool')} {ev['name']}({args})", "dim")
        elif t == "tool_result":
            first = (ev.get("result_summary") or "").strip().splitlines()[:1]
            mark = theme.status_mark("fail" if ev.get("is_error") else "ok", self.out)
            self.say(f"    {mark} {(first[0] if first else '')[:140]}")
        elif t == "usage":
            self.usage["prompt"] += ev.get("prompt_tokens") or 0
            self.usage["completion"] += ev.get("completion_tokens") or 0
            if ev.get("cost_usd") is None:
                self.usage["unpriced_calls"] += 1
            else:
                self.usage["cost_usd"] = round(self.usage["cost_usd"] + ev["cost_usd"], 8)
        elif t == "interruption_received":
            self.say(f"  (queued note: {ev['content']})", "dim")
        elif t == "final_receipt":
            r = ev["receipt"]
            self.turns += 1
            if r["outcome"] != "completed":
                self.say(f"{self.g('warn')} {r['outcome']}: {r['final_text']}".strip(), "warn")
            self.say(self.status_line(), "dim")
            return r["outcome"]
        return None

    def _save(self, outcome: str) -> None:
        from core.memory.store import init_db, update_session

        conn = init_db()
        try:
            update_session(conn, self.session_id, "success" if outcome == "completed" else "failure",
                           outcome=outcome, usage=self.usage)
        finally:
            conn.close()

    # -- slash commands ---------------------------------------------------------------------------
    def command(self, line: str) -> str | None:
        name, _, arg = line.partition(" ")
        arg = arg.strip()
        name = name.lower()
        if name in {"/exit", "/quit", "/q"}:
            return "exit"
        if name in {"/help", "/?"}:
            for cmd, text in COMMANDS.items():
                self.say(f"  {cmd:<16} {text}")
        elif name == "/cost":
            u = self.usage
            self.say(f"{self.g('receipt')} {u['prompt']:,} input + {u['completion']:,} output tokens, "
                     f"{fmt(u['cost_usd'])}".strip()
                     + (f", {u['unpriced_calls']} call(s) without a known price" if u["unpriced_calls"] else "")
                     + (f" (limit {fmt(self.budget.cost_limit)})" if self.budget.cost_limit else ""))
        elif name == "/mode":
            self._mode(arg)
        elif name == "/model":
            if arg:
                self.model = arg
            self.say(f"model: {self.current_model()}")
        elif name == "/tools":
            self._tools()
        elif name == "/theme":
            if arg:
                if arg not in theme.available():
                    self.say(f"unknown theme; choose from {', '.join(theme.available())}", "warn")
                    return None
                os.environ["HARNESS_THEME"] = arg
            self.say(f"theme: {theme.current_name()}")
        elif name == "/session":
            self.say(self.session_id)
        elif name == "/new":
            from core.memory.store import create_session, init_db

            self.session_id = str(uuid.uuid4())
            conn = init_db()
            try:
                create_session(conn, self.session_id, self.agent_id, "(interactive chat)",
                               permission_mode=self.requested_mode)
            finally:
                conn.close()
            self.usage = {k: 0 for k in self.usage} | {"cost_usd": 0.0}
            self.say(f"new session {self.session_id}", "dim")
        else:
            self.say(f"unknown command {name}; /help lists them", "warn")
        return None

    def _mode(self, arg: str) -> None:
        from core.eventlog import append_event
        from core.memory.store import init_db
        from core.modes import normalize

        if not arg:
            self.say(f"mode: {self.current_mode()}")
            return
        try:
            new = normalize(arg)
        except ValueError as error:
            self.say(str(error), "warn")
            return
        old = self.current_mode()
        conn = init_db()
        try:   # recorded in the event log, so resumes and audits see who changed it
            append_event(conn, self.session_id, "mode_change", {"from": old, "to": new, "approved_by": "user:/mode"})
        finally:
            conn.close()
        self.requested_mode = new
        self.say(f"mode: {old} {self.g('arrow')} {new}".replace("  ", " "))

    def _tools(self) -> None:
        from core.engine import expand_capabilities
        from core.modes import READ_ONLY_MODES

        mode = self.current_mode()
        allowed = expand_capabilities(self.profile.allowed_tools) | ({"Plan"} if mode == "plan" else set())
        names = [s["function"]["name"] for s in self.engine.snapshot().schemas(
            allowed, set(self.profile.deny_tools), read_only=mode in READ_ONLY_MODES)]
        self.say(f"{len(names)} tools in {mode} mode: " + ", ".join(names))


def enable_history() -> None:
    """Line editing and a persistent history file where readline exists (not on plain Windows)."""
    try:
        import atexit
        import readline

        from core.home import harness_home

        path = harness_home() / "chat_history"
        try:
            readline.read_history_file(path)
        except OSError:
            pass
        readline.set_history_length(1000)
        atexit.register(lambda: _save_history(readline, path))
    except ImportError:
        pass


def _save_history(readline, path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        readline.write_history_file(path)
        os.chmod(path, 0o600)
    except OSError:
        pass
