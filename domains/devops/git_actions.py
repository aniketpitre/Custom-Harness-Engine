"""GitOps: propose a change as a pull request from an isolated git worktree.

The user's checkout is never touched: the change is made in a temporary worktree on a new
branch, pushed, opened as a PR with `gh`, and the worktree and local branch are removed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.confine import safe_env
from core.primitives.policy import PolicyDecision, RiskTier
from domains.devops.policy_table import TOOL_RISK_TABLE

_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
# One source of truth: the GitOps-managed subset of the risk table.
GITOPS_MANAGED_ACTIONS = {
    k: v for k, v in TOOL_RISK_TABLE.items()
    if k[0] in {"gitops", "argocd"} or k == ("kubectl", "restart_pod")
}


def resolve_gitops_route(tool: str, action: str) -> PolicyDecision:
    risk_tier = GITOPS_MANAGED_ACTIONS.get((tool, action))
    if risk_tier is None:
        return PolicyDecision(decision="DENY", risk_tier=RiskTier.R4,
                              reason="Action has no registered GitOps route", tool=tool, action=action)
    return PolicyDecision(decision="REQUIRE_APPROVAL", risk_tier=risk_tier,
                          reason="GitOps change requires approval before PR creation", tool=tool, action=action)


def allowed_repo(repo_path: str | Path, allowlist: tuple[str, ...], workspace: Path) -> bool:
    repo = Path(repo_path).resolve()
    roots = [Path(p).resolve() for p in allowlist] or [workspace.resolve()]
    return any(repo == r or r in repo.parents for r in roots)


def create_change_pr(
    repo_path: str | Path,
    branch_name: str,
    file_path: str,
    content: str,
    commit_message: str,
    pr_title: str,
    pr_body: str,
    remote_name: str = "origin",
) -> str:
    """Create, push and open a PR for one file change. Caller must have approval."""
    from git import Repo

    if not _BRANCH_PATTERN.fullmatch(branch_name) or branch_name in {"main", "master"} or ".." in branch_name:
        raise ValueError("Invalid or protected branch name")
    if not commit_message.strip() or not pr_title.strip():
        raise ValueError("Commit message and PR title are required")

    repo = Repo(Path(repo_path).resolve())
    if remote_name not in {r.name for r in repo.remotes}:
        raise RuntimeError(f"Git remote not found: {remote_name}")
    if branch_name in {h.name for h in repo.heads}:
        raise RuntimeError(f"Branch already exists: {branch_name}")

    tmp = Path(tempfile.mkdtemp(prefix="harness-gitops-"))
    worktree = tmp / "wt"
    try:
        repo.git.worktree("add", "-b", branch_name, str(worktree), "HEAD")
        wt = Repo(worktree)
        target = (worktree / file_path).resolve()
        if worktree.resolve() not in target.parents:
            raise ValueError("Target path must be within the repository")
        if ".git" in target.relative_to(worktree.resolve()).parts:
            raise ValueError("Refusing to write inside .git")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        wt.index.add([str(target.relative_to(worktree.resolve()))])
        if not wt.index.diff("HEAD"):
            raise RuntimeError("GitOps action produced no file change")
        wt.index.commit(commit_message)
        wt.remote(remote_name).push(branch_name)
        result = subprocess.run(
            ["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--head", branch_name],
            cwd=worktree, check=False, capture_output=True, text=True, timeout=60,
            env=safe_env(extra_allow=("GITHUB_TOKEN", "GH_TOKEN", "GH_HOST")))
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "GitHub PR creation failed")
        return result.stdout.strip()
    finally:
        try:
            repo.git.worktree("remove", "--force", str(worktree))
        except Exception:  # noqa: BLE001
            shutil.rmtree(worktree, ignore_errors=True)
            try:
                repo.git.worktree("prune")
            except Exception:  # noqa: BLE001
                pass
        try:
            repo.git.branch("-D", branch_name)
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(tmp, ignore_errors=True)
