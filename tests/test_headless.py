"""Headless contract (output formats, exit codes, summary) and the GitHub Action's shell step."""
import io
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from cli.main import main
from core import headless
from core.approvals import ApprovalBroker, set_broker
from tests.helpers import install_llm, msg

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fresh_engine(monkeypatch):
    """`harness run` uses the process-wide engine; give each test its own."""
    import core.engine as eng

    monkeypatch.setattr(eng, "_engine", None, raising=False)
    yield


def _run(capsys, *argv):
    code = main(["run", *argv])
    return code, capsys.readouterr()


@pytest.mark.unit
def test_exit_codes():
    assert headless.exit_code("success", "completed") == 0
    assert headless.exit_code("failure", "completed") == 1           # verification failed
    assert headless.exit_code("failure", "error") == 1
    for o in ("budget_exhausted", "turn_limit", "time_limit"):
        assert headless.exit_code("failure", o) == 3


def test_json_output_is_a_stable_result(capsys, monkeypatch, workspace):
    (workspace / "a.txt").write_text("hi")
    install_llm(monkeypatch, [msg(tool_calls=[("read", {"path": "a.txt"})]), msg("all good")])
    code, out = _run(capsys, "check", "files", "--output-format", "json")
    res = json.loads(out.out)
    assert code == 0 and res["exit_code"] == 0 and res["schema_version"] == 1 and res["type"] == "result"
    assert res["final_text"] == "all good" and res["status"] == "success" and res["outcome"] == "completed"
    assert res["actions"][0]["tool"] == "filesystem" and res["actions"][0]["decision"] == "ALLOW"
    assert res["usage"]["cost_usd"] > 0 and res["usage"]["turns"] == 2 and res["duration_seconds"] >= 0
    assert "message_history" not in res


def test_stream_json_emits_events_then_the_result(capsys, monkeypatch, workspace):
    install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})]), msg("done")])
    code, out = _run(capsys, "list", "--output-format", "stream-json")
    lines = [json.loads(line) for line in out.out.strip().splitlines()]
    types = [e["type"] for e in lines]
    assert code == 0 and types[-1] == "result" and "tool_call" in types and "tool_result" in types
    assert "usage" in types and "final_receipt" not in types and "keepalive" not in types


def test_text_output_and_goal_from_stdin(capsys, monkeypatch):
    install_llm(monkeypatch, [msg("the answer")])
    monkeypatch.setattr(sys, "stdin", io.StringIO("what is up?\n"))
    code, out = _run(capsys, "-", "--output-format", "text")
    assert code == 0 and out.out.strip() == "the answer"


def test_goal_file_and_usage_errors(capsys, monkeypatch, tmp_path):
    install_llm(monkeypatch, [msg("ok")])
    f = tmp_path / "goal.md"
    f.write_text("do the thing")
    assert _run(capsys, "--goal-file", str(f), "--output-format", "text")[0] == 0
    code, out = _run(capsys, "--output-format", "json")
    assert code == 2 and "no goal" in out.err
    code, out = _run(capsys, "x", "--agent", "nope", "--output-format", "json")
    assert code == 2 and "Unknown agent" in out.err


def test_limit_exit_code_and_verification_failure(capsys, monkeypatch, workspace):
    install_llm(monkeypatch, [msg(tool_calls=[("read_directory", {"path": "."})], tokens=2_000_000)] * 3)
    code, out = _run(capsys, "g", "--output-format", "json", "--max-cost", "0.01")
    assert code == 3 and json.loads(out.out)["outcome"] == "budget_exhausted"
    install_llm(monkeypatch, [msg("done")])
    code, out = _run(capsys, "g", "--output-format", "json", "--verify-file", str(workspace / "nope"), "x")
    res = json.loads(out.out)
    assert code == 1 and res["verified"] is False and res["verification"]["passed"] is False


def test_approval_timeout_zero_denies_immediately(capsys, monkeypatch, workspace):
    set_broker(ApprovalBroker())            # timeout from settings, as in production
    import time

    install_llm(monkeypatch, [msg(tool_calls=[("write", {"path": "a.txt", "content": "x"})]), msg("could not")])
    started = time.monotonic()
    code, out = _run(capsys, "g", "--output-format", "json", "--approval-timeout", "0", "--mode", "strict")
    res = json.loads(out.out)
    assert time.monotonic() - started < 10 and res["outcome"] == "completed"
    assert [a["decision"] for a in res["actions"]] == ["DENY"] and not (workspace / "a.txt").exists()


def test_summary_file_is_markdown(capsys, monkeypatch, tmp_path):
    install_llm(monkeypatch, [msg("fine")])
    summary = tmp_path / "summary.md"
    summary.write_text("# existing\n")
    assert _run(capsys, "g", "--output-format", "json", "--summary-file", str(summary))[0] == 0
    text = summary.read_text()
    assert text.startswith("# existing\n") and "### ✅ Harness run: success (completed)" in text
    assert "| Cost |" in text and "#### Answer" in text and "fine" in text


def test_receipt_format_is_unchanged(capsys, monkeypatch):
    install_llm(monkeypatch, [msg("x")])
    code, out = _run(capsys, "g")
    assert code == 0 and json.loads(out.out)["run_id"] and "message_history" in json.loads(out.out)


# -- the GitHub Action ----------------------------------------------------------------------------
ACTION = yaml.safe_load((ROOT / "action.yml").read_text())


@pytest.mark.unit
def test_action_metadata():
    assert ACTION["runs"]["using"] == "composite"
    assert ACTION["inputs"]["mode"]["default"] == "read-only"          # safe by default in CI
    assert ACTION["inputs"]["approval-timeout"]["default"] == "0"
    assert {"status", "outcome", "exit-code", "cost-usd", "session-id", "result-file"} <= set(ACTION["outputs"])


SHIM = textwrap.dedent('''\
    #!{python}
    import sys
    sys.path.insert(0, {root!r})
    from types import SimpleNamespace
    import litellm
    reply = {reply!r}
    async def fake(**kw):
        m = SimpleNamespace(role="assistant", content=reply, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=m)],
                               usage=SimpleNamespace(total_tokens=30, prompt_tokens=20, completion_tokens=10))
    litellm.acompletion = fake
    from cli.main import main
    sys.exit(main())
''')


@pytest.mark.parametrize("fail_on,expected_exit", [("failure", 0), ("never", 0)])
def test_action_run_step_end_to_end(tmp_path, fail_on, expected_exit):
    """Execute the action's real bash step with a `harness` shim that fakes only the model."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "harness"
    shim.write_text(SHIM.format(python=sys.executable, root=str(ROOT), reply="LGTM"))
    shim.chmod(0o755)
    step = next(s for s in ACTION["runs"]["steps"] if s.get("id") == "run")
    out, summary = tmp_path / "out.txt", tmp_path / "summary.md"
    env = {k: v for k, v in os.environ.items() if not k.startswith("HARNESS_")}
    env.update({"PATH": f"{bin_dir}:{env['PATH']}", "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(out),
                "GITHUB_STEP_SUMMARY": str(summary), "HARNESS_HOME": str(tmp_path / "home"),
                "HARNESS_WORKSPACE": str(tmp_path), "HARNESS_DB_PATH": str(tmp_path / "db.sqlite"),
                "HARNESS_DATA_DIR": str(tmp_path / "data"), "HARNESS_STREAM": "false",
                "GOAL": "review the repo", "GOAL_FILE": "", "AGENT": "devops_agent", "MODE": "read-only",
                "MODEL": "groq/openai/gpt-oss-120b", "MAX_COST": "1", "APPROVAL_TIMEOUT": "0", "FAIL_ON": fail_on})
    proc = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == expected_exit, proc.stderr
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines())
    assert outputs["status"] == "success" and outputs["exit-code"] == "0" and outputs["outcome"] == "completed"
    assert float(outputs["cost-usd"]) > 0 and outputs["session-id"]
    assert json.loads(Path(outputs["result-file"]).read_text())["final_text"] == "LGTM"
    assert "Harness run: success" in summary.read_text()
