import re
import subprocess
from pathlib import Path

from git import Repo

from core.primitives.policy import PolicyDecision, RiskTier

_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
GITOPS_MANAGED_ACTIONS = {
    ("kubectl", "restart_pod"): RiskTier.R2,
    ("argocd", "app_sync_staging"): RiskTier.R2,
    ("argocd", "app_sync_production"): RiskTier.R3,
    ("gitops", "propose_change"): RiskTier.R2,
}


def resolve_gitops_route(tool: str, action: str) -> PolicyDecision:
    risk_tier = GITOPS_MANAGED_ACTIONS.get((tool, action))
    if risk_tier is None:
        return PolicyDecision(
            decision="DENY",
            risk_tier=RiskTier.R4,
            reason="Action has no registered GitOps route",
            tool=tool,
            action=action,
        )
    return PolicyDecision(
        decision="REQUIRE_APPROVAL",
        risk_tier=risk_tier,
        reason="GitOps change requires approval before PR creation",
        tool=tool,
        action=action,
    )


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
    """Create, push, and open a GitHub PR for one explicit file change.

    The caller must perform policy and human approval before invoking this mutating
    operation. The working tree must be clean and the target path must remain inside
    the repository.
    """
    if not _BRANCH_PATTERN.fullmatch(branch_name) or branch_name in {"main", "master"}:
        raise ValueError("Invalid or protected branch name")
    if not commit_message.strip() or not pr_title.strip():
        raise ValueError("Commit message and PR title are required")

    repo_path = Path(repo_path).resolve()
    repo = Repo(repo_path)
    if repo.is_dirty(untracked_files=True):
        raise RuntimeError("GitOps action requires a clean working tree")
    if remote_name not in {remote.name for remote in repo.remotes}:
        raise RuntimeError(f"Git remote not found: {remote_name}")

    target = (Path(repo.working_tree_dir) / file_path).resolve()
    # Check if target is inside the working directory
    try:
        target.relative_to(Path(repo.working_tree_dir).resolve())
    except ValueError:
        raise ValueError("Target path must be within the repository")
    target.parent.mkdir(parents=True, exist_ok=True)

    if branch_name in {head.name for head in repo.heads}:
        raise RuntimeError(f"Branch already exists: {branch_name}")
    branch = repo.create_head(branch_name)
    branch.checkout()
    try:
        target.write_text(content, encoding="utf-8")
        repo.index.add([str(target.relative_to(repo.working_tree_dir))])
        if not repo.index.diff("HEAD"):
            raise RuntimeError("GitOps action produced no file change")
        repo.index.commit(commit_message)
        repo.remote(remote_name).push(branch_name)
        result = subprocess.run(
            ["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--head", branch_name],
            cwd=repo.working_tree_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "GitHub PR creation failed")
        return result.stdout.strip()
    finally:
        # Checkout the branch we were on previously
        for ref in repo.heads:
            if ref.name != branch_name:
                ref.checkout()
                break
