import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ENV_KEYS = [k for k in os.environ if k.startswith(("HARNESS_", "VAULT_"))]


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets its own DB, data dir and workspace; no Vault, no real tokens."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT"):
        monkeypatch.delenv(key, raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("HARNESS_DB_PATH", str(tmp_path / "data" / "memory.db"))
    monkeypatch.setenv("HARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HARNESS_WORKSPACE", str(workspace))
    monkeypatch.setenv("HARNESS_API_TOKEN", "test-token")
    monkeypatch.setenv("HARNESS_STREAM", "false")
    monkeypatch.setenv("HARNESS_SETTINGS_FILE", str(tmp_path / "no-settings.yaml"))
    monkeypatch.chdir(workspace)
    from core import secrets
    from core.approvals import ApprovalBroker, set_broker
    from core.memory.store import forget_migrations

    secrets.clear_cache()
    forget_migrations()
    set_broker(ApprovalBroker(timeout=2))
    yield workspace
    set_broker(None)


@pytest.fixture
def workspace(isolated_env):
    return isolated_env


@pytest.fixture
async def engine():
    from core.approvals import get_broker
    from core.engine import Engine

    e = Engine(broker=get_broker())
    await e.ensure_started()
    yield e
    await e.shutdown()
