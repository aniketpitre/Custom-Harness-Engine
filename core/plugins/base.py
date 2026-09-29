"""Plugins: the unit of registration, reload and disposal (Cordis-lite).

A plugin's `register(ctx)` only *stages* tools, hooks and services. The manager commits
staged effects atomically; every commit returns disposers that are run LIFO on unload.
Reload builds and validates the new plugin first and rolls back to the old one on failure.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Callable

from core.effects import Disposer, EffectStack
from core.tools import ToolSpec

log = logging.getLogger("harness.plugins")


class LifecycleState(Enum):
    UNRESOLVED = "UNRESOLVED"
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"
    DEACTIVATING = "DEACTIVATING"
    INACTIVE = "INACTIVE"
    FAILED = "FAILED"
    DISPOSING = "DISPOSING"


class Plugin:
    name: str = ""
    requires: tuple[str, ...] = ()   # service keys that must be provided by ACTIVE plugins
    provides: tuple[str, ...] = ()   # service keys this plugin provides (for cycle detection)

    def register(self, ctx: "PluginContext") -> Any:  # may be async
        raise NotImplementedError


class PluginContext:
    def __init__(self, engine: Any, plugin: Plugin) -> None:
        self.engine = engine
        self.plugin = plugin
        self.tools: list[ToolSpec] = []
        self.hooks: list[tuple[str, Callable, int]] = []
        self.services: dict[str, Any] = {}
        self.live: EffectStack = EffectStack()  # resources acquired during register()

    def tool(self, spec: ToolSpec) -> None:
        self.tools.append(replace(spec, owner=spec.owner or self.plugin.name))

    def hook(self, event: str, fn: Callable, priority: int = 100) -> None:
        self.hooks.append((event, fn, priority))

    def provide(self, key: str, value: Any) -> None:
        self.services[key] = value

    def service(self, key: str) -> Any:
        return self.engine.plugins.services[key]

    def effect(self, name: str, disposer: Disposer) -> None:
        """Track a resource acquired now (socket, subprocess...). Released on unload/rollback."""
        self.live.push(f"{self.plugin.name}:{name}", disposer)


@dataclass
class PluginRecord:
    plugin: Plugin
    ctx: PluginContext | None = None
    state: LifecycleState = LifecycleState.UNRESOLVED
    error: str | None = None
    disposers: EffectStack = field(default_factory=EffectStack)
    generation: int = 1


class PluginManager:
    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.records: dict[str, PluginRecord] = {}
        self.services: dict[str, Any] = {}

    # -- introspection ---------------------------------------------------
    def status(self) -> list[dict[str, Any]]:
        return [{"name": n, "state": r.state.value, "error": r.error, "generation": r.generation,
                 "tools": [t.name for t in (r.ctx.tools if r.ctx else [])],
                 "requires": list(r.plugin.requires)} for n, r in sorted(self.records.items())]

    def state(self, name: str) -> LifecycleState | None:
        rec = self.records.get(name)
        return rec.state if rec else None

    # -- staging ---------------------------------------------------------
    async def _stage(self, plugin: Plugin) -> PluginContext:
        ctx = PluginContext(self.engine, plugin)
        try:
            out = plugin.register(ctx)
            if inspect.isawaitable(out):
                await out
            names = [t.name for t in ctx.tools]
            if len(names) != len(set(names)):
                raise ValueError("plugin registers duplicate tool names")
            for spec in ctx.tools:
                existing = self.engine.registry._tools.get(spec.name)
                if existing is not None and existing.owner != plugin.name:
                    raise ValueError(f"tool name already registered by {existing.owner}: {spec.name}")
            return ctx
        except BaseException:
            await ctx.live.rollback()
            raise

    def _cycle(self, plugin: Plugin) -> str | None:
        graph = {n: r.plugin for n, r in self.records.items() if n != plugin.name}
        graph[plugin.name] = plugin
        providers = {k: n for n, p in graph.items() for k in p.provides}
        seen: set[str] = set()

        def visit(name: str, stack: tuple[str, ...]) -> str | None:
            if name in stack:
                return " -> ".join(stack + (name,))
            if name in seen:
                return None
            seen.add(name)
            for req in graph[name].requires:
                dep = providers.get(req)
                if dep and (found := visit(dep, stack + (name,))):
                    return found
            return None

        return visit(plugin.name, ())

    # -- commit / dispose ------------------------------------------------
    def _commit(self, rec: PluginRecord) -> None:
        ctx = rec.ctx
        assert ctx is not None
        rec.disposers = EffectStack()
        try:
            for spec in ctx.tools:
                rec.disposers.push(f"tool:{spec.name}", self.engine.registry.register(spec))
            for event, fn, prio in ctx.hooks:
                rec.disposers.push(f"hook:{event}", self.engine.hooks.on(event, fn, prio))
            for key, value in ctx.services.items():
                self.services[key] = value
                rec.disposers.push(f"service:{key}", lambda k=key: self.services.pop(k, None))
        except BaseException:
            _run_sync(rec.disposers)
            raise
        rec.state, rec.error = LifecycleState.ACTIVE, None

    async def _deactivate(self, rec: PluginRecord, to: LifecycleState = LifecycleState.INACTIVE) -> None:
        if rec.state is not LifecycleState.ACTIVE:
            rec.state = to if rec.state is not LifecycleState.FAILED else rec.state
            return
        rec.state = LifecycleState.DEACTIVATING
        # dependents first: anything that requires a key only this plugin provides
        keys = set(rec.ctx.services) if rec.ctx else set()
        for other in list(self.records.values()):
            if other is not rec and other.state is LifecycleState.ACTIVE and keys & set(other.plugin.requires):
                await self._deactivate(other)
        await rec.disposers.rollback()
        if rec.ctx:
            await rec.ctx.live.rollback()  # resources acquired at register() go too; re-acquired on reactivation
        rec.state = to

    def _satisfied(self, rec: PluginRecord) -> bool:
        return all(k in self.services for k in rec.plugin.requires)

    async def _reconcile(self) -> None:
        for _ in range(len(self.records) + 2):
            changed = False
            for rec in list(self.records.values()):
                if rec.state is LifecycleState.ACTIVE and not self._satisfied(rec):
                    await self._deactivate(rec)
                    changed = True
                elif rec.state is LifecycleState.INACTIVE and self._satisfied(rec):
                    try:
                        rec.ctx = await self._stage(rec.plugin)
                        self._commit(rec)
                        changed = True
                    except Exception as error:  # noqa: BLE001
                        rec.state, rec.error = LifecycleState.FAILED, str(error)
            if not changed:
                break

    # -- public API ------------------------------------------------------
    async def load(self, plugin: Plugin) -> PluginRecord:
        """Load or transactionally reload `plugin` (same name replaces the old one)."""
        name = plugin.name
        if not name:
            raise ValueError("plugin must have a name")
        old = self.records.get(name)
        cycle = self._cycle(plugin)
        if cycle:
            if old is None:
                rec = PluginRecord(plugin, state=LifecycleState.FAILED, error=f"dependency cycle: {cycle}")
                self.records[name] = rec
                return rec
            raise ValueError(f"dependency cycle: {cycle}")
        new = PluginRecord(plugin, state=LifecycleState.INITIALIZING, generation=(old.generation + 1) if old else 1)
        if not self._satisfied(new):
            # waits for its dependencies; register() runs only once they are provided
            if old is not None:
                await self._deactivate(old)
            new.state = LifecycleState.INACTIVE
            self.records[name] = new
            await self._reconcile()
            return new
        try:
            new.ctx = await self._stage(plugin)
        except Exception as error:  # noqa: BLE001
            log.warning("plugin %s failed to load: %s", name, error)
            if old is not None:  # transactional: the previous version keeps running
                old.error = f"reload failed: {error}"
                raise
            new.state, new.error = LifecycleState.FAILED, str(error)
            self.records[name] = new
            return new
        if old is not None:
            await self._deactivate(old)
        self.records[name] = new
        try:
            self._commit(new)
        except Exception as error:  # noqa: BLE001 - roll back to the old plugin
            await new.ctx.live.rollback()
            if old is not None:
                self.records[name] = old
                old.error = f"reload failed: {error}"
                old.ctx = await self._stage(old.plugin)
                self._commit(old)
                raise
            new.state, new.error = LifecycleState.FAILED, str(error)
        await self._reconcile()
        return self.records[name]

    async def unload(self, name: str) -> None:
        rec = self.records.get(name)
        if rec is None:
            return
        rec.state = rec.state if rec.state is not LifecycleState.ACTIVE else rec.state
        await self._deactivate(rec)
        if rec.ctx:
            await rec.ctx.live.rollback()
        del self.records[name]
        await self._reconcile()

    async def unload_all(self) -> None:
        for name in reversed(list(self.records)):
            await self.unload(name)


def _run_sync(stack: EffectStack) -> None:
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(stack.rollback())
    except RuntimeError:
        asyncio.run(stack.rollback())
