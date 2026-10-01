"""The `penko` command: init, serve, run, doctor, token, sessions, approvals, plugins, version."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import secrets as pysecrets
import shutil
import sys

from core import __version__, theme
from core.home import DEFAULTS_DIR, ensure_home, env_file, harness_home, keyring_items, load_env, write_env

PROVIDERS = {
    "groq": ("GROQ_API_KEY", "groq/openai/gpt-oss-120b"),
    "openai": ("OPENAI_API_KEY", "openai/gpt-4o"),
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic/claude-sonnet-4-5"),
    "openrouter": ("OPENROUTER_API_KEY", "openrouter/auto"),
    "nvidia": ("NVIDIA_API_KEY", "nvidia_nim/meta/llama-3.1-70b-instruct"),
    "gemini": ("GEMINI_API_KEY", "gemini/gemini-2.5-flash"),
    "deepseek": ("DEEPSEEK_API_KEY", "deepseek/deepseek-chat"),
    "mistral": ("MISTRAL_API_KEY", "mistral/mistral-large-latest"),
    "lmstudio": ("", "lm_studio/qwen/qwen3-4b"),
    "ollama": ("", "ollama_chat/qwen3:4b"),
    "custom": ("", "openai/your-model"),    # any OpenAI-compatible endpoint: vLLM, TGI, LiteLLM proxy, a gateway
}
PROVIDER_ALIASES = {"local": "ollama", "lm-studio": "lmstudio", "openai-compatible": "custom"}
LMSTUDIO_URL = "http://localhost:1234/v1"


def _lmstudio_models(base: str) -> list[str]:
    """Model ids LM Studio is serving right now (empty when it is not running)."""
    try:
        import httpx

        r = httpx.get(f"{base.rstrip('/')}/models", timeout=2.0)
        return [m["id"] for m in r.json().get("data", []) if "embed" not in m["id"].lower()]
    except Exception:  # noqa: BLE001
        return []


def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    reader = getpass.getpass if secret else input
    return (reader(f"{prompt}{suffix}: ") or default).strip()


# ---------------------------------------------------------------------------
def cmd_init(args) -> int:
    load_env()
    print(theme.banner(__version__), end="")
    home = ensure_home()
    interactive = not args.yes and sys.stdin.isatty()
    provider = (args.provider or (_ask("LLM provider (" + "/".join(PROVIDERS) + ")", "groq") if interactive else "groq")).lower()
    provider = PROVIDER_ALIASES.get(provider, provider)
    if provider not in PROVIDERS:
        print(f"Unknown provider {provider!r}; choose from: {', '.join(PROVIDERS)}", file=sys.stderr)
        return 2
    key_var, default_model = PROVIDERS[provider]
    extra: dict[str, str] = {}
    if provider == "lmstudio":
        base = args.base_url or LMSTUDIO_URL
        served = _lmstudio_models(base)
        if served:
            default_model = "lm_studio/" + served[0]
            print(f"LM Studio is serving: {', '.join(served)}")
        else:
            print(f"note: LM Studio is not answering at {base}; start its server (Developer tab) and load a model.",
                  file=sys.stderr)
        # small local models: a context that fits a 16k window, and a little more time per call
        extra = {"LM_STUDIO_API_BASE": base, "HARNESS_CONTEXT_WINDOW": str(args.context_window or 16384),
                 "HARNESS_RESERVE_TOKENS": "2048", "HARNESS_KEEP_RECENT_TOKENS": "6000", "HARNESS_LLM_TIMEOUT": "300"}
    if provider == "custom":
        base = args.base_url or (_ask("Base URL of the OpenAI-compatible API (e.g. http://gpu-box:8000/v1)") if interactive else "")
        if not base:
            print("--provider custom needs --base-url (an OpenAI-compatible /v1 endpoint)", file=sys.stderr)
            return 2
        extra = {"OPENAI_API_BASE": base}
        if args.context_window:
            extra["HARNESS_CONTEXT_WINDOW"] = str(args.context_window)
    if provider == "ollama" and args.base_url:
        extra = {"OLLAMA_API_BASE": args.base_url}
    model = args.model or (_ask("Model", default_model) if interactive else default_model)
    if provider == "custom" and "/" not in model.split(":")[0]:
        model = f"openai/{model}"          # LiteLLM speaks the OpenAI protocol to the base URL

    values: dict[str, str] = {"HARNESS_MODEL": model, **extra}
    api_key = args.api_key or (os.environ.get(args.api_key_env) if args.api_key_env else None)
    if key_var and not api_key and not os.environ.get(key_var):
        api_key = _ask(f"{provider} API key (input hidden, stored in {env_file()})", secret=True) if interactive else None
    if key_var and api_key:
        values[key_var] = api_key
    elif key_var and not os.environ.get(key_var):
        print(f"note: no {provider} API key provided; add {key_var}=... to {env_file()} before running.", file=sys.stderr)
    if provider == "custom":   # the endpoint may not need a key, but the OpenAI client requires one
        values["OPENAI_API_KEY"] = api_key or os.environ.get("OPENAI_API_KEY") or "not-needed"

    token_existing = os.environ.get("HARNESS_API_TOKEN")
    values["HARNESS_API_TOKEN"] = token_existing or pysecrets.token_hex(32)

    bot = args.telegram_bot_token or (os.environ.get(args.telegram_bot_token_env) if args.telegram_bot_token_env else None)
    chat = args.telegram_chat_id
    if interactive and not bot and _ask("Set up Telegram approvals? (y/N)", "n").lower().startswith("y"):
        bot = _ask("Telegram bot token", secret=True)
        chat = _ask("Approval chat id")
    if bot and chat:
        values["HARNESS_SECRET_TELEGRAM_BOT_TOKEN"] = bot
        values["HARNESS_SECRET_TELEGRAM_APPROVAL_CHAT_ID"] = chat
        if args.approver:
            values["HARNESS_APPROVERS"] = args.approver
        elif interactive:
            uid = _ask("Telegram user id allowed to approve (blank = anyone in that chat)")
            if uid:
                values["HARNESS_APPROVERS"] = f"telegram:{uid}"

    from core import keystore

    store = args.secret_store
    if store == "auto":
        store = "keyring" if keystore.available() else "file"
    elif store == "keyring" and not keystore.available():
        print(f"No usable OS keyring here ({keystore.backend_name()}). Install one, or use --secret-store file.",
              file=sys.stderr)
        return 2
    path = write_env(values, store=store)
    agents = home / "config" / "agents.yaml"
    if not agents.exists() and not args.no_agents:
        shutil.copy(DEFAULTS_DIR / "agents.yaml", agents)
    where = (f"OS keyring ({keystore.backend_name()}); settings in {path}" if store == "keyring"
             else f"{path} (mode 600)")
    print(f"Harness home: {home}\nSecrets stored in: {where}")
    print(f"Agents: {agents}  (edit to change what agents may do)")
    print("API token: show it with `penko token`.")
    load_env(override=True)
    from cli.doctor import collect, render

    print("\n" + render(collect()))
    print(f"\n{theme.glyph('run')} Next: `penko serve`   then   `penko run \"List the files in the workspace\"`".lstrip())
    return 0


def cmd_secret(args) -> int:
    """penko secret list|set NAME|delete NAME - manage individual secrets (e.g. rotate a provider key)."""
    from core import keystore
    from core.home import _read_env_file, delete_secret, internal_name, keyring_items, public_name

    load_env()
    file_values = _read_env_file()
    in_keyring = set(keyring_items(file_values))
    if args.action == "list":
        for name in sorted(in_keyring | {k for k in file_values if keystore.is_secret_name(k) and k != keystore.ITEMS_VAR}):
            print(f"{public_name(name):<45} {'keyring' if name in in_keyring else 'file (.env)'}")
        return 0
    if not args.name:
        print("secret name required", file=sys.stderr)
        return 2
    if args.action == "delete":
        if delete_secret(args.name):
            print("deleted")
            return 0
        print("not found", file=sys.stderr)
        return 1
    name = internal_name(args.name)
    value = os.environ.get(args.from_env, "") if args.from_env else getpass.getpass(f"{args.name} (hidden): ")
    if not value:
        print("empty value", file=sys.stderr)
        return 2
    # keep a secret where the installation already keeps its secrets
    use_keyring = bool(in_keyring) and keystore.available()
    write_env({name: value}, store="keyring" if use_keyring else "file")
    os.environ[name] = value
    print(f"{args.name} stored in {'the OS keyring' if use_keyring else str(env_file())}")
    return 0


def cmd_token(args) -> int:
    load_env()
    token = os.environ.get("HARNESS_API_TOKEN")
    if not token:
        print("No API token configured. Run `penko init`.", file=sys.stderr)
        return 1
    print(token)
    return 0


def cmd_serve(args) -> int:
    load_env()
    ensure_home()
    from core.settings import settings

    st = settings()
    host, port = args.host or st.api_host, args.port or st.api_port
    if not st.api_tokens:
        print("PENKO_API_TOKEN is not set: the API would reject every request. Run `penko init`.", file=sys.stderr)
        return 1
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"warning: binding to {host}; make sure the API is not reachable by untrusted networks.", file=sys.stderr)
    import uvicorn

    print(theme.banner(__version__, sys.stderr), end="", file=sys.stderr)
    print(f"Dashboard: {_dashboard_url(host, port)}   (open it signed in with `penko dashboard`)", file=sys.stderr)
    uvicorn.run("core.gateway.api:app", host=host, port=port, log_level=args.log_level)
    return 0


def _dashboard_url(host: str, port: int) -> str:
    shown = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    return f"http://{'[' + shown + ']' if ':' in shown else shown}:{port}/ui"


def cmd_dashboard(args) -> int:
    """Open the web dashboard, signed in: the token travels in the URL fragment, which is never sent to a server."""
    load_env()
    from core.settings import settings

    st = settings()
    token = os.environ.get("HARNESS_API_TOKEN")
    if not token:
        print("No API token configured. Run `penko init`.", file=sys.stderr)
        return 1
    url = _dashboard_url(args.host or st.api_host, args.port or st.api_port)
    if args.print_url:
        print(url)
        return 0
    import webbrowser

    if not webbrowser.open(f"{url}#token={token}"):
        print(f"Open {url} and paste the token from `penko token`.")
    else:
        print(f"Opened {url} (start the server with `penko serve` if it is not running).")
    return 0


def _usage_line(usage: dict | None) -> str:
    from core.cost import fmt

    if not usage:
        return ""
    tokens = (usage.get("prompt") or 0) + (usage.get("completion") or 0)
    extra = f", {usage['unpriced_calls']} unpriced call(s)" if usage.get("unpriced_calls") else ""
    return f"{tokens:,} tokens, {fmt(usage.get('cost_usd'))}{extra}"


def _goal_text(args) -> str | None:
    if args.goal == ["-"]:
        return sys.stdin.read().strip() or None
    if args.goal_file:
        with open(args.goal_file, encoding="utf-8") as fh:
            return fh.read().strip() or None
    return " ".join(args.goal).strip() or None


def cmd_run(args) -> int:
    from core import headless

    load_env()
    ensure_home()
    goal = _goal_text(args)
    if not goal:
        print("no goal given (pass it as arguments, `-` for stdin, or --goal-file)", file=sys.stderr)
        return headless.EXIT_USAGE
    if args.max_cost:
        os.environ["HARNESS_MAX_COST_USD"] = str(args.max_cost)
    if args.approval_timeout is not None:
        os.environ["HARNESS_APPROVAL_TIMEOUT"] = str(args.approval_timeout)
    if args.model:
        os.environ["HARNESS_MODEL"] = args.model
    from core.gateway.cli import UnknownAgent, handle_cli_input

    fmt_ = args.output_format
    verification = ({"type": "file_content", "path": args.verify_file[0], "expected_content": args.verify_file[1]}
                    if args.verify_file else None)

    def on_event(event: dict) -> None:
        line = headless.stream_line(event)
        if line:
            print(line, flush=True)

    try:
        receipt = asyncio.run(handle_cli_input(
            goal, verification, args.agent, permission_mode=args.mode,
            on_event=on_event if fmt_ == "stream-json" else None, live_status=fmt_ in {"receipt", "text"}))
    except UnknownAgent as error:
        print(str(error), file=sys.stderr)
        return headless.EXIT_USAGE
    res = headless.result(receipt)
    if fmt_ == "receipt":
        print(receipt.model_dump_json(indent=2))
    elif fmt_ == "text":
        print(receipt.final_text)
    else:
        print(json.dumps(res, default=str, separators=(",", ":") if fmt_ == "stream-json" else None,
                         indent=None if fmt_ == "stream-json" else 2))
    if args.summary_file:
        with open(args.summary_file, "a", encoding="utf-8") as fh:
            fh.write(headless.summary_markdown(res))
    if theme.styled(sys.stderr) and fmt_ in {"receipt", "text"}:
        ok = receipt.status == "success"
        print(f"\n{theme.glyph('receipt', sys.stderr)} {theme.status_mark('ok' if ok else 'fail', sys.stderr)} "
              f"{theme.paint(str(receipt.status), 'accent', sys.stderr)}  {_usage_line(receipt.usage)}", file=sys.stderr)
    return res["exit_code"]


def cmd_chat(args) -> int:
    load_env()
    ensure_home()
    if args.max_cost:
        os.environ["HARNESS_MAX_COST_USD"] = str(args.max_cost)
    from cli.chat import Chat, enable_history

    if sys.stdin.isatty():
        enable_history()
    return Chat(agent_id=args.agent, mode=args.mode, model=args.model, resume=args.resume).run()


def cmd_doctor(args) -> int:
    from cli.doctor import as_dicts, collect, render

    checks = collect(online=args.online)
    print(json.dumps(as_dicts(checks), indent=2) if args.json else render(checks))
    return 1 if any(c.status == "fail" for c in checks) else 0


def cmd_sessions(args) -> int:
    load_env()
    from core.memory.store import get_session, init_db

    conn = init_db()
    try:
        if args.session_id:
            session = get_session(conn, args.session_id)
            if not session:
                print("not found", file=sys.stderr)
                return 1
            print(json.dumps(session, indent=2, default=str))
            return 0
        from core.cost import fmt

        rows = conn.execute("SELECT id, status, outcome, agent_id, goal, cost_usd, updated_at FROM sessions "
                            "WHERE parent_session_id IS NULL ORDER BY updated_at DESC LIMIT ?", (args.limit,)).fetchall()
        for r in rows:
            print(f"{r['id']}  {r['status']:<8} {(r['outcome'] or '-'):<17} {r['agent_id']:<14} "
                  f"{fmt(r['cost_usd']):>9}  {r['goal'][:60]}")
        if not rows:
            print("no sessions yet")
    finally:
        conn.close()
    return 0


def cmd_cost(args) -> int:
    load_env()
    from datetime import datetime, timedelta, timezone

    from core.cost import fmt
    from core.memory.store import init_db, usage_summary

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    conn = init_db()
    try:
        rows = usage_summary(conn, since=since, group_by=args.by)
    finally:
        conn.close()
    if args.json:
        print(json.dumps({"days": args.days, "by": args.by, "rows": rows}, indent=2))
        return 0
    if not rows:
        print(f"no model calls in the last {args.days} day(s)")
        return 0
    print(f"{args.by:<42} {'calls':>6} {'input tok':>11} {'output tok':>11} {'cost':>10}")
    for r in rows:
        note = f"  ({r['unpriced_calls']} unpriced)" if r["unpriced_calls"] else ""
        print(f"{str(r['key'])[:42]:<42} {r['calls']:>6} {r['prompt_tokens']:>11,} {r['completion_tokens']:>11,} "
              f"{fmt(r['cost_usd']):>10}{note}")
    total = sum(r["cost_usd"] for r in rows)
    unpriced = sum(r["unpriced_calls"] for r in rows)
    print(f"\n{theme.glyph('receipt')} total {fmt(total)} over {args.days} day(s)".replace("  ", " ")
          + (f"; {unpriced} call(s) have no known price (set PENKO_PRICES)" if unpriced else ""))
    return 0


def _api(args, method: str, path: str, body: dict | None = None):
    import httpx

    load_env()
    token = os.environ.get("HARNESS_API_TOKEN", "")
    from core.settings import settings

    url = (args.url or f"http://127.0.0.1:{settings().api_port}") + path
    return httpx.request(method, url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=15)


def cmd_approvals(args) -> int:
    try:
        if args.action == "list":
            resp = _api(args, "GET", "/approvals")
        else:
            resp = _api(args, "POST", f"/approvals/{args.approval_id}",
                        {"approved": args.action == "approve", "scope": args.scope, "note": args.note})
    except Exception as error:  # noqa: BLE001
        print(f"Could not reach the API: {error}. Is `penko serve` running?", file=sys.stderr)
        return 1
    if resp.status_code != 200:
        print(f"{resp.status_code}: {resp.text}", file=sys.stderr)
        return 1
    data = resp.json()
    if args.action == "list":
        for a in data:
            print(f"{a['id']}  {theme.risk_mark(a['risk_tier'])} {a['risk_tier']}  {a['tool']}\n    {a['rendered'][:300].replace(chr(10), chr(10) + '    ')}")
        if not data:
            print("no pending approvals")
    else:
        print(data["status"])
    return 0


def cmd_plugins(args) -> int:
    load_env()
    from core.engine import Engine

    async def go():
        engine = Engine()
        await engine.ensure_started()
        for p in engine.plugins.status():
            mark = theme.status_mark("fail" if p["error"] else "ok") if theme.styled() else ""
            print(f"{mark + ' ' if mark else ''}{p['name']:<12} {p['state']:<8} {', '.join(p['tools'])[:80]}"
                  + (f"  ERROR: {p['error']}" if p["error"] else ""))
        await engine.shutdown()

    asyncio.run(go())
    return 0


def cmd_theme(args) -> int:
    load_env()
    skins = theme.available()
    name = theme.current_name()
    if args.action == "list":
        for key, skin in skins.items():
            mark = "*" if key == name else " "
            print(f"{mark} {theme.preview(skin) if theme.styled() else f'{key:<9} {skin.description}'}")
        print(f"\nActive: {name}. Change it with `penko theme set NAME`; add your own in {theme.skins_dir()}/NAME.yaml")
        return 0
    if args.action == "show":
        print(theme.banner(__version__), end="")
        print(f"theme: {theme.current().name} ({theme.current().description})")
        return 0
    if not args.name or args.name not in skins:
        print(f"Unknown theme {args.name!r}. Available: {', '.join(skins)}", file=sys.stderr)
        return 2
    write_env({"HARNESS_THEME": args.name}, store="keyring" if keyring_items() else "file")
    os.environ["HARNESS_THEME"] = args.name
    print(theme.banner(__version__), end="")
    print(f"Theme set to {args.name}.")
    return 0


def cmd_version(args) -> int:
    print(theme.banner(__version__), end="")
    print(f"penko-perry {__version__}  (home: {harness_home()})")
    return 0


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="penko", description="Penko Perry: policy-gated, verified, audited agents for DevOps "
                                "(`penko` works as an alias)")
    sub = p.add_subparsers(dest="command")

    i = sub.add_parser("init", help="first-run setup (model, key, API token, approvals)")
    i.add_argument("--provider", choices=list(PROVIDERS) + list(PROVIDER_ALIASES),
                   help="hosted: groq, openai, anthropic, openrouter, nvidia, gemini, deepseek, mistral; "
                        "self-hosted: lmstudio, ollama, custom (any OpenAI-compatible URL)")
    i.add_argument("--model")
    i.add_argument("--api-key", help="prefer --api-key-env: command lines end up in shell history")
    i.add_argument("--api-key-env", metavar="VAR", help="read the provider key from this environment variable")
    i.add_argument("--base-url", help="server URL for lmstudio (default http://localhost:1234/v1), ollama "
                   "(default http://localhost:11434) or custom (required, an OpenAI-compatible /v1 URL)")
    i.add_argument("--context-window", type=int, help="context length the model was loaded with (lmstudio: 16384)")
    i.add_argument("--telegram-bot-token")
    i.add_argument("--telegram-bot-token-env", metavar="VAR")
    i.add_argument("--telegram-chat-id")
    i.add_argument("--approver", help="allowed approver ids, e.g. telegram:123")
    i.add_argument("--secret-store", choices=["auto", "keyring", "file"], default="auto",
                   help="where secrets live: the OS keyring (default when available) or the mode-600 .env file")
    i.add_argument("--no-agents", action="store_true", help="do not copy the default agents.yaml")
    i.add_argument("-y", "--yes", action="store_true", help="non-interactive: use defaults and flags only")
    i.set_defaults(fn=cmd_init)

    s = sub.add_parser("serve", help="start the API")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--log-level", default="info")
    s.set_defaults(fn=cmd_serve)

    r = sub.add_parser("run", help="run one goal (headless-friendly; see --output-format and exit codes)",
                       description="Exit codes: 0 success, 1 failure, 2 usage error, 3 a budget/turn/time limit "
                                   "stopped the run.")
    r.add_argument("goal", nargs="*", help="the goal; `-` reads it from stdin")
    r.add_argument("--goal-file", metavar="PATH")
    r.add_argument("--output-format", choices=["receipt", "json", "stream-json", "text"], default="receipt")
    r.add_argument("--summary-file", metavar="PATH", help="append a Markdown summary (e.g. $GITHUB_STEP_SUMMARY)")
    r.add_argument("--approval-timeout", type=float, metavar="SECONDS",
                   help="how long to wait for a human; 0 denies anything that needs approval (CI)")
    r.add_argument("--model", help="override PENKO_MODEL for this run")
    r.add_argument("--agent", default="devops_agent")
    r.add_argument("--verify-file", nargs=2, metavar=("PATH", "EXPECTED"))
    r.add_argument("--max-cost", type=float, metavar="USD", help="stop the run once it has spent this much")
    r.add_argument("--mode", choices=["default", "plan", "read-only", "strict"],
                   help="permission mode: plan = read-only until you approve the plan")
    r.set_defaults(fn=cmd_run)

    db = sub.add_parser("dashboard", help="open the web dashboard (served by `penko serve` at /ui)")
    db.add_argument("--host")
    db.add_argument("--port", type=int)
    db.add_argument("--print-url", action="store_true", help="print the URL (without the token) instead of opening it")
    db.set_defaults(fn=cmd_dashboard)

    ch = sub.add_parser("chat", help="interactive multi-turn session (approvals inline, /help for commands)")
    ch.add_argument("--agent", default="devops_agent")
    ch.add_argument("--mode", choices=["default", "plan", "read-only", "strict"])
    ch.add_argument("--model")
    ch.add_argument("--max-cost", type=float, metavar="USD")
    ch.add_argument("--resume", metavar="SESSION_ID")
    ch.set_defaults(fn=cmd_chat)

    d = sub.add_parser("doctor", help="check the installation and print fixes")
    d.add_argument("--online", action="store_true", help="also make a tiny model call")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_doctor)

    sub.add_parser("token", help="print the API token").set_defaults(fn=cmd_token)

    sc = sub.add_parser("secret", help="list, set or delete individual secrets (never prints values)")
    sc.add_argument("action", choices=["list", "set", "delete"])
    sc.add_argument("name", nargs="?")
    sc.add_argument("--from-env", metavar="VAR", help="read the value from this environment variable")
    sc.set_defaults(fn=cmd_secret)

    ss = sub.add_parser("sessions", help="list recent sessions or show one")
    ss.add_argument("session_id", nargs="?")
    ss.add_argument("--limit", type=int, default=20)
    ss.set_defaults(fn=cmd_sessions)

    a = sub.add_parser("approvals", help="list or decide pending approvals on a running server")
    a.add_argument("action", choices=["list", "approve", "deny"])
    a.add_argument("approval_id", nargs="?")
    a.add_argument("--scope", default="once", choices=["once", "session", "always"])
    a.add_argument("--note")
    a.add_argument("--url")
    a.set_defaults(fn=cmd_approvals)

    th = sub.add_parser("theme", help="list, show or set the terminal theme (helm, harbor, ember, forest, midnight, mono)")
    th.add_argument("action", choices=["list", "show", "set"], nargs="?", default="list")
    th.add_argument("name", nargs="?")
    th.set_defaults(fn=cmd_theme)

    co = sub.add_parser("cost", help="token and USD usage from the event log")
    co.add_argument("--days", type=int, default=30)
    co.add_argument("--by", choices=["model", "agent", "day", "session"], default="model")
    co.add_argument("--json", action="store_true")
    co.set_defaults(fn=cmd_cost)

    sub.add_parser("plugins", help="list plugins and their state").set_defaults(fn=cmd_plugins)
    sub.add_parser("version").set_defaults(fn=cmd_version)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        load_env()
        print(theme.banner(__version__), end="")
        parser.print_help()
        return 0
    if args.command == "approvals" and args.action != "list" and not args.approval_id:
        print("approval id required", file=sys.stderr)
        return 2
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
