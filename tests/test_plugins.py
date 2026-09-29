"""Plugin lifecycle: disposers, reactive dependencies, transactional reload, failure isolation, effects."""
import pytest

from core.effects import EffectScope, EffectStack
from core.engine import Engine
from core.plugins.base import LifecycleState, Plugin
from core.primitives.policy import RiskTier
from core.tools import ToolSpec

pytestmark = pytest.mark.integration


def _tool(name):
    return ToolSpec(name, "d", {"type": "object", "properties": {}}, lambda a, c: name, capability="Read",
                    risk=RiskTier.R0)


def make(name, tools=(), requires=(), provides=(), hooks=(), fail=False, services=None, log=None):
    class P(Plugin):
        def register(self, ctx):
            if fail:
                raise RuntimeError(f"{name} exploded")
            for t in tools:
                ctx.tool(_tool(t))
            for ev, fn in hooks:
                ctx.hook(ev, fn)
            for k, v in (services or {}).items():
                ctx.provide(k, v)
            if log is not None:
                ctx.effect("resource", lambda: log.append(f"released {name}"))

    P.name, P.requires, P.provides = name, tuple(requires), tuple(provides)
    return P()


@pytest.fixture
def eng():
    return Engine(builtin=False)


async def test_load_registers_and_unload_disposes_everything(eng):
    log = []
    p = make("a", tools=["t1", "t2"], hooks=[("stop", lambda x: None)], services={"svc": 1}, log=log)
    await eng.plugins.load(p)
    assert eng.registry.names() == ["t1", "t2"] and eng.hooks.count("stop") == 1 and eng.plugins.services == {"svc": 1}
    await eng.plugins.unload("a")
    assert eng.registry.names() == [] and eng.hooks.count() == 0 and eng.plugins.services == {}
    assert log == ["released a"]                       # resources acquired at load are released too


async def test_failed_plugin_is_isolated(eng):
    await eng.plugins.load(make("good", tools=["g"]))
    rec = await eng.plugins.load(make("bad", tools=["b"], fail=True))
    assert rec.state is LifecycleState.FAILED and "exploded" in rec.error
    assert eng.registry.names() == ["g"] and eng.plugins.state("good") is LifecycleState.ACTIVE


async def test_reactive_activation_and_deactivation_by_dependency(eng):
    await eng.plugins.load(make("consumer", tools=["c"], requires=["db"]))
    assert eng.plugins.state("consumer") is LifecycleState.INACTIVE and eng.registry.names() == []
    await eng.plugins.load(make("provider", services={"db": object()}, provides=["db"]))
    assert eng.plugins.state("consumer") is LifecycleState.ACTIVE and eng.registry.names() == ["c"]
    await eng.plugins.unload("provider")               # provider disappears -> dependent deactivates
    assert eng.plugins.state("consumer") is LifecycleState.INACTIVE and eng.registry.names() == []
    await eng.plugins.load(make("provider", services={"db": 2}, provides=["db"]))   # and comes back
    assert eng.plugins.state("consumer") is LifecycleState.ACTIVE


async def test_dependents_are_disposed_before_their_provider(eng):
    order = []
    await eng.plugins.load(make("provider", services={"db": 1}, provides=["db"], log=order))
    await eng.plugins.load(make("consumer", tools=["c"], requires=["db"], log=order))
    await eng.plugins.unload("provider")
    assert order == ["released consumer", "released provider"]


async def test_reload_replaces_atomically(eng):
    await eng.plugins.load(make("p", tools=["old"]))
    snapshot = eng.snapshot()
    rec = await eng.plugins.load(make("p", tools=["new"]))
    assert rec.generation == 2 and eng.registry.names() == ["new"]
    assert snapshot.get("old") is not None            # in-flight runs keep their snapshot


async def test_failed_reload_keeps_the_previous_version_running(eng):
    await eng.plugins.load(make("p", tools=["v1"]))
    with pytest.raises(RuntimeError):
        await eng.plugins.load(make("p", tools=["v2"], fail=True))
    assert eng.registry.names() == ["v1"] and eng.plugins.state("p") is LifecycleState.ACTIVE
    assert "reload failed" in eng.plugins.records["p"].error


async def test_tool_name_collision_between_plugins_is_rejected(eng):
    await eng.plugins.load(make("a", tools=["same"]))
    rec = await eng.plugins.load(make("b", tools=["same"]))
    assert rec.state is LifecycleState.FAILED and "already registered" in rec.error
    assert eng.registry.names() == ["same"]


async def test_dependency_cycle_is_detected(eng):
    await eng.plugins.load(make("a", requires=["kb"], provides=["ka"]))
    rec = await eng.plugins.load(make("b", requires=["ka"], provides=["kb"]))
    assert rec.state is LifecycleState.FAILED and "cycle" in rec.error


async def test_status_report(eng):
    await eng.plugins.load(make("a", tools=["t"]))
    s = eng.plugins.status()
    assert s == [{"name": "a", "state": "ACTIVE", "error": None, "generation": 1, "tools": ["t"], "requires": []}]


async def test_engine_shutdown_unloads_all(eng):
    await eng.plugins.load(make("a", tools=["t"]))
    await eng.shutdown()
    assert eng.registry.names() == []


async def test_effect_stack_is_lifo_and_survives_disposer_errors():
    stack, log = EffectStack(), []
    stack.push("a", lambda: log.append(1))
    stack.push("b", lambda: (_ for _ in ()).throw(RuntimeError("bad")))

    async def async_disposer():
        log.append(3)

    stack.push("c", async_disposer)
    ran = await stack.rollback()
    assert log == [3, 1] and ran == ["c", "a"] and len(stack) == 0


async def test_effect_scope_disposes_on_error_and_early_dispose_runs_once():
    log = []
    with pytest.raises(ValueError):
        async with EffectScope() as stack:
            early = stack.push("x", lambda: log.append("x"))
            stack.push("y", lambda: log.append("y"))
            await early()
            await early()
            raise ValueError
    assert log == ["x", "y"]


async def test_run_disposes_effects_and_reports_teardown(engine, monkeypatch):
    """Effects pushed by a tool (e.g. a subprocess) are torn down when the run ends."""
    from core.loop import run_agent
    from tests.helpers import context, install_llm, msg

    log = []

    async def handler(args, ctx):
        ctx.effects.push("proc", lambda: log.append("killed"))
        return "ok"

    class P(Plugin):
        name = "eff"

        def register(self, c):
            c.tool(ToolSpec("eff", "d", {"type": "object", "properties": {}}, handler, capability="Read",
                            risk=RiskTier.R0))

    await engine.plugins.load(P())
    install_llm(monkeypatch, [msg(tool_calls=[("eff", {})]), msg("done")])
    r = await run_agent(context(), ["Read"], engine=engine)
    assert log == ["killed"] and r["teardown_tasks"] == ["proc"]


async def test_builtin_plugins_all_active(engine):
    states = {p["name"]: p["state"] for p in engine.plugins.status()}
    assert states and set(states.values()) == {"ACTIVE"}
    assert {"fs", "web", "shell", "memory", "skills", "advisor", "subagents", "selfedit", "devops"} <= set(states)
