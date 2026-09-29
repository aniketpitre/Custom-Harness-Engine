"""Subagents/orchestration, webhooks, CLI, secrets/settings, receipts, telemetry, registry."""
import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import pytest

from core.memory.store import get_session, init_db
from core.primitives.agent import AgentProfile
from core.primitives.orchestration import OrchestrationPlan, Phase, SubagentSpec
from tests.helpers import context, install_llm, msg

pytestmark = pytest.mark.integration


class TestOrchestration:
    def _plan(self):
        return OrchestrationPlan(id="wf-1", goal="audit", phases=[
            Phase(name="Audit", subagent_specs=[SubagentSpec(id="auditor-1", goal="find privileged pods", tool_scope=["Read"]),
                                                SubagentSpec(id="auditor-2", goal="find missing limits", tool_scope=["Read"])]),
            Phase(name="Cross-check", subagent_specs=[SubagentSpec(id="verifier", goal="cross check", tool_scope=["Read"])])])

    async def test_phases_run_checkpoint_and_resume_on_a_real_database(self, engine, monkeypatch):
        from core.orchestration.executor import execute_plan

        def answer(kw):
            goal = kw["messages"][1]["content"].splitlines()[0]
            return msg("privileged pod xyz" if "privileged" in goal else "limits ok" if "limits" in goal else "confirmed")

        calls = install_llm(monkeypatch, [answer] * 3)
        ctx = context("audit")
        results = await execute_plan(self._plan(), ctx, engine)
        assert [len(r) for r in results] == [2, 1] and results[1][0]["final_text"] == "confirmed"
        assert {r["subagent_id"] for r in results[0]} == {"auditor-1", "auditor-2"} and all(r["status"] == "success" for r in results[0])
        assert "previous_phase_results" in json.dumps(calls[-1]["messages"]) and "privileged pod xyz" in json.dumps(calls[-1]["messages"])
        assert "previous_phase_results" not in ctx.live_state                       # caller's context is not mutated
        conn = init_db()
        assert conn.execute("SELECT status FROM workflow_checkpoints WHERE workflow_id='wf-1' AND phase_index=1").fetchone()[0] == "completed"
        # every subagent has its own durable child session
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3
        calls.clear()
        again = await execute_plan(self._plan(), ctx, engine)       # resume: nothing is re-run
        assert calls == [] and again[1][0]["final_text"] == "confirmed"

    async def test_resume_after_partial_progress(self, engine, monkeypatch):
        from core.memory.store import save_workflow_checkpoint
        from core.orchestration.executor import execute_plan

        conn = init_db()
        save_workflow_checkpoint(conn, "wf-1", 0, "completed", [{"subagent_id": "a", "final_text": "phase0"}])
        calls = install_llm(monkeypatch, [msg("phase1 done")])
        results = await execute_plan(self._plan(), context("audit"), engine)
        assert len(calls) == 1 and results[0][0]["final_text"] == "phase0" and results[1][0]["final_text"] == "phase1 done"

    async def test_subagent_failure_is_reported_not_raised(self, engine, monkeypatch):
        from core.orchestration.executor import execute_phase

        install_llm(monkeypatch, [RuntimeError("provider down")] * 3)
        import core.llm as llm

        async def nosleep(_):
            return None

        monkeypatch.setattr(llm, "_sleep", nosleep)
        res = await execute_phase(self._plan().phases[0], context())
        assert all(r["status"] == "failure" for r in res)

    async def test_subagents_never_exceed_parent_capabilities_and_share_budget(self, engine, monkeypatch):
        from core.loop import run_agent

        seen = []

        def spy(kw):
            seen.append({t["function"]["name"] for t in kw.get("tools", [])})
            return msg("sub answer", tokens=150_000) if len(seen) == 2 else \
                msg(tool_calls=[("spawn_agent", {"goal": "sub goal", "tools": ["Read", "Shell", "SelfEdit"]})], tokens=100)

        install_llm(monkeypatch, [spy, spy, msg("parent done", tokens=100_000)])
        r = await run_agent(context(), ["Read", "Subagents"], engine=engine)
        sub_tools = seen[1]
        assert "read" in sub_tools and "bash" not in sub_tools and "write_and_register_tool" not in sub_tools
        result = json.loads(r["actions"][0].raw_result)
        assert result["status"] == "success" and result["final_text"] == "sub answer"
        assert r["outcome"] == "completed"            # 150k+100k+100k>200k? budget is shared -> checked below

    async def test_shared_budget_stops_parent_after_subagent_spends_it(self, engine, monkeypatch):
        from core.loop import run_agent

        script = [msg(tool_calls=[("spawn_agent", {"goal": "g"})], tokens=100),
                  msg("sub", tokens=190_000),
                  msg(tool_calls=[("read_directory", {"path": "."})], tokens=20_000)]
        install_llm(monkeypatch, script)
        r = await run_agent(context(), ["Read", "Subagents"], engine=engine)
        assert r["outcome"] == "budget_exhausted"

    async def test_depth_limit(self, engine):
        from core.subagents import MAX_DEPTH, run_subagent
        from core.tools import RunCtx

        parent = RunCtx(session_id=None, agent_id="p", allowed={"Read"}, engine=engine, depth=MAX_DEPTH,
                        extras={"context": context()})
        res = await run_subagent(parent, "x")
        assert res["status"] == "failure" and "depth" in res["error"]

    async def test_concurrency_cap(self, engine, monkeypatch):
        from core.orchestration.executor import execute_phase

        monkeypatch.setenv("HARNESS_MAX_SUBAGENTS", "2")
        running = {"now": 0, "max": 0}

        async def slow(**kw):
            running["now"] += 1
            running["max"] = max(running["max"], running["now"])
            await asyncio.sleep(0.15)
            running["now"] -= 1
            return msg("ok")

        import litellm

        monkeypatch.setattr(litellm, "acompletion", slow)
        phase = Phase(name="p", subagent_specs=[SubagentSpec(id=f"s{i}", goal="g", tool_scope=["Read"]) for i in range(6)])
        engine.extras.pop("subagent_sem", None)
        res = await execute_phase(phase, context(), engine)
        assert running["max"] == 2 and all(r["status"] == "success" for r in res)

    async def test_named_profile_is_used(self, engine, monkeypatch):
        from core.orchestration.executor import execute_phase
        from core.registry import AgentRegistry

        reg = AgentRegistry("/nonexistent.yaml")
        reg._agents["auditor"] = AgentProfile(id="auditor", domain="devops", system_prompt="YOU ARE THE AUDITOR", allowed_tools=["Read"])
        engine.extras["agents"] = reg
        calls = install_llm(monkeypatch, [msg("ok")])
        await execute_phase(Phase(name="p", subagent_specs=[SubagentSpec(id="s", goal="g", tool_scope=["Read"], agent_id="auditor")]),
                            context(), engine)
        assert "YOU ARE THE AUDITOR" in calls[0]["messages"][0]["content"]


class TestWebhooks:
    async def test_signed_retried_and_sent_to_all_endpoints(self, monkeypatch):
        import httpx

        from core.gateway import webhooks

        monkeypatch.setenv("HARNESS_WEBHOOK_ENDPOINTS", "http://a.local/hook,http://b.local/hook")
        monkeypatch.setenv("HARNESS_WEBHOOK_SECRET", "s3cret")
        seen, attempts = [], {"a": 0}

        def handler(req: httpx.Request):
            if req.url.host == "a.local":
                attempts["a"] += 1
                if attempts["a"] < 3:
                    return httpx.Response(503)
            seen.append((req.url.host, req.headers.get("x-harness-signature"), req.content))
            return httpx.Response(200)

        real = httpx.AsyncClient
        monkeypatch.setattr(webhooks.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

        async def nosleep(_):
            return None

        monkeypatch.setattr(webhooks, "_sleep", nosleep)
        results = await webhooks.dispatch_webhook("sess-1", "success", {"some": "data"})
        assert len(results) == 2 and all(r.status_code == 200 for r in results) and attempts["a"] == 3
        for host, sig, body in seen:
            assert sig == "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
            payload = json.loads(body)
            assert payload["event"] == "session_completed" and payload["receipt"] == {"some": "data"}

    async def test_failure_event_and_noop_without_endpoints(self, monkeypatch):
        from core.gateway import webhooks

        assert await webhooks.dispatch_webhook("s", "failure") is None
        monkeypatch.setenv("HARNESS_WEBHOOK_ENDPOINTS", "http://a.local/hook")

        async def nosleep(_):
            return None

        monkeypatch.setattr(webhooks, "_sleep", nosleep)
        import httpx

        real = httpx.AsyncClient
        bodies = []
        monkeypatch.setattr(webhooks.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(
            lambda r: (bodies.append(json.loads(r.content)), httpx.Response(200))[1]), **kw))
        await webhooks.dispatch_webhook("s", "failure")
        assert bodies[0]["event"] == "session_failed" and "X-Harness-Signature" not in bodies[0]

    async def test_run_manager_keeps_references_to_background_tasks(self):
        from core import runs

        done = []

        async def work():
            await asyncio.sleep(0.05)
            done.append(1)

        t = runs.spawn(work())
        assert t in runs._background
        await t
        await asyncio.sleep(0)
        assert t not in runs._background and done == [1]


class TestCli:
    async def test_cli_runs_a_durable_session_and_returns_a_receipt(self, monkeypatch, workspace):
        from core.approvals import get_broker
        from core.engine import Engine, set_engine
        from core.gateway.cli import handle_cli_input
        from core.registry import AgentRegistry

        set_engine(Engine())
        try:
            (workspace / "a.txt").write_text("hi")
            reg = AgentRegistry("/nonexistent")
            reg._agents["devops_agent"] = AgentProfile(id="devops_agent", domain="devops", system_prompt="x", allowed_tools=["Read"])
            install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})]), msg("listed")])
            receipt = await handle_cli_input("List the files", agents=reg,
                                             verification_request={"type": "file_content", "path": str(workspace / "a.txt"), "expected_content": "hi"})
            assert receipt.status == "success" and receipt.final_text == "listed" and receipt.verified is True
            assert receipt.actions[0].action == "read_directory" and receipt.chain_head
            conn = init_db()
            assert get_session(conn, receipt.run_id)["status"] == "success"      # durable, like API sessions
        finally:
            set_engine(None)

    async def test_unknown_agent_exits(self):
        from core.gateway.cli import handle_cli_input
        from core.registry import AgentRegistry

        with pytest.raises(SystemExit):
            await handle_cli_input("x", agents=AgentRegistry("/nonexistent"))


class TestSecretsAndSettings:
    def test_env_override_beats_vault_and_no_vault_needed(self, monkeypatch):
        from core import secrets

        monkeypatch.setenv("HARNESS_SECRET_TELEGRAM_BOT_TOKEN", "from-env")
        assert secrets.get_secret("telegram", "bot_token") == "from-env"

    def test_vault_client_is_shared_and_reads_are_cached(self, monkeypatch):
        import hvac

        from core import secrets

        created, reads = [], []

        class KV:
            def read_secret_version(self, path, mount_point):
                reads.append(path)
                return {"data": {"data": {"api_key": "k-" + path}}}

        class Client:
            def __init__(self, url, token):
                created.append(1)
                self.secrets = SimpleNS(kv=SimpleNS(v2=KV()))

            def is_authenticated(self):
                return True

        from types import SimpleNamespace as SimpleNS

        monkeypatch.setattr(hvac, "Client", Client)
        monkeypatch.setenv("VAULT_ADDR", "http://v")
        monkeypatch.setenv("VAULT_TOKEN", "t")
        secrets.clear_cache()
        for _ in range(5):
            assert secrets.get_secret("llm", "api_key") == "k-llm"
        secrets.get_secret("other", "api_key")
        assert created == [1] and reads == ["llm", "other"]            # one client, one read per secret

    def test_missing_vault_env_is_a_clear_error(self):
        from core import secrets

        with pytest.raises(RuntimeError, match="VAULT_ADDR"):
            secrets.get_secret("x", "y")

    def test_per_model_credentials(self, monkeypatch):
        from core import secrets

        monkeypatch.setenv("GROQ_API_KEY", "groq-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "anth-key")
        assert secrets.get_llm_key("groq/openai/gpt-oss-120b") == "groq-key"
        assert secrets.get_llm_key("anthropic/claude-sonnet-4") == "anth-key"      # not the groq key
        assert secrets.get_llm_key("openai/gpt-4o") is None                        # let LiteLLM decide

    def test_settings_precedence_and_defaults(self, monkeypatch, tmp_path):
        from core.settings import settings

        cfg = tmp_path / "s.yaml"
        cfg.write_text("model:\n  primary: yaml/model\n  fallback: yaml/fallback\notel:\n  endpoint: http://otel:4317\n")
        monkeypatch.setenv("HARNESS_SETTINGS_FILE", str(cfg))
        st = settings()
        assert st.model == "yaml/model" and st.fallback_models == ("yaml/fallback",) and st.otel_endpoint == "http://otel:4317"
        monkeypatch.setenv("HARNESS_MODEL", "env/model")
        monkeypatch.setenv("HARNESS_MAX_TURNS", "7")
        monkeypatch.setenv("HARNESS_MAX_TURNS_BAD", "x")
        assert settings().model == "env/model" and settings().max_turns == 7 and settings().token_budget == 200_000
        monkeypatch.setenv("HARNESS_MAX_TURNS", "seven")
        assert settings().max_turns == 30                                            # bad value falls back

    def test_api_binds_to_loopback_by_default(self):
        from core.settings import settings

        assert settings().api_host == "127.0.0.1"


class TestReceiptsAndRegistry:
    def test_status_semantics(self):
        from core.receipts import derive_status

        assert derive_status("completed", None) == "success" and derive_status("completed", True) == "success"
        assert derive_status("completed", False) == "failure"
        for o in ("budget_exhausted", "turn_limit", "time_limit", "error", "cancelled", "loop_guard", "crashed"):
            assert derive_status(o, None) == "failure"

    def test_registry_reload_is_transactional(self, tmp_path):
        from core.registry import AgentRegistry, LifecycleState

        f = tmp_path / "agents.yaml"
        f.write_text("- id: a\n  domain: d\n  system_prompt: p\n")
        reg = AgentRegistry(f)
        reg.set_lifecycle_state("a", LifecycleState.FAILED)
        f.write_text("- id: a\n  domain: d\n  system_prompt: p\n- id: b\n  domain: d\n  system_prompt: q\n")
        assert reg.reload() is True and set(reg._agents) == {"a", "b"}
        assert reg._lifecycle_states["a"] is LifecycleState.ACTIVE          # reload heals a FAILED agent
        f.write_text("- id: ''\n  domain: d\n  system_prompt: p\n")           # invalid -> rollback
        assert reg.reload() is False and set(reg._agents) == {"a", "b"}

    def test_lifecycle_state_exposed_via_list_agents(self):
        from core.registry import AgentRegistry, LifecycleState

        reg = AgentRegistry("/nonexistent")
        reg._agents["t"] = AgentProfile(id="t", domain="d", system_prompt="p")
        assert reg.list_agents()[0]["lifecycle_state"] == "UNRESOLVED"
        reg.set_lifecycle_state("t", LifecycleState.FAILED)
        assert reg.list_agents()[0]["lifecycle_state"] == "FAILED"

    def test_shipped_agents_yaml_is_valid(self):
        from pathlib import Path

        from core.registry import load_agents

        agents = load_agents(Path(__file__).parent.parent / "config" / "agents.yaml")
        assert "DevOpsWrite" in agents["devops_agent"].allowed_tools and "DevOpsWrite" not in agents["read_only_explorer"].allowed_tools
        from core.policy import parse_rule

        [parse_rule(r) for r in agents["devops_agent"].rules]


class TestTelemetry:
    def test_tracing_initialises_with_endpoint_and_is_idempotent(self, monkeypatch):
        import core.telemetry as t

        monkeypatch.setattr(t, "_initialised", False)
        called = []
        monkeypatch.setattr(t.trace, "set_tracer_provider", lambda p: called.append(p))
        t.init_tracing("http://localhost:4317")
        t.init_tracing("http://localhost:4317")
        assert len(called) == 1      # regression: init used get_secret before import and never ran

    def test_no_endpoint_is_noop(self, monkeypatch):
        import core.telemetry as t

        monkeypatch.setattr(t, "_initialised", False)
        called = []
        monkeypatch.setattr(t.trace, "set_tracer_provider", lambda p: called.append(p))
        t.init_tracing()
        assert called == []

    async def test_metrics_are_emitted_for_runs_and_policy(self, engine, monkeypatch):
        import core.loop as loop
        import core.tools as tools

        runs, policy = [], []
        monkeypatch.setattr(loop.run_counter, "add", lambda n, attrs=None: runs.append(attrs))
        import core.telemetry as t

        monkeypatch.setattr(t.policy_counter, "add", lambda n, attrs=None: policy.append(attrs))
        install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})]), msg("ok")])
        await loop.run_agent(context(), ["Read"], engine=engine)
        assert runs and policy and policy[0]["decision"] == "ALLOW"

    def test_importing_the_engine_does_not_require_optional_instrumentation(self):
        import importlib

        import core.agent_engine

        importlib.reload(core.agent_engine)


class TestVerifierAgentAndSignedChain:
    async def test_independent_verifier_agent_can_fail_a_run(self, engine, monkeypatch):
        from core.loop import run_agent
        from core.registry import AgentRegistry

        reg = AgentRegistry("/nonexistent")
        reg._agents["checked"] = AgentProfile(id="checked", domain="devops", system_prompt="x", allowed_tools=["Read"],
                                              verify_with_agent=True)
        engine.extras["agents"] = reg
        calls = install_llm(monkeypatch, [msg("I fixed it"), msg("FAIL: no evidence of a fix")])
        r = await run_agent(context(), ["Read"], reg._agents["checked"], engine=engine, agent_id="checked")
        assert r["verified"] is False and r["verification"].method == "verifier_agent"
        assert "independent verifier" in calls[1]["messages"][1]["content"] and "I fixed it" in calls[1]["messages"][1]["content"]
        assert "write" not in {t["function"]["name"] for t in calls[1]["tools"]}          # read-only

    async def test_verifier_agent_pass(self, engine, monkeypatch):
        from core.loop import run_agent
        from core.registry import AgentRegistry

        reg = AgentRegistry("/nonexistent")
        reg._agents["checked"] = AgentProfile(id="checked", domain="devops", system_prompt="x", allowed_tools=["Read"],
                                              verify_with_agent=True)
        engine.extras["agents"] = reg
        install_llm(monkeypatch, [msg("done"), msg("PASS: evidence found")])
        r = await run_agent(context(), ["Read"], reg._agents["checked"], engine=engine, agent_id="checked")
        assert r["verified"] is True

    def test_hmac_chain_cannot_be_recomputed_without_the_key(self, monkeypatch):
        from core import eventlog

        monkeypatch.setenv("HARNESS_RECEIPT_KEY", "key-1")
        conn = init_db()
        for i in range(3):
            eventlog.append_event(conn, "s", "user_msg", {"content": f"m{i}"})
        assert eventlog.verify_chain(conn, "s")[0] is True
        # attacker rewrites event 2 and recomputes plain sha256 hashes for the rest of the chain
        conn.execute("UPDATE events SET payload = ? WHERE session_id='s' AND seq=2", ('{"content":"forged"}',))
        prev = conn.execute("SELECT hash FROM events WHERE seq=1").fetchone()[0]
        for seq in (2, 3):
            row = conn.execute("SELECT type, payload FROM events WHERE session_id='s' AND seq=?", (seq,)).fetchone()
            h = hashlib.sha256(f"{prev}|s|{seq}|{row['type']}|{row['payload']}".encode()).hexdigest()
            conn.execute("UPDATE events SET prev_hash=?, hash=? WHERE session_id='s' AND seq=?", (prev, h, seq))
            prev = h
        conn.commit()
        assert eventlog.verify_chain(conn, "s")[0] is False
