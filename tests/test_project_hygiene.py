"""Repository hygiene: the things the audit flagged about packaging, secrets and deployment files."""
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_expected_files_exist():
    for f in ("pyproject.toml", "docker-compose.yml", ".env.example", "Dockerfile", ".github/workflows/ci.yml",
              ".gitleaks.toml", "core/__init__.py", "domains/__init__.py"):
        assert (ROOT / f).is_file(), f


def test_gitignore_excludes_secrets_and_local_state():
    text = (ROOT / ".gitignore").read_text()
    for entry in (".env", "data/", "config/mcp.yaml", "config/hooks.yaml"):
        assert entry in text


def test_repo_root_is_free_of_one_off_patch_scripts():
    stray = [p.name for p in ROOT.iterdir() if re.match(r"(fix_|patch_).*|test_type\.py|current_diff\.patch|.*\.(rej|orig)$", p.name)]
    assert stray == []
    assert not list((ROOT / "core").rglob("*.rej")) and not list((ROOT / "core").rglob("*.orig"))


def test_no_hardcoded_tokens_in_tracked_sources():
    pattern = re.compile(r"(?<![A-Za-z0-9])(hvs\.[A-Za-z0-9_-]{20,}|s\.[A-Za-z0-9]{24}|[0-9a-f]{64}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})")
    offenders = []
    for path in list((ROOT / "core").rglob("*.py")) + list((ROOT / "domains").rglob("*.py")) + \
            list((ROOT / "tests").rglob("*.py")) + [ROOT / "main.py", ROOT / "start.sh"]:
        for m in pattern.finditer(path.read_text(errors="ignore")):
            if not m.group(0).startswith("AKIAABCDEFGH"):        # the fake key used by scanner tests
                offenders.append((path.name, m.group(0)[:12]))
    assert offenders == []


def test_compose_gives_the_harness_no_root_token_and_binds_loopback():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    harness = compose["services"]["harness"]
    env = harness["environment"]
    assert "VAULT_TOKEN" not in env and "VAULT_TOKEN_FILE" in env
    assert all("VAULT_DEV_ROOT_TOKEN_ID" not in str(v) for v in env.values())
    assert all(p.startswith("127.0.0.1:") for p in harness["ports"])
    assert "network_mode" not in harness
    assert all(p.startswith("127.0.0.1:") for p in compose["services"]["vault"]["ports"])
    assert "HARNESS_API_TOKEN" in env


def test_vault_init_creates_a_read_only_policy_token():
    script = (ROOT / "docker/init-vault.sh").read_text()
    assert 'capabilities = ["read"]' in script and "vault token create -policy=harness-read" in script
    assert "create" not in script.split("harness-read - <<'POLICY'")[1].split("POLICY")[0].replace("capabilities", "")


def test_dockerfile_runs_the_api_as_non_root_with_all_packages():
    text = (ROOT / "Dockerfile").read_text()
    assert "USER harness" in text and 'CMD ["python", "main.py"]' in text and "COPY cli" in text
    assert "HEALTHCHECK" in text


def test_start_script_protects_the_env_file():
    text = (ROOT / "start.sh").read_text()
    assert "chmod 600 .env" in text and "umask 077" in text and "docker compose" in text and "docker-compose" not in text
    assert subprocess.run(["bash", "-n", str(ROOT / "start.sh")]).returncode == 0


def test_pyproject_dependencies_are_declared_and_split():
    import tomllib

    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    deps = " ".join(cfg["dependencies"])
    assert "claude-agent-sdk" not in deps and "pytest" not in deps and "kubernetes" not in deps
    assert {"telegram", "vault", "devops", "mcp", "otel", "setup", "dev"} <= set(cfg["optional-dependencies"])
    assert "questionary" in " ".join(cfg["optional-dependencies"]["setup"])
    assert "opentelemetry-instrumentation-litellm" in " ".join(cfg["optional-dependencies"]["otel"])


def test_importing_the_core_does_not_pull_in_heavy_optional_packages():
    """Cold start: kubernetes, telegram, git, hvac and litellm load lazily, not at import time."""
    code = ("import sys, core.gateway.api, core.loop\n"
            "heavy = [m for m in ('kubernetes', 'telegram', 'git', 'hvac', 'litellm', 'mcp') if m in sys.modules]\n"
            "print(','.join(heavy))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "", out.stdout


def test_engine_starts_without_optional_integrations_installed():
    code = ("import sys\n"
            "for m in ('kubernetes', 'telegram', 'git', 'hvac', 'mcp'):\n"
            "    sys.modules[m] = None\n"       # simulate not installed
            "import asyncio\nfrom core.engine import Engine\n"
            "e = Engine()\nasyncio.run(e.ensure_started())\n"
            "print(len(e.registry.names()))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert int(out.stdout.strip()) > 20


def test_ci_runs_tests_lint_and_secret_scan():
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    text = str(ci)
    assert "pytest" in text and "ruff check" in text and "gitleaks" in text


def test_docs_are_organised():
    assert (ROOT / "docs" / "Harness_Engine_Audit.md").is_file() and (ROOT / "docs/refs/Deepseek-harness-paper.pdf").is_file()
    assert not (ROOT / "Deepseek-harness-paper.pdf").exists()
