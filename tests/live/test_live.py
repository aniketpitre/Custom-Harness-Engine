"""Live tests: need real infrastructure. Skipped by default; run with `pytest -m live tests/live`.

Environment: VAULT_ADDR/VAULT_TOKEN (Vault with llm secret), a reachable cluster + argocd CLI for the
DevOps checks, GITHUB_TOKEN + `gh` and a scratch repo (HARNESS_LIVE_REPO) for the GitOps check.
"""
import os
import shutil

import pytest

from tests.helpers import context

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def real_settings(monkeypatch):
    # undo the unit-test isolation for the pieces live tests need
    for k in ("VAULT_ADDR", "VAULT_TOKEN"):
        if os.environ.get(f"LIVE_{k}"):
            monkeypatch.setenv(k, os.environ[f"LIVE_{k}"])


async def test_live_agent_lists_argocd_apps(engine):
    if not shutil.which("argocd"):
        pytest.skip("argocd CLI not installed")
    from core.loop import run_agent

    r = await run_agent(context("List the ArgoCD applications currently deployed."), ["Read", "DevOpsRead"], engine=engine)
    assert r["outcome"] == "completed" and r["actions"] and r["actions"][0].tool == "argocd"


async def test_live_argocd_app_get_missing_app():
    if not shutil.which("argocd"):
        pytest.skip("argocd CLI not installed")
    from domains.devops.tools.argocd_tools import argocd_app_get

    with pytest.raises(RuntimeError):
        argocd_app_get("non-existent-app")


async def test_live_gitops_pr(engine, tmp_path, monkeypatch):
    repo = os.environ.get("HARNESS_LIVE_REPO")
    if not (repo and os.environ.get("GITHUB_TOKEN") and shutil.which("gh")):
        pytest.skip("HARNESS_LIVE_REPO, GITHUB_TOKEN and gh are required")
    import time

    from domains.devops.git_actions import create_change_pr

    branch = f"harness-live-{int(time.time())}"
    url = create_change_pr(repo, branch, f"docs/live_{branch}.md", "Live GitOps validation\n", "test: live gitops",
                           "test: live gitops validation", "Validation PR from the live test suite")
    assert url.startswith("http")


async def test_live_vault_secret_roundtrip():
    if not (os.environ.get("VAULT_ADDR") and os.environ.get("VAULT_TOKEN")):
        pytest.skip("Vault not configured")
    from core.secrets import get_secret

    assert get_secret("llm", "api_key")
