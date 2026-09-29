"""Control-plane API: fail-closed auth, scopes, detached runs, SSE tail/resume, fork, approvals, cron."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from core.gateway import api
from core.primitives.agent import AgentProfile
from tests.helpers import install_llm, msg

pytestmark = pytest.mark.integration
H = {"Authorization": "Bearer test-token"}

AGENTS = {
    "reader": AgentProfile(id="reader", domain="devops", system_prompt="Test.", allowed_tools=["Read"]),
    "writer": AgentProfile(id="writer", domain="devops", system_prompt="Test.", allowed_tools=["Read", "Write"]),
}


@pytest.fixture(autouse=True)
def agents():
    old = api.registry._agents
    api.registry._agents = dict(AGENTS)
    api._rate.clear()
    yield
    api.registry._agents = old


@pytest.fixture
def client():
    with TestClient(api.app, headers=H) as c:
        yield c


def _wait(client, sid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        s = client.get(f"/sessions/{sid}").json()
        if s["status"] not in ("pending", "running"):
            return s
        time.sleep(0.05)
    raise AssertionError("session did not finish")


class TestAuth:
    def test_health_is_open(self):
        assert TestClient(api.app).get("/health").json() == {"status": "ok"}

    def test_missing_token(self):
        r = TestClient(api.app).get("/agents")
        assert r.status_code == 401 and r.json() == {"detail": "Not authenticated"}

    def test_wrong_token(self):
        r = TestClient(api.app).get("/agents", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401 and r.json() == {"detail": "Invalid API token"}

    def test_valid_env_token(self):
        assert TestClient(api.app).get("/agents", headers=H).status_code == 200

    def test_vault_token_fallback(self, monkeypatch):
        monkeypatch.delenv("HARNESS_API_TOKEN")
        monkeypatch.setattr(api, "get_secret", lambda p, k: "vault-token")
        c = TestClient(api.app)
        assert c.get("/agents", headers={"Authorization": "Bearer vault-token"}).status_code == 200

    def test_no_token_configured_fails_closed_without_default(self, monkeypatch):
        monkeypatch.delenv("HARNESS_API_TOKEN")
        monkeypatch.setattr(api, "get_secret", lambda p, k: (_ for _ in ()).throw(KeyError()))
        r = TestClient(api.app).get("/agents", headers={"Authorization": "Bearer default_unsafe_token_change_me"})
        assert r.status_code == 503
        assert TestClient(api.app).get("/agents", headers={"Authorization": "Bearer "}).status_code == 401

    def test_scoped_tokens(self, monkeypatch):
        monkeypatch.setenv("HARNESS_API_TOKENS", json.dumps({"ro": ["agents:read", "sessions:read"]}))
        c = TestClient(api.app, headers={"Authorization": "Bearer ro"})
        assert c.get("/agents").status_code == 200
        assert c.post("/sessions", json={"agent_id": "reader", "goal": "x"}).status_code == 403
        assert c.post("/cron", json={"cron": "* * * * *", "agent_id": "reader", "goal": "x"}).status_code == 403
        assert c.get("/admin/plugins").status_code == 403

    def test_rate_limit(self, monkeypatch):
        monkeypatch.setenv("HARNESS_API_RATE_LIMIT", "3")
        c = TestClient(api.app, headers=H)
        codes = [c.get("/agents").status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]

    def test_every_route_requires_auth(self):
        c = TestClient(api.app)
        for route in api.app.routes:
            path = getattr(route, "path", "")
            if path in {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"} or not path:
                continue
            if path in {"/", "/ui", "/ui/", "/ui/{name}"}:     # static dashboard code; its data calls need the token
                continue
            for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
                url = path.replace("{session_id}", "x").replace("{agent_id}", "x").replace("{job_id}", "x") \
                    .replace("{approval_id}", "x").replace("{action}", "pause")
                r = c.request(method, url)
                assert r.status_code in (401, 503), (method, path, r.status_code)


class TestAgentsAndSessions:
    def test_agents(self, client):
        assert {a["id"] for a in client.get("/agents").json()} == {"reader", "writer"}
        assert client.get("/agents/reader").json()["domain"] == "devops"
        assert client.get("/agents/none").status_code == 404

    def test_unknown_agent_and_session(self, client):
        assert client.post("/sessions", json={"agent_id": "x", "goal": "g"}).status_code == 404
        assert client.get("/sessions/none").status_code == 404
        assert client.get("/sessions/none/events").status_code == 404

    def test_full_lifecycle_detached_run_with_receipt(self, client, monkeypatch, workspace):
        (workspace / "n.txt").write_text("hello")
        calls = install_llm(monkeypatch, [msg(tool_calls=[("read", {"path": "n.txt"})]), msg("all good")])
        r = client.post("/sessions", json={"agent_id": "reader", "goal": "read n", "environment": {"T": "1"}})
        assert r.status_code == 201 and r.json()["status"] == "pending"
        sid = r.json()["session_id"]
        assert client.post(f"/sessions/{sid}/run").status_code == 202
        assert client.post(f"/sessions/{sid}/run").status_code == 409        # cannot start twice
        s = _wait(client, sid)
        assert s["status"] == "success" and s["outcome"] == "completed" and s["environment"] == {"T": "1"}
        assert "'T': '1'" in calls[0]["messages"][1]["content"]           # environment reaches the agent
        rec = s["run_receipt"]
        assert rec["final_text"] == "all good" and rec["actions"][0]["action"] == "read"
        assert rec["chain_head"] and rec["outcome"] == "completed" and rec["message_history"]
        assert client.get(f"/sessions/{sid}/verify-chain").json()["ok"] is True
        evs = client.get(f"/sessions/{sid}/events").json()
        assert [e["type"] for e in evs][:2] == ["user_msg", "run_start"]

    def test_failed_verification_gives_failure_status(self, client, monkeypatch, workspace):
        install_llm(monkeypatch, [msg("done")])
        sid = client.post("/sessions", json={"agent_id": "reader", "goal": "g", "run": True, "verification": {
            "type": "file_content", "path": str(workspace / "missing"), "expected_content": "x"}}).json()["session_id"]
        s = _wait(client, sid)
        assert s["status"] == "failure" and s["verified"] is False and s["outcome"] == "completed"

    def test_budget_exhaustion_is_reported_as_failure(self, client, monkeypatch):
        install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})], tokens=999_999)])
        sid = client.post("/sessions", json={"agent_id": "reader", "goal": "g", "run": True}).json()["session_id"]
        s = _wait(client, sid)
        assert s["status"] == "failure" and s["outcome"] == "budget_exhausted"

    def test_client_disconnect_does_not_cancel_the_run(self, client, monkeypatch):
        import asyncio

        import litellm

        async def slow(**kw):
            await asyncio.sleep(0.6)
            return msg("finished anyway")

        monkeypatch.setattr(litellm, "acompletion", slow)
        sid = client.post("/sessions", json={"agent_id": "reader", "goal": "g"}).json()["session_id"]
        with client.stream("GET", f"/sessions/{sid}/stream") as resp:          # starts the run...
            assert resp.status_code == 200
        # ...and the stream is closed immediately; the run must still complete
        s = _wait(client, sid)
        assert s["status"] == "success" and s["run_receipt"]["final_text"] == "finished anyway"

    def test_stream_events_and_last_event_id_resume(self, client, monkeypatch, workspace):
        (workspace / "n.txt").write_text("x")
        install_llm(monkeypatch, [msg(tool_calls=[("read", {"path": "n.txt"})]), msg("streamed")])
        sid = client.post("/sessions", json={"agent_id": "reader", "goal": "g"}).json()["session_id"]
        ids, events = [], []
        with client.stream("GET", f"/sessions/{sid}/stream") as resp:
            cur = None
            for line in resp.iter_lines():
                if line.startswith("id: "):
                    cur = int(line[4:])
                elif line.startswith("data: "):
                    ids.append(cur)
                    events.append(json.loads(line[6:]))
        types = [e["type"] for e in events]
        assert types[0] == "usage" and types[1] in {"tool_call", "message"}
        assert "tool_result" in types and types[-1] == "final_receipt"
        assert ids == sorted(ids) and len(set(ids)) == len(ids)
        assert events[-1]["receipt"]["final_text"] == "streamed"
        # resume after the 2nd event: only later events are replayed
        seen = []
        with client.stream("GET", f"/sessions/{sid}/stream", headers={**H, "Last-Event-ID": str(ids[1])}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    seen.append(json.loads(line[6:])["type"])
        assert seen == types[2:]

    def test_finished_session_replays_from_the_durable_log(self, client, monkeypatch):
        install_llm(monkeypatch, [msg("hi")])
        sid = client.post("/sessions", json={"agent_id": "reader", "goal": "g", "run": True}).json()["session_id"]
        _wait(client, sid)
        api.runs.buffers.clear()                                # simulate a process restart
        with client.stream("GET", f"/sessions/{sid}/stream") as resp:
            types = [json.loads(ln[6:])["type"] for ln in resp.iter_lines() if ln.startswith("data: ")]
        assert types[-1] == "final_receipt" and "message" in types

    def test_interrupt_is_delivered_to_the_running_session(self, client, monkeypatch):
        import asyncio

        import litellm

        seen = []
        gate = {"n": 0}

        async def fake(**kw):
            gate["n"] += 1
            seen.append(json.dumps(kw["messages"]))
            if gate["n"] == 1:
                await asyncio.sleep(0.5)
                return msg(tool_calls=[("read_directory", {"path": "."})])
            return msg("saw it")

        monkeypatch.setattr(litellm, "acompletion", fake)
        sid = client.post("/sessions", json={"agent_id": "reader", "goal": "g", "run": True}).json()["session_id"]
        time.sleep(0.15)
        assert client.post(f"/sessions/{sid}/interrupt", json={"message": "STOP AND ABORT"}).status_code == 200
        client.post(f"/sessions/{sid}/interrupt", json={"message": "and also this"})
        _wait(client, sid)
        assert "User Interruption: STOP AND ABORT" in seen[1] and "and also this" in seen[1]
        assert seen[1].index("STOP AND ABORT") < seen[1].index("and also this")

    def test_cancel_stops_the_run_and_finalises_session(self, client, monkeypatch):
        import asyncio

        import litellm

        async def hang(**kw):
            await asyncio.sleep(30)

        monkeypatch.setattr(litellm, "acompletion", hang)
        sid = client.post("/sessions", json={"agent_id": "reader", "goal": "g", "run": True}).json()["session_id"]
        time.sleep(0.2)
        assert client.post(f"/sessions/{sid}/cancel").json()["status"] == "cancelling"
        s = _wait(client, sid)
        assert s["status"] == "failure" and s["outcome"] == "cancelled"
        assert client.post(f"/sessions/{sid}/cancel").json()["status"] == "not_running"

    def test_fork_at_event_replays_history_and_applies_new_goal(self, client, monkeypatch, workspace):
        (workspace / "n.txt").write_text("x")
        install_llm(monkeypatch, [msg(tool_calls=[("read", {"path": "n.txt"})]), msg("first run")])
        sid = client.post("/sessions", json={"agent_id": "reader", "goal": "original", "run": True}).json()["session_id"]
        _wait(client, sid)
        evs = client.get(f"/sessions/{sid}/events").json()
        first_user = next(e for e in evs if e["type"] == "user_msg")
        fork = client.post(f"/sessions/{sid}/fork", json={"goal_override": "different goal", "event_id": first_user["id"]})
        assert fork.status_code == 201
        fid = fork.json()["session_id"]
        f = client.get(f"/sessions/{fid}").json()
        assert f["parent_session_id"] == sid and f["parent_event_id"] == first_user["id"] and f["goal"] == "different goal"
        calls = install_llm(monkeypatch, [msg("second run")])
        client.post(f"/sessions/{fid}/run")
        s = _wait(client, fid)
        users = [m["content"] for m in calls[0]["messages"] if m["role"] == "user"]
        assert any("original" in u for u in users) and users[-1] == "different goal"
        assert not any("first run" in json.dumps(m) for m in calls[0]["messages"])   # cut before the reply
        assert s["run_receipt"]["final_text"] == "second run"
        assert client.post(f"/sessions/{sid}/fork", json={"event_id": "nope"}).status_code == 404

    def test_write_checkpoint_and_rewind(self, client, monkeypatch, workspace):
        (workspace / "cfg.txt").write_text("v1")
        install_llm(monkeypatch, [msg(tool_calls=[("write", {"path": "cfg.txt", "content": "v2"})]), msg("done")])
        sid = client.post("/sessions", json={"agent_id": "writer", "goal": "g", "run": True}).json()["session_id"]
        s = _wait(client, sid)
        assert (workspace / "cfg.txt").read_text() == "v2"
        action = s["run_receipt"]["actions"][0]
        assert action["rollback_available"] is True and action["pre_state_snapshot"]["existed"] is True
        r = client.post(f"/sessions/{sid}/rewind", json={"action_index": 0})
        assert r.status_code == 200 and (workspace / "cfg.txt").read_text() == "v1"
        assert client.post(f"/sessions/{sid}/rewind", json={"action_index": 9}).status_code == 404


class TestApprovalsApi:
    def test_approve_via_api_unblocks_the_run(self, client, monkeypatch, workspace):
        api.engine.broker._timeout = 20
        install_llm(monkeypatch, [msg(tool_calls=[("bash", {"command": "touch made.txt"})]), msg("done")])
        api.registry._agents["shell"] = AgentProfile(id="shell", domain="devops", system_prompt="x",
                                                     allowed_tools=["Shell"])
        sid = client.post("/sessions", json={"agent_id": "shell", "goal": "g", "run": True}).json()["session_id"]
        end = time.time() + 10
        pend = []
        while time.time() < end and not pend:
            pend = client.get("/approvals").json()
            time.sleep(0.05)
        assert pend and pend[0]["tool"] == "bash" and "touch made.txt" in pend[0]["rendered"]
        assert client.post("/approvals/unknown", json={"approved": True}).status_code == 409
        assert client.post(f"/approvals/{pend[0]['id']}", json={"approved": True}).status_code == 200
        s = _wait(client, sid)
        assert s["status"] == "success" and (workspace / "made.txt").exists()
        assert s["run_receipt"]["actions"][0]["approved_by"].startswith("api:")

    def test_denial_via_api_is_returned_to_the_model(self, client, monkeypatch, workspace):
        api.engine.broker._timeout = 20
        calls = install_llm(monkeypatch, [msg(tool_calls=[("bash", {"command": "touch made.txt"})]), msg("ok, skipped")])
        api.registry._agents["shell"] = AgentProfile(id="shell", domain="devops", system_prompt="x",
                                                     allowed_tools=["Shell"])
        sid = client.post("/sessions", json={"agent_id": "shell", "goal": "g", "run": True}).json()["session_id"]
        end = time.time() + 10
        pend = []
        while time.time() < end and not pend:
            pend = client.get("/approvals").json()
            time.sleep(0.05)
        client.post(f"/approvals/{pend[0]['id']}", json={"approved": False, "note": "not now"})
        s = _wait(client, sid)
        assert s["status"] == "success" and not (workspace / "made.txt").exists()
        assert "Human rejected this action: not now" in json.dumps(calls[1]["messages"])


class TestScheduling:
    def test_cron_crud_and_persistence(self, client):
        r = client.post("/cron", json={"cron": "*/5 * * * *", "agent_id": "reader", "goal": "g", "timezone": "Asia/Kolkata"})
        assert r.status_code == 201
        jid = r.json()["job_id"]
        listed = client.get("/cron").json()
        assert listed[0]["id"] == jid and listed[0]["timezone"] == "Asia/Kolkata" and listed[0]["next_run"]
        assert client.post(f"/cron/{jid}/pause").status_code == 200
        assert client.get("/cron").json()[0]["paused"] is True
        assert client.post(f"/cron/{jid}/bogus").status_code == 404
        # "restart": scheduler forgets its in-memory jobs, persisted rows restore them
        api.scheduler.remove_all_jobs()
        from core.background.scheduler import load_persisted_jobs

        assert load_persisted_jobs() == 1 and api.scheduler.get_job(jid) is not None
        assert client.delete(f"/cron/{jid}").status_code == 200
        assert client.get("/cron").json() == [] and client.delete(f"/cron/{jid}").status_code == 404

    def test_bad_input(self, client):
        assert client.post("/cron", json={"cron": "not cron", "agent_id": "reader", "goal": "g"}).status_code == 400
        assert client.post("/cron", json={"cron": "* * * * *", "agent_id": "zz", "goal": "g"}).status_code == 404
        assert client.get("/cron").json() == []                                # nothing half-stored

    async def test_scheduled_job_starts_a_session_via_the_run_manager(self, monkeypatch):
        from core.background import scheduler as sch
        from core.memory.store import get_session, init_db

        started = []

        class FakeRuns:
            async def start(self, sid):
                started.append(sid)
                return True

        sch.set_run_manager(FakeRuns())
        sid = await sch.scheduled_session_job("reader", "nightly audit", {"E": "1"})
        conn = init_db()
        assert started == [sid] and get_session(conn, sid)["goal"] == "nightly audit"

    async def test_heartbeat_skips_when_file_empty_and_runs_with_instructions(self, workspace):
        from core.background import scheduler as sch
        from core.memory.store import get_session, init_db

        launched = []

        class FakeRuns:
            async def start(self, sid):
                launched.append(sid)
                return True

        sch.set_run_manager(FakeRuns())
        assert await sch.heartbeat_job("reader", "Heartbeat", {}) is None
        (workspace / "HEARTBEAT.md").write_text("check for ArgoCD drift")
        sid = await sch.heartbeat_job("reader", "Heartbeat", {})
        assert sid in launched and "ArgoCD drift" in get_session(init_db(), sid)["goal"]


class TestMisc:
    def test_memory_dream_and_skills_and_admin(self, client, monkeypatch):
        install_llm(monkeypatch, [msg("merged")])
        from core.memory.store import add_memory, init_db

        c = init_db()
        add_memory(c, "a", "fact one", "agent-created", "tool-observed", "devops")
        add_memory(c, "b", "fact two", "agent-created", "tool-observed", "devops")
        assert client.post("/memory/dream").json()["consolidated_themes"] == ["merged"]
        assert any(s["name"] == "argocd-status-check" for s in client.get("/skills").json())
        plugins = client.get("/admin/plugins").json()
        assert {"fs", "devops", "shell"} <= {p["name"] for p in plugins}
        r = client.post("/admin/reload").json()
        assert r["agents"] is True
