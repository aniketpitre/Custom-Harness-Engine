"""bash tool: command classifier (hard blocklist + read-only allowlist), filtered environment,
optional bubblewrap/docker sandbox, output caps, and process cleanup through effect disposers."""
from __future__ import annotations

import asyncio
import os
import shutil
import signal

from core.confine import classify_command, safe_env
from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.settings import settings
from core.tools import ToolSpec

MAX_CAPTURE = 200_000


def build_argv(command: str, backend: str, workspace: str) -> list[str]:
    """Wrap `command` for the chosen sandbox backend. Raises if the backend is unavailable."""
    if backend == "none":
        return ["bash", "-c", command]
    if backend == "bwrap":
        if not shutil.which("bwrap"):
            raise RuntimeError("Sandbox 'bwrap' requested but bubblewrap is not installed")
        return ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                "--bind", workspace, workspace, "--unshare-net", "--unshare-pid", "--die-with-parent",
                "--chdir", workspace, "bash", "-c", command]
    if backend == "docker":
        if not shutil.which("docker"):
            raise RuntimeError("Sandbox 'docker' requested but docker is not installed")
        image = os.environ.get("HARNESS_SANDBOX_IMAGE", "python:3.12-slim")
        return ["docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "256",
                "--memory", "1g", "-v", f"{workspace}:/workspace", "-w", "/workspace", image,
                "bash", "-c", command]
    raise ValueError(f"Unknown sandbox backend: {backend}")


def _risk(args: dict, ctx) -> RiskTier:
    return classify_command(args["command"])


def _hard_deny(args: dict) -> str | None:
    return "command matches the hard blocklist" if classify_command(args["command"]) is RiskTier.R4 else None


async def run_bash(args: dict, ctx) -> str:
    st = settings()
    timeout = min(float(args.get("timeout", 60)), st.tool_timeout)
    argv = build_argv(args["command"], st.sandbox, str(st.workspace))
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(st.workspace), env=safe_env(), stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, start_new_session=True)

    def kill() -> None:
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    ctx.effects.push(f"bash:{proc.pid}", kill)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        kill()
        raise
    text = out[:MAX_CAPTURE].decode(errors="replace")
    return f"exit code {proc.returncode}\n{text}"


class ShellPlugin(Plugin):
    name = "shell"

    def register(self, ctx: PluginContext) -> None:
        ctx.tool(ToolSpec(
            "bash", "Run a shell command in the workspace. Read-only commands run directly; anything "
            "else needs approval. Destructive commands are blocked.",
            {"type": "object", "properties": {"command": {"type": "string"},
                                              "timeout": {"type": "number", "minimum": 1, "maximum": 600}},
             "required": ["command"], "additionalProperties": False},
            run_bash, capability="Shell", risk=_risk, hard_deny=_hard_deny, policy_tool="shell",
            policy_action="bash", render=lambda a: f"bash: {a['command']}"))
