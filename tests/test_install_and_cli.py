"""Single-command install: HARNESS_HOME, `harness init/doctor/serve/run/...`, and the built wheel."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli import doctor
from cli.main import build_parser, main
from core import home
from tests.helpers import install_llm, msg

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("HARNESS_MODEL", "HARNESS_API_TOKEN", "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
              "HARNESS_SANDBOX", "HARNESS_APPROVERS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HARNESS_SETTINGS_FILE", "")


class TestHome:
    def test_parse_env_handles_comments_quotes_and_export(self):
        text = "# c\nA=1\nexport B='two words'\nC=\"3\"\n\nbad line\nD=x=y\n"
        assert home.parse_env(text) == {"A": "1", "B": "two words", "C": "3", "D": "x=y"}

    def test_write_env_is_private_atomic_and_merges(self, tmp_path):
        p = home.write_env({"A": "1", "B": "2"})
        assert p.stat().st_mode & 0o777 == 0o600 and home.harness_home().stat().st_mode & 0o777 == 0o700
        home.write_env({"B": "3", "C": "4"})
        assert home.parse_env(p.read_text()) == {"A": "1", "B": "3", "C": "4"}
        assert not list(p.parent.glob("*.tmp"))

    def test_load_env_does_not_override_real_environment(self, monkeypatch):
        home.write_env({"HARNESS_MODEL": "from-file", "HARNESS_MAX_TURNS": "9"})
        monkeypatch.setenv("HARNESS_MODEL", "from-env")
        monkeypatch.delenv("HARNESS_MAX_TURNS", raising=False)
        assert home.load_env() == ["HARNESS_MAX_TURNS"]
        assert os.environ["HARNESS_MODEL"] == "from-env" and os.environ["HARNESS_MAX_TURNS"] == "9"
        monkeypatch.delenv("HARNESS_MAX_TURNS")

    def test_config_lookup_order_home_then_cwd_then_packaged(self, workspace):
        assert home.find_config("agents.yaml") == home.DEFAULTS_DIR / "agents.yaml"        # packaged default
        (workspace / "config").mkdir()
        (workspace / "config" / "agents.yaml").write_text("- id: cwd\n  domain: d\n  system_prompt: p\n")
        assert home.find_config("agents.yaml") == Path("config/agents.yaml")               # checkout convenience
        (home.ensure_home() / "config" / "agents.yaml").write_text("- id: home\n  domain: d\n  system_prompt: p\n")
        assert home.find_config("agents.yaml") == home.harness_home() / "config" / "agents.yaml"

    def test_packaged_defaults_exist_and_are_valid(self):
        from core.registry import load_agents

        for name in ("agents.yaml", "settings.yaml", "mcp.yaml.example", "hooks.yaml.example"):
            assert (home.DEFAULTS_DIR / name).is_file(), name
        assert {"devops_agent", "read_only_explorer"} <= set(load_agents(home.DEFAULTS_DIR / "agents.yaml"))

    def test_database_defaults_to_the_harness_home_not_the_cwd(self, monkeypatch):
        from core.settings import settings

        monkeypatch.delenv("HARNESS_DB_PATH")
        monkeypatch.delenv("HARNESS_DATA_DIR")
        assert settings().db_path == home.harness_home() / "data" / "memory.db"
        assert settings().data_dir == home.harness_home() / "data"

    def test_agents_load_from_home_override(self):
        from core.registry import AgentRegistry

        (home.ensure_home() / "config" / "agents.yaml").write_text("- id: mine\n  domain: d\n  system_prompt: p\n")
        assert set(AgentRegistry()._agents) == {"mine"}


class TestInit:
    def test_non_interactive_init_writes_everything_privately(self, capsys, monkeypatch):
        monkeypatch.setenv("MY_KEY", "sk-secret-value")
        code = main(["init", "-y", "--provider", "groq", "--api-key-env", "MY_KEY", "--model", "groq/test-model"])
        out = capsys.readouterr().out
        assert code == 0
        env = home.parse_env(home.env_file().read_text())
        assert env["GROQ_API_KEY"] == "sk-secret-value" and env["HARNESS_MODEL"] == "groq/test-model"
        assert len(env["HARNESS_API_TOKEN"]) == 64
        assert home.env_file().stat().st_mode & 0o777 == 0o600
        assert (home.harness_home() / "config" / "agents.yaml").is_file()
        assert "sk-secret-value" not in out and env["HARNESS_API_TOKEN"] not in out       # never printed
        assert "Ready to go" in out or "problem" in out

    def test_init_is_idempotent_and_keeps_token_and_custom_agents(self, monkeypatch):
        main(["init", "-y", "--provider", "groq", "--api-key", "k1"])
        first = home.parse_env(home.env_file().read_text())["HARNESS_API_TOKEN"]
        agents = home.harness_home() / "config" / "agents.yaml"
        agents.write_text("- id: custom\n  domain: d\n  system_prompt: p\n")
        monkeypatch.delenv("HARNESS_API_TOKEN", raising=False)
        main(["init", "-y", "--provider", "openai", "--api-key", "k2", "--model", "openai/gpt-x"])
        env = home.parse_env(home.env_file().read_text())
        assert env["HARNESS_API_TOKEN"] == first and env["GROQ_API_KEY"] == "k1" and env["OPENAI_API_KEY"] == "k2"
        assert env["HARNESS_MODEL"] == "openai/gpt-x" and "custom" in agents.read_text()

    def test_unknown_provider_and_local_provider(self, capsys):
        with pytest.raises(SystemExit):
            main(["init", "-y", "--provider", "bogus"])
        assert main(["init", "-y", "--provider", "local", "--base-url", "http://localhost:11434/v1"]) == 0
        env = home.parse_env(home.env_file().read_text())
        assert env["OPENAI_API_BASE"] == "http://localhost:11434/v1" and env["HARNESS_MODEL"].startswith("ollama_chat/")

    def test_telegram_settings_are_stored_for_the_secret_chain(self):
        main(["init", "-y", "--provider", "groq", "--api-key", "k", "--telegram-bot-token", "123:abc",
              "--telegram-chat-id", "42", "--approver", "telegram:7", "--no-agents"])
        env = home.parse_env(home.env_file().read_text())
        assert env["HARNESS_APPROVERS"] == "telegram:7"
        from core.secrets import get_secret

        os.environ.update({k: v for k, v in env.items() if k.startswith("HARNESS_SECRET")})
        try:
            assert get_secret("telegram", "bot_token") == "123:abc" and get_secret("telegram", "approval_chat_id") == "42"
        finally:
            for k in list(os.environ):
                if k.startswith("HARNESS_SECRET"):
                    del os.environ[k]
        assert not (home.harness_home() / "config" / "agents.yaml").exists()

    def test_interactive_flow(self, monkeypatch, capsys):
        answers = iter(["anthropic", "anthropic/my-model", "n"])
        monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
        monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-typed")
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        assert main(["init"]) == 0
        env = home.parse_env(home.env_file().read_text())
        assert env["ANTHROPIC_API_KEY"] == "sk-typed" and env["HARNESS_MODEL"] == "anthropic/my-model"

    def test_token_command(self, capsys):
        assert main(["token"]) == 1
        main(["init", "-y", "--provider", "groq", "--api-key", "k"])
        capsys.readouterr()
        os.environ.pop("HARNESS_API_TOKEN", None)
        assert main(["token"]) == 0
        assert len(capsys.readouterr().out.strip()) == 64
        os.environ.pop("HARNESS_API_TOKEN", None)


class TestDoctor:
    def _by_name(self, checks):
        return {c.name: c for c in checks}

    def test_fresh_install_reports_missing_token_with_the_fix(self, capsys):
        checks = self._by_name(doctor.collect())
        assert checks["api token"].status == "fail" and "harness init" in checks["api token"].fix
        assert main(["doctor"]) == 1
        assert "harness init" in capsys.readouterr().out

    def test_ready_after_init(self, capsys, monkeypatch):
        main(["init", "-y", "--provider", "groq", "--api-key", "k"])
        capsys.readouterr()
        monkeypatch.setenv("HARNESS_API_TOKEN", home.parse_env(home.env_file().read_text())["HARNESS_API_TOKEN"])
        checks = self._by_name(doctor.collect())
        assert checks["api token"].status == checks["provider key"].status == checks["agents"].status == "ok"
        assert checks["database"].status == "ok" and "wal" in checks["database"].detail
        assert main(["doctor"]) == 0 and "Ready to go" in capsys.readouterr().out

    def test_json_output_is_machine_readable(self, capsys):
        main(["doctor", "--json"])
        data = json.loads(capsys.readouterr().out)
        assert {"name", "status", "detail", "fix"} <= set(data[0]) and any(c["name"] == "python" for c in data)

    def test_env_file_permissions_are_checked(self):
        p = home.write_env({"A": "1"})
        p.chmod(0o644)
        c = self._by_name(doctor.collect())["env file"]
        assert c.status == "fail" and f"chmod 600 {p}" in c.fix

    def test_requested_sandbox_backend_missing_is_a_failure(self, monkeypatch):
        monkeypatch.setenv("HARNESS_SANDBOX", "bwrap")
        monkeypatch.setattr(doctor.shutil, "which", lambda n: None if n == "bwrap" else "/usr/bin/" + n)
        assert self._by_name(doctor.collect())["bwrap"].status == "fail"

    def test_optional_things_are_warnings_not_failures(self, monkeypatch):
        monkeypatch.setattr(doctor.shutil, "which", lambda n: None)
        monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda m: None)
        checks = self._by_name(doctor.collect())
        assert checks["kubectl"].status == checks["python:telegram"].status == "warn"
        assert 'pip install "harness-engine[telegram]"' == checks["python:telegram"].fix

    def test_online_check(self, monkeypatch):
        install_llm(monkeypatch, [msg("OK")])
        assert self._by_name(doctor.collect(online=True))["model reachable"].status == "ok"
        install_llm(monkeypatch, [RuntimeError("bad key")] * 5)
        import core.llm as llm

        async def nosleep(_):
            return None

        monkeypatch.setattr(llm, "_sleep", nosleep)
        c = self._by_name(doctor.collect(online=True))["model reachable"]
        assert c.status == "fail" and "bad key" in c.detail

    def test_busy_port_detected(self):
        import socket

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        try:
            assert self._by_name(doctor.collect(port=port))["port"].status == "warn"
        finally:
            s.close()


class TestServeRunAndFriends:
    def test_serve_refuses_without_token_and_passes_settings_to_uvicorn(self, monkeypatch, capsys):
        import uvicorn

        calls = []
        monkeypatch.setattr(uvicorn, "run", lambda *a, **k: calls.append((a, k)))
        assert main(["serve"]) == 1 and calls == []
        monkeypatch.setenv("HARNESS_API_TOKEN", "t")
        assert main(["serve", "--port", "9123"]) == 0
        assert calls[0][0] == ("core.gateway.api:app",) and calls[0][1]["host"] == "127.0.0.1" and calls[0][1]["port"] == 9123
        assert main(["serve", "--host", "0.0.0.0"]) == 0
        assert "warning: binding to 0.0.0.0" in capsys.readouterr().err

    def test_run_prints_receipt_and_sets_exit_code(self, monkeypatch, capsys, workspace):
        from core.engine import set_engine

        (workspace / "a.txt").write_text("hi")
        set_engine(None)
        install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})]), msg("listed a.txt")])
        try:
            assert main(["run", "List", "files"]) == 0
            receipt = json.loads(capsys.readouterr().out)
            assert receipt["status"] == "success" and receipt["final_text"] == "listed a.txt" and receipt["chain_head"]
            install_llm(monkeypatch, [msg("done")])
            assert main(["run", "check", "--verify-file", str(workspace / "a.txt"), "nope"]) == 1   # verification failed
        finally:
            set_engine(None)

    def test_sessions_list_and_show(self, capsys, monkeypatch):
        from core.memory.store import create_session, init_db

        conn = init_db()
        create_session(conn, "sess-1", "devops_agent", "fix the thing")
        assert main(["sessions"]) == 0 and "sess-1" in capsys.readouterr().out
        assert main(["sessions", "sess-1"]) == 0 and json.loads(capsys.readouterr().out)["goal"] == "fix the thing"
        assert main(["sessions", "missing"]) == 1

    def test_approvals_against_a_running_api(self, monkeypatch, capsys):
        import httpx
        from fastapi.testclient import TestClient

        from core.approvals import ApprovalRequest
        from core.gateway import api

        monkeypatch.setenv("HARNESS_API_TOKEN", "tok")
        with TestClient(api.app) as tc:
            def route(method, url, json=None, headers=None, timeout=None):
                return tc.request(method, url.replace("http://127.0.0.1:8000", ""), json=json, headers=headers)

            monkeypatch.setattr(httpx, "request", route)
            monkeypatch.setattr(sys, "argv", ["harness"])
            api.engine.broker._timeout = 10
            assert main(["approvals", "list"]) == 0 and "no pending" in capsys.readouterr().out
            result = {}

            async def ask():
                result["r"] = await api.engine.broker.request(ApprovalRequest("bash", "h", "touch x", "R2"))

            import time

            future = tc.portal.start_task_soon(ask)      # same event loop as the API, like in production
            for _ in range(50):
                if api.engine.broker.pending():
                    break
                time.sleep(0.05)
            assert main(["approvals", "list"]) == 0 and "touch x" in capsys.readouterr().out
            pending_id = api.engine.broker.pending()[0]["id"]
            assert main(["approvals", "approve"]) == 2                     # id required
            assert main(["approvals", "deny", pending_id, "--note", "no"]) == 0
            future.result(5)
            assert result["r"].approved is False and result["r"].note == "no"

    def test_approvals_unreachable_api_message(self, monkeypatch, capsys):
        assert main(["approvals", "list", "--url", "http://127.0.0.1:1"]) == 1
        assert "harness serve" in capsys.readouterr().err

    def test_plugins_and_version(self, capsys):
        assert main(["plugins"]) == 0
        out = capsys.readouterr().out
        assert "fs" in out and "ACTIVE" in out and "FAILED" not in out
        assert main(["version"]) == 0 and "harness-engine 0.2.0" in capsys.readouterr().out

    def test_every_subcommand_is_documented_in_help(self):
        parser = build_parser()
        names = set(parser._subparsers._group_actions[0].choices)
        assert {"init", "serve", "run", "doctor", "token", "sessions", "approvals", "plugins", "version"} <= names


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    base = tmp_path_factory.mktemp("wheel")
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-q", str(ROOT),
                    "-w", str(base / "w")], check=True, capture_output=True, cwd=base)
    wheel = next((base / "w").glob("harness_engine-*.whl"))
    target = base / "site"
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "-q", "--target", str(target), str(wheel)],
                   check=True, capture_output=True)
    shutil_build = ROOT / "build"
    if shutil_build.exists():
        import shutil

        shutil.rmtree(shutil_build, ignore_errors=True)
    return wheel, target



@pytest.mark.integration
class TestWheel:
    """Build the wheel, install it into an empty directory and run it from elsewhere:
    proves defaults, skills and the `harness` entry point are packaged (nothing depends on the checkout)."""

    def test_wheel_contents_and_entry_point(self, installed):
        import zipfile

        wheel, target = installed
        names = zipfile.ZipFile(wheel).namelist()
        for expected in ("core/defaults/agents.yaml", "core/defaults/settings.yaml", "core/defaults/mcp.yaml.example",
                         "domains/devops/skills/argocd-status-check/SKILL.md", "cli/main.py", "core/plugins/dyn_runner.py"):
            assert expected in names, expected
        ep = next(n for n in names if n.endswith("entry_points.txt"))
        assert "harness = cli.main:main" in zipfile.ZipFile(wheel).read(ep).decode()
        assert not [n for n in names if n.startswith(("tests/", "docs/"))]

    def test_installed_copy_runs_from_another_directory(self, installed, tmp_path):
        _wheel, target = installed
        env = {**os.environ, "PYTHONPATH": str(target), "HARNESS_HOME": str(tmp_path / "home")}
        for k in ("HARNESS_API_TOKEN", "HARNESS_DB_PATH", "HARNESS_DATA_DIR", "HARNESS_SETTINGS_FILE"):
            env.pop(k, None)
        cwd = tmp_path / "elsewhere"
        cwd.mkdir()
        run = lambda *a: subprocess.run([sys.executable, "-m", "cli", *a], cwd=cwd, env=env, capture_output=True, text=True)  # noqa: E731
        ver = run("version")
        assert ver.returncode == 0 and "0.2.0" in ver.stdout
        init = run("init", "-y", "--provider", "groq", "--api-key", "k")
        assert init.returncode == 0, init.stderr
        doc = run("doctor", "--json")
        checks = {c["name"]: c for c in json.loads(doc.stdout)}
        assert checks["agents"]["status"] == "ok" and checks["api token"]["status"] == "ok"
        where = subprocess.run([sys.executable, "-c", "import core, sys; print(core.__file__)"], cwd=cwd, env=env,
                               capture_output=True, text=True).stdout.strip()
        assert str(target) in where and str(ROOT) not in where           # really the installed copy
        assert "fs" in run("plugins").stdout                              # engine + bundled skills load from the wheel
        script = target / "bin" / "harness"
        assert script.exists()
        out = subprocess.run([str(script), "version"], cwd=cwd, env=env, capture_output=True, text=True)
        assert out.returncode == 0 and "harness-engine" in out.stdout


class TestInstallScript:
    SCRIPT = ROOT / "install.sh"

    def _run(self, tmp_path, tools, env=None):
        bindir = tmp_path / "bin"
        bindir.mkdir(parents=True, exist_ok=True)
        for name in ("sh", "cat", "dirname", "ln", "mkdir", "pwd"):
            real = subprocess.run(["which", name], capture_output=True, text=True).stdout.strip()
            if real and not (bindir / name).exists():
                (bindir / name).symlink_to(real)
        for tool in tools:
            f = bindir / tool
            if not f.exists():
                f.write_text("#!/bin/sh\nexit 0\n" if not tool.startswith("python") else
                             f"#!/bin/sh\nexec {sys.executable} \"$@\"\n")
                f.chmod(0o755)
        full = {"PATH": str(bindir), "HARNESS_INSTALL_DRY_RUN": "1", "HOME": str(tmp_path), **(env or {})}
        return subprocess.run(["/bin/sh", str(self.SCRIPT)], capture_output=True, text=True, env=full)

    def test_syntax(self):
        assert subprocess.run(["sh", "-n", str(self.SCRIPT)]).returncode == 0

    def test_prefers_uv_then_pipx_then_private_venv(self, tmp_path):
        out = self._run(tmp_path, ["uv", "pipx", "python3"]).stdout
        assert out.startswith("uv tool install --force") and "harness-engine[runtime] @ git+https://github.com/aniketpitre/" in out
        assert self._run(tmp_path / "b", ["pipx", "python3"]).stdout.startswith("pipx install --force")
        venv = self._run(tmp_path / "c", ["python3"], {"HARNESS_VENV": str(tmp_path / "v")}).stdout
        assert "-m venv" in venv and 'pip" install "harness-engine[runtime] @' in venv and ".local/bin/harness" in venv

    def test_sources_and_extras(self, tmp_path):
        pypi = self._run(tmp_path, ["uv"], {"HARNESS_SOURCE": "harness-engine", "HARNESS_EXTRAS": "telegram,vault"}).stdout
        assert '"harness-engine[telegram,vault]"' in pypi
        bare = self._run(tmp_path / "b", ["uv"], {"HARNESS_SOURCE": "harness-engine", "HARNESS_EXTRAS": ""}).stdout
        assert '"harness-engine"' in bare
        local = self._run(tmp_path / "c", ["uv"], {"HARNESS_SOURCE": str(ROOT)}).stdout
        assert f"@ file://{ROOT}" in local

    def test_no_python_gives_a_helpful_message(self, tmp_path):
        r = self._run(tmp_path, [])
        assert r.returncode == 1 and "Python 3.11+" in r.stdout and "astral.sh/uv" in r.stdout
