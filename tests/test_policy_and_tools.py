"""Policy engine, tool registry/invoke path, approvals broker, hooks."""
import asyncio

import pytest

from core.approvals import ApprovalBroker, ApprovalRequest, args_hash
from core.hooks import HookBus
from core.policy import Rule, decide, parse_rule
from core.primitives.policy import RiskTier
from core.tools import Registry, RunCtx, ToolSpec, invoke, limit_output


def _decide(tier, **kw):
    base = dict(name="t", policy_tool="t", policy_action="a", tier=tier, read_only=False, args={}, rules=[],
                tainted=False)
    base.update(kw)
    return decide(**base)


class TestPolicy:
    def test_tiers(self):
        assert _decide(RiskTier.R0).decision == "ALLOW"
        assert _decide(RiskTier.R1).decision == "ALLOW"
        assert _decide(RiskTier.R2).decision == "REQUIRE_APPROVAL"
        assert _decide(RiskTier.R3).decision == "REQUIRE_APPROVAL"
        assert _decide(RiskTier.R4).decision == "DENY"

    def test_hard_deny_beats_everything(self):
        d = _decide(RiskTier.R0, hard_deny_reason="nope", rules=[Rule("allow", "*")])
        assert d.decision == "DENY"

    def test_rules_deny_before_ask_before_allow(self):
        rules = [parse_rule("allow:t"), parse_rule("ask:t"), parse_rule("deny:t(secret*)")]
        assert _decide(RiskTier.R1, args={"path": "secret.txt"}, rules=rules).decision == "DENY"
        assert _decide(RiskTier.R1, args={"path": "ok"}, rules=rules).decision == "REQUIRE_APPROVAL"
        assert _decide(RiskTier.R2, rules=[Rule("allow", "t")]).decision == "ALLOW"

    def test_taint_raises_mutating_tiers_but_not_reads(self):
        assert _decide(RiskTier.R1, tainted=True).decision == "REQUIRE_APPROVAL"
        assert _decide(RiskTier.R1, tainted=True, read_only=True).decision == "ALLOW"
        d = _decide(RiskTier.R3, tainted=True)
        assert d.decision == "REQUIRE_APPROVAL" and d.risk_tier is RiskTier.R3

    def test_allow_rule_cannot_bypass_taint(self):
        assert _decide(RiskTier.R2, tainted=True, rules=[Rule("allow", "t")]).decision == "REQUIRE_APPROVAL"

    def test_remembered_approval_never_applies_to_r3(self):
        assert _decide(RiskTier.R2, pre_approved=True).decision == "ALLOW"
        assert _decide(RiskTier.R3, pre_approved=True).decision == "REQUIRE_APPROVAL"

    def test_bad_rule_rejected(self):
        with pytest.raises(ValueError):
            parse_rule("maybe:tool")


def _spec(name="t", handler=None, **kw):
    async def default(args, ctx):
        return "ran"

    return ToolSpec(name, "d", {"type": "object", "properties": {"x": {"type": "string"}}, "required": [],
                                "additionalProperties": False}, handler or default, owner="test", **kw)


def _ctx(broker=None, **kw):
    return RunCtx(session_id="s", agent_id="a", allowed={"Generic", "Read"}, broker=broker or ApprovalBroker(timeout=1),
                  hooks=HookBus(), **kw)


async def _run(spec, args, ctx):
    reg = Registry()
    reg.register(spec)
    return await invoke(reg.snapshot(), "c1", spec.name, args, ctx)


class TestInvoke:
    async def test_allowed_r1_runs_and_records(self):
        res = await _run(_spec(risk=RiskTier.R1), {}, _ctx())
        assert res.content == "ran" and not res.is_error
        assert res.record.policy_decision.decision == "ALLOW" and res.record.args_hash

    async def test_capability_denied(self):
        ctx = _ctx()
        ctx.allowed = {"Read"}
        res = await _run(_spec(capability="Write"), {}, ctx)
        assert res.is_error and res.record.policy_decision.decision == "DENY"

    async def test_arg_validation_error_returns_message(self):
        res = await _run(_spec(), {"bogus": 1}, _ctx())
        assert res.is_error and "Invalid arguments" in res.content

    async def test_exception_becomes_error_result(self):
        async def boom(a, c):
            raise KeyError("k")

        res = await _run(_spec(handler=boom), {}, _ctx())
        assert res.is_error and "KeyError" in res.content

    async def test_sync_handler_runs_in_thread(self):
        import threading

        main = threading.get_ident()
        seen = {}

        def sync(a, c):
            seen["t"] = threading.get_ident()
            return "s"

        res = await _run(_spec(handler=sync), {}, _ctx())
        assert res.content == "s" and seen["t"] != main

    async def test_timeout(self):
        async def slow(a, c):
            await asyncio.sleep(5)

        res = await _run(_spec(handler=slow, timeout=0.1), {}, _ctx())
        assert res.is_error and "Timeout" in res.content

    async def test_r2_needs_approval_and_denial_returns_message(self):
        broker = ApprovalBroker(timeout=2)

        async def deny(req: ApprovalRequest):
            broker.resolve(req.id, False, "tester", note="too risky")

        broker.add_channel(deny)
        res = await _run(_spec(risk=RiskTier.R2), {}, _ctx(broker))
        assert res.is_error and "too risky" in res.content
        assert res.record.policy_decision.decision == "DENY"

    async def test_approval_grants_and_records_approver(self):
        broker = ApprovalBroker(timeout=2)

        async def approve(req):
            assert req.args_hash == args_hash("t", {"x": "1"})
            broker.resolve(req.id, True, "tele:42")

        broker.add_channel(approve)
        res = await _run(_spec(risk=RiskTier.R2), {"x": "1"}, _ctx(broker))
        assert res.content == "ran" and res.record.approved_by == "tele:42"
        assert res.record.policy_decision.decision == "ALLOW"

    async def test_approval_timeout_denies(self):
        res = await _run(_spec(risk=RiskTier.R2), {}, _ctx(ApprovalBroker(timeout=0.1)))
        assert res.is_error and "timed out" in res.content

    async def test_session_scope_remembers_r2_only(self):
        broker = ApprovalBroker(timeout=2)
        asked = []

        async def approve(req):
            asked.append(req.id)
            broker.resolve(req.id, True, "u", scope="session")

        broker.add_channel(approve)
        ctx = _ctx(broker)
        spec = _spec(risk=RiskTier.R2)
        await _run(spec, {}, ctx)
        await _run(spec, {}, ctx)
        assert len(asked) == 1   # second identical call was remembered
        r3 = _spec(name="r3", risk=RiskTier.R3)
        await _run(r3, {}, ctx)
        await _run(r3, {}, ctx)
        assert len(asked) == 3   # R3 is always asked

    async def test_always_scope_persists_in_db(self):
        broker = ApprovalBroker(timeout=2)

        async def approve(req):
            broker.resolve(req.id, True, "u", scope="always")

        broker.add_channel(approve)
        await _run(_spec(risk=RiskTier.R2), {"x": "1"}, _ctx(broker))
        assert broker.is_remembered("t", args_hash("t", {"x": "1"}))
        assert not broker.is_remembered("t", args_hash("t", {"x": "2"}))

    async def test_hook_can_tighten_but_not_loosen(self):
        ctx = _ctx()
        ctx.hooks.on("pre_tool", lambda p: {"decision": "deny", "reason": "no"})
        res = await _run(_spec(), {}, ctx)
        assert res.is_error and "no" in res.content
        ctx2 = _ctx(ApprovalBroker(timeout=0.1))
        ctx2.hooks.on("pre_tool", lambda p: {"decision": "allow"})   # ignored: cannot loosen
        res2 = await _run(_spec(risk=RiskTier.R2), {}, ctx2)
        assert res2.is_error

    async def test_hook_can_rewrite_arguments(self):
        seen = {}

        async def h(args, ctx):
            seen.update(args)
            return "ok"

        ctx = _ctx()
        ctx.hooks.on("pre_tool", lambda p: {"updatedInput": {"x": "rewritten"}})
        await _run(_spec(handler=h), {"x": "orig"}, ctx)
        assert seen == {"x": "rewritten"}

    async def test_untrusted_output_is_wrapped_and_taints(self):
        ctx = _ctx()

        async def h(a, c):
            return "hello​ world"

        res = await _run(_spec(handler=h, untrusted=True, read_only=True), {}, ctx)
        assert res.content.startswith('<external source="t" trust="untrusted">')
        assert "​" not in res.content and ctx.tainted

    async def test_after_taint_mutating_r1_needs_approval(self):
        ctx = _ctx(ApprovalBroker(timeout=0.1))
        ctx.tainted = True
        res = await _run(_spec(risk=RiskTier.R1), {}, ctx)
        assert res.is_error   # approval requested, nobody answered -> denied

    async def test_output_limit_spills_and_previews(self, tmp_path):
        async def big(a, c):
            return "A" * 50_000

        res = await _run(_spec(handler=big, output_limit=1000), {}, _ctx())
        assert len(res.content) < 1600 and "TRUNCATED" in res.content and "read_spill" in res.content

    async def test_verify_postcondition_failure_flags_error(self):
        res = await _run(_spec(verify=lambda a, out: False), {}, _ctx())
        assert res.is_error and "verification failed" in res.content


def test_limit_output_small_passthrough(tmp_path):
    assert limit_output("hi", 10, "s", "t", tmp_path) == "hi"


def test_registry_disposer_and_snapshot_isolation():
    reg = Registry()
    dispose = reg.register(_spec("a"))
    snap = reg.snapshot()
    dispose()
    assert reg.names() == [] and snap.get("a") is not None      # old snapshot unaffected
    with pytest.raises(ValueError):
        reg.register(_spec("b"))
        reg.register(ToolSpec("b", "d", {}, lambda a, c: "", owner="other"))


class TestBroker:
    async def test_unauthorised_approver_rejected(self):
        broker = ApprovalBroker(timeout=1, approvers=("telegram:1",))
        got = []

        async def chan(req):
            got.append(broker.resolve(req.id, True, "telegram:999"))   # wrong user
            got.append(broker.resolve(req.id, True, "telegram:1"))

        broker.add_channel(chan)
        res = await broker.request(ApprovalRequest("t", "h", "r", "R2"))
        assert got == [False, True] and res.approved and res.approver == "telegram:1"

    async def test_concurrent_requests_do_not_interfere(self):
        broker = ApprovalBroker(timeout=2)
        reqs = []

        async def chan(req):
            reqs.append(req)

        broker.add_channel(chan)
        t1 = asyncio.create_task(broker.request(ApprovalRequest("a", "h1", "r", "R2")))
        t2 = asyncio.create_task(broker.request(ApprovalRequest("b", "h2", "r", "R2")))
        await asyncio.sleep(0.1)
        assert len(broker.pending()) == 2
        broker.resolve(reqs[1].id, True, "u")
        broker.resolve(reqs[0].id, False, "u")
        r1, r2 = await t1, await t2
        by_tool = {reqs[0].tool: r1, reqs[1].tool: r2}
        assert by_tool["a"].approved is False and by_tool["b"].approved is True

    async def test_double_resolve_ignored(self):
        broker = ApprovalBroker(timeout=1)

        async def chan(req):
            assert broker.resolve(req.id, True, "u")
            assert not broker.resolve(req.id, False, "u")

        broker.add_channel(chan)
        assert (await broker.request(ApprovalRequest("t", "h", "r", "R2"))).approved

    async def test_state_persisted(self):
        broker = ApprovalBroker(timeout=0.1)
        req = ApprovalRequest("t", "h", "rendered", "R2", session_id="s1")
        await broker.request(req)
        from core.memory.store import init_db

        row = init_db().execute("SELECT status, session_id FROM approvals WHERE id = ?", (req.id,)).fetchone()
        assert row["status"] == "timed_out" and row["session_id"] == "s1"


class TestHooks:
    async def test_failing_hook_skipped_and_order_by_priority(self):
        bus = HookBus()
        order = []
        bus.on("pre_tool", lambda p: order.append("late") or None, priority=200)
        bus.on("pre_tool", lambda p: (_ for _ in ()).throw(RuntimeError("bad")), priority=50)
        bus.on("pre_tool", lambda p: order.append("early") or None, priority=10)
        await bus.emit("pre_tool", {})
        assert order == ["early", "late"]

    async def test_disposer_removes_hook(self):
        bus = HookBus()
        d = bus.on("stop", lambda p: {"continue": "x"})
        d()
        assert (await bus.emit("stop", {})).force_continue is None

    async def test_command_hook_exit_2_blocks(self):
        from core.hooks import command_hook

        bus = HookBus()
        bus.on("pre_tool", command_hook("echo blocked >&2; exit 2"))
        r = await bus.emit("pre_tool", {"tool": "x"})
        assert r.decision == "deny" and "blocked" in r.reason
