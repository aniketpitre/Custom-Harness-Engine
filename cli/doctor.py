"""`harness doctor`: checks the installation and prints the exact fix for anything that is wrong."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import socket
import sys
from dataclasses import asdict, dataclass

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _binary(name: str, needed_for: str, level: str = WARN) -> Check:
    path = shutil.which(name)
    if path:
        return Check(name, OK, path)
    return Check(name, level, f"not found (needed for {needed_for})", f"install {name} and make sure it is on PATH")


def _module(mod: str, extra: str, needed_for: str) -> Check:
    if importlib.util.find_spec(mod):
        return Check(f"python:{mod}", OK, "installed")
    return Check(f"python:{mod}", WARN, f"not installed (needed for {needed_for})",
                 f'pip install "harness-engine[{extra}]"')


def collect(online: bool = False, port: int | None = None) -> list[Check]:
    from core.home import env_file, harness_home, is_private, load_env
    from core.registry import AgentRegistry
    from core.secrets import get_llm_key
    from core.settings import settings

    load_env()
    st = settings()
    checks: list[Check] = []
    ok_py = sys.version_info >= (3, 11)
    checks.append(Check("python", OK if ok_py else FAIL, sys.version.split()[0],
                        "" if ok_py else "Harness Engine needs Python 3.11 or newer"))

    home = harness_home()
    writable = home.exists() and os.access(home, os.W_OK)
    checks.append(Check("home", OK if writable else WARN, str(home),
                        "" if writable else "run `harness init` to create it"))
    env = env_file()
    if env.exists():
        private = is_private(env)
        checks.append(Check("env file", OK if private else FAIL, f"{env} ({'mode 600' if private else 'readable by others'})",
                            "" if private else f"chmod 600 {env}"))

    checks.append(Check("api token", OK if st.api_tokens else FAIL,
                        "configured" if st.api_tokens else "HARNESS_API_TOKEN is not set (API refuses all requests)",
                        "" if st.api_tokens else "run `harness init` (or export HARNESS_API_TOKEN=$(openssl rand -hex 32))"))
    checks.append(Check("model", OK, st.model + (f" (fallbacks: {', '.join(st.fallback_models)})" if st.fallback_models else "")))
    key = get_llm_key(st.model)
    local = st.model.split("/")[0] in {"ollama", "ollama_chat"} or bool(os.environ.get("OPENAI_API_BASE"))
    if key or local:
        checks.append(Check("provider key", OK, "found" if key else "not needed (local model)"))
    else:
        provider = st.model.split("/")[0]
        checks.append(Check("provider key", WARN, f"no key found for '{provider}' (LiteLLM may still find one in the environment)",
                            f"run `harness init`, or export {provider.upper()}_API_KEY=..."))

    try:
        agents = AgentRegistry()._agents
        checks.append(Check("agents", OK if agents else FAIL, f"{len(agents)} profile(s): {', '.join(sorted(agents))}" if agents
                            else "no agent profiles found", "" if agents else "run `harness init` to create config/agents.yaml"))
    except Exception as error:  # noqa: BLE001
        checks.append(Check("agents", FAIL, f"invalid agents.yaml: {error}", "fix the YAML or delete it to use the defaults"))

    try:
        from core.memory.store import init_db

        conn = init_db()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        checks.append(Check("database", OK, f"{st.db_path} (journal_mode={mode})"))
    except Exception as error:  # noqa: BLE001
        checks.append(Check("database", FAIL, str(error), "check permissions on HARNESS_HOME/data"))

    checks.append(_binary("git", "GitOps pull requests"))
    checks.append(_binary("gh", "opening pull requests (GitOps)"))
    checks.append(_binary("kubectl", "diagnosing Kubernetes (optional)"))
    checks.append(_binary("argocd", "ArgoCD tools"))
    if st.sandbox == "bwrap":
        checks.append(_binary("bwrap", "HARNESS_SANDBOX=bwrap (fails closed without it)", FAIL))
    elif st.sandbox == "docker":
        checks.append(_binary("docker", "HARNESS_SANDBOX=docker (fails closed without it)", FAIL))
    else:
        bwrap = shutil.which("bwrap")
        checks.append(Check("sandbox", OK if bwrap else WARN,
                            "bwrap available" if bwrap else "shell tool runs without a sandbox",
                            "" if bwrap else "install bubblewrap and set HARNESS_SANDBOX=bwrap for a network-isolated shell"))

    checks.append(_module("telegram", "telegram", "Telegram approvals"))
    checks.append(_module("kubernetes", "devops", "Kubernetes tools"))
    checks.append(_module("git", "devops", "GitOps"))
    checks.append(_module("mcp", "mcp", "MCP servers"))
    if os.environ.get("VAULT_ADDR"):
        checks.append(_module("hvac", "vault", "Vault secrets"))
    if st.otel_endpoint:
        checks.append(_module("opentelemetry.exporter.otlp.proto.grpc.trace_exporter", "otel", "OpenTelemetry export"))

    telegram_ready = bool(os.environ.get("HARNESS_SECRET_TELEGRAM_BOT_TOKEN") and os.environ.get("HARNESS_SECRET_TELEGRAM_APPROVAL_CHAT_ID"))
    checks.append(Check("approvals", OK if telegram_ready else WARN,
                        "Telegram configured" if telegram_ready else "using terminal / API approvals (no Telegram)",
                        "" if telegram_ready else "optional: `harness init` can configure Telegram"))

    p = port or st.api_port
    with socket.socket() as s:
        s.settimeout(0.3)
        busy = s.connect_ex((st.api_host if st.api_host != "0.0.0.0" else "127.0.0.1", p)) == 0
    checks.append(Check("port", WARN if busy else OK, f"{st.api_host}:{p} is {'in use' if busy else 'free'}",
                        "stop the other process or use `harness serve --port N`" if busy else ""))

    if online:
        try:
            from core.llm import simple_completion

            reply = asyncio.run(asyncio.wait_for(simple_completion("Reply with the single word OK.", st), 45))
            checks.append(Check("model reachable", OK, f"replied: {reply.strip()[:40]!r}"))
        except Exception as error:  # noqa: BLE001
            checks.append(Check("model reachable", FAIL, str(error)[:200], "check the model name, key and network"))
    return checks


def render(checks: list[Check]) -> str:
    icon = {OK: "✓", WARN: "!", FAIL: "✗"}
    lines = []
    for c in checks:
        lines.append(f" {icon[c.status]} {c.name:<18} {c.detail}")
        if c.fix and c.status != OK:
            lines.append(f"     → {c.fix}")
    fails = sum(c.status == FAIL for c in checks)
    warns = sum(c.status == WARN for c in checks)
    lines.append(f"\n{fails} problem(s), {warns} warning(s)." + ("" if fails else " Ready to go: `harness serve`."))
    return "\n".join(lines)


def as_dicts(checks: list[Check]) -> list[dict]:
    return [asdict(c) for c in checks]
