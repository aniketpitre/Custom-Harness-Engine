"""MCP client: tools of external MCP servers appear as mcp__<server>__<tool> and go through the
same policy/approval path as every other tool. Config: config/mcp.yaml

servers:
  - name: github
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env: {GITHUB_TOKEN_ENV: "GITHUB_TOKEN"}     # map: child env name -> harness env var to copy
    read_only_tools: ["get_*", "list_*", "search_*"]   # R0; everything else needs approval (R2)
"""
from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
from typing import Any

from core.confine import safe_env
from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.tools import ToolSpec

log = logging.getLogger("harness.mcp")
CONNECT_TIMEOUT = 30.0


class McpConnection:
    """Holds the stdio client open in a dedicated task (anyio scopes must exit in their own task)."""

    def __init__(self, command: str, args: list[str], env: dict[str, str]) -> None:
        self.command, self.args, self.env = command, args, env
        self.session: Any = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.error: BaseException | None = None

    async def _run(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        try:
            params = StdioServerParameters(command=self.command, args=self.args, env=self.env)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.session = session
                    self._ready.set()
                    await self._stop.wait()
        except BaseException as error:  # noqa: BLE001
            self.error = error
        finally:
            self.session = None
            self._ready.set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self._ready.wait(), CONNECT_TIMEOUT)
        if self.session is None:
            raise RuntimeError(f"MCP server failed to start: {self.error}")

    async def close(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, 10)
            except Exception:  # noqa: BLE001
                self._task.cancel()


def _text(result: Any) -> str:
    parts = []
    for item in getattr(result, "content", []) or []:
        parts.append(getattr(item, "text", None) or str(item))
    text = "\n".join(parts)
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        raise RuntimeError(text or "MCP tool error")
    return text


class McpServerPlugin(Plugin):
    def __init__(self, name: str, command: str, args: list[str] | None = None, env: dict[str, str] | None = None,
                 read_only_tools: list[str] | None = None) -> None:
        self.server = name
        self.name = f"mcp:{name}"
        self.command, self.args = command, list(args or [])
        self.env_map, self.read_only = dict(env or {}), list(read_only_tools or [])

    async def register(self, ctx: PluginContext) -> None:
        env = safe_env(extra={child: os.environ[src] for child, src in self.env_map.items() if src in os.environ})
        conn = McpConnection(self.command, self.args, env)
        await conn.start()
        ctx.effect("connection", conn.close)
        listing = await conn.session.list_tools()
        for tool in listing.tools:
            ro = any(fnmatch.fnmatch(tool.name, p) for p in self.read_only)
            name = f"mcp__{self.server}__{tool.name}"

            async def handler(args: dict, run_ctx, _t=tool.name) -> str:
                return _text(await conn.session.call_tool(_t, args))

            ctx.tool(ToolSpec(
                name, (tool.description or tool.name)[:500],
                (getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None)
                 or {"type": "object", "properties": {}}), handler, capability="MCP",
                risk=RiskTier.R0 if ro else RiskTier.R2, read_only=ro, parallel_safe=ro, untrusted=True,
                policy_tool=f"mcp:{self.server}", policy_action=tool.name, timeout=120,
                render=lambda a, n=name: f"{n}\n{str(a)[:1500]}"))


def mcp_plugins(path: str | None = None) -> list[Plugin]:
    from core.home import find_config

    path = path or str(find_config("mcp.yaml"))
    if not os.path.isfile(path):
        return []
    import yaml

    cfg = yaml.safe_load(open(path)) or {}
    return [McpServerPlugin(s["name"], s["command"], s.get("args"), s.get("env"), s.get("read_only_tools"))
            for s in cfg.get("servers", [])]
