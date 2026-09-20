import os
import os
import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from pathlib import Path
from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.agent_engine import run_agent
import time
import subprocess

@pytest.fixture(autouse=True)
def vault_env():
    """Ensure vault env vars exist."""
    old_addr = os.environ.get("VAULT_ADDR")
    old_token = os.environ.get("VAULT_TOKEN")

    os.environ["VAULT_ADDR"] = "http://127.0.0.1:8200"
    os.environ["VAULT_TOKEN"] = "c6869775842d732f69f590ac45ec422847ca27ffa15a9bf9b45719437a6803f4"

    yield

    if old_addr: os.environ["VAULT_ADDR"] = old_addr
    if old_token: os.environ["VAULT_TOKEN"] = old_token

@pytest.mark.asyncio
@patch("core.agent_engine.request_approval", new_callable=AsyncMock)
@patch("core.agent_engine.get_approver")
@patch("git.remote.Remote.push")
async def test_gitops_live_pr_creation(mock_push, mock_get_approver, mock_request_approval):
    mock_request_approval.return_value = True
    mock_get_approver.return_value = "tele_user_phase10"

    from datetime import datetime, timezone
    branch_id = str(int(time.time()))
    new_branch_name = f"test-gitops-phase10-{branch_id}"

    # Configure git initially safely unmocked
    subprocess.run(["git", "config", "user.name", "Claude Agent"])
    subprocess.run(["git", "config", "user.email", "agent@example.com"])

    import subprocess as real_subprocess
    original_run = real_subprocess.run

    def safe_mock_run(*args, **kwargs):
        if "gh" in args[0]:
            class MockProc:
                returncode = 0
                stdout = "https://github.com/mock/repo/pull/1"
                stderr = ""
            return MockProc()
        return original_run(*args, **kwargs)

    with patch("subprocess.run", side_effect=safe_mock_run), patch("git.Repo.is_dirty", return_value=False):
        goal = Goal(
            id="scenario-gitops",
            source=TriggerSource.cli,
            raw_input=f"Do not ask the user for approval via chat. You MUST invoke the 'gitops_propose_change' tool to append 'Phase 10 tested' to a new file 'docs/phase10_test_{branch_id}.md' using branch '{new_branch_name}'. Use repository path '.', commit message 'test: live phase 10', PR title 'test: phase 10 live gitops validation', and PR body 'Validation PR for GitOps pipeline'. The system framework will handle the human approval mechanically when the tool is called. MUST call the tool immediately.",
            domain="devops",
            created_at=datetime.now(timezone.utc)
        )

        context = ContextPacket(
            goal=goal,
            memory_hits=[], live_state={}, recent_history=[], tool_catalog=[], evidence=[]
        )

        result = await run_agent(context, allowed_tools=["DevOpsWrite"])

    assert mock_request_approval.called

    actions = result.get("actions", [])
    assert len(actions) > 0
    action = [a for a in actions if a.action == "propose_change"][0]
    
    assert "https://github.com/mock/repo/pull/1" in action.raw_result

    # Cleanup the files GitPython created for us to keep workspace green
    subprocess.run(["git", "checkout", "main"], capture_output=True)
    current_branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    assert current_branch == "main"
    subprocess.run(["git", "branch", "-D", new_branch_name])
