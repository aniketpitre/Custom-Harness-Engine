"""Engine: registry + hook bus + plugin manager + approval broker, started once per process."""
from __future__ import annotations

import asyncio
from typing import Any

from core.approvals import ApprovalBroker, get_broker
from core.hooks import HookBus
from core.plugins.base import Plugin, PluginManager
from core.tools import Registry, RegistrySnapshot

# Capability groups. "Generic" is the legacy umbrella name.
CAPABILITY_ALIASES = {"Generic": {"Read", "Write", "Web", "Memory"}}


def expand_capabilities(allowed: list[str] | set[str]) -> set[str]:
    out = set(allowed)
    for name in list(out):
        out |= CAPABILITY_ALIASES.get(name, set())
    return out


class Engine:
    def __init__(self, broker: ApprovalBroker | None = None, plugins: list[Plugin] | None = None,
                 builtin: bool = True) -> None:
        self.registry = Registry()
        self.hooks = HookBus()
        self.broker = broker or get_broker()
        self.plugins = PluginManager(self)
        self._initial = plugins or []
        self._builtin = builtin
        self._started = False
        self._lock: asyncio.Lock | None = None
        self.extras: dict[str, Any] = {}

    async def ensure_started(self) -> "Engine":
        if self._started:
            return self
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._started:
                return self
            plugins = list(self._initial)
            if self._builtin:
                from core.builtin import builtin_plugins

                plugins = builtin_plugins() + plugins
            for plugin in plugins:
                await self.plugins.load(plugin)
            if self._builtin:
                from core.hooks import load_hook_config
                from core.plugins.dynamic import load_dynamic_tools
                from core.plugins.mcp_client import mcp_plugins

                load_hook_config(self.hooks)
                await load_dynamic_tools(self)
                for plugin in mcp_plugins():
                    await self.plugins.load(plugin)  # a failing server is marked FAILED, not fatal
            self._started = True
        return self

    def snapshot(self) -> RegistrySnapshot:
        return self.registry.snapshot()

    async def shutdown(self) -> None:
        await self.plugins.unload_all()
        self._started = False


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine


def set_engine(engine: Engine | None) -> None:
    global _engine
    _engine = engine
