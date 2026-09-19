import pytest
import asyncio
from unittest.mock import patch, MagicMock
from core.primitives.orchestration import Phase, OrchestrationPlan, SubagentSpec
from core.primitives.context import ContextPacket
from core.primitives.goal import Goal, TriggerSource
from datetime import datetime
from core.orchestration.executor import execute_plan
import json

@pytest.fixture
def mock_run_agent():
    with patch("core.orchestration.executor.run_agent") as mock_run:
        yield mock_run

@pytest.fixture
def mock_db_checkpoints(tmp_path):
    with patch("core.orchestration.executor.init_db") as mock_init:
        # We need a real sqlite db to test checkpoint behavior
        import sqlite3
        db_path = tmp_path / "test_store.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow_checkpoints (
                workflow_id TEXT,
                phase_index INTEGER,
                status TEXT,
                result_json TEXT,
                updated_at TEXT,
                PRIMARY KEY (workflow_id, phase_index)
            )
        """)
        conn.commit()
        mock_init.return_value = conn
        yield conn

@pytest.mark.asyncio
async def test_adversarial_cross_check(mock_run_agent, mock_db_checkpoints):
    # Phase 1: Audit namespaces
    # Phase 2: Verify findings
    
    spec_audit = SubagentSpec(
        id="auditor-1",
        goal="Find all pods with privileged: true in the namespace",
        tool_scope=["DevOpsRead"]
    )
    phase_1 = Phase(name="Audit", subagent_specs=[spec_audit])
    
    spec_verify = SubagentSpec(
        id="verifier-1",
        goal="Cross check phase 1 findings against Git manifests",
        tool_scope=["Read"]
    )
    phase_2 = Phase(name="Cross-check", subagent_specs=[spec_verify])
    
    plan = OrchestrationPlan(
        id="wf-test-1",
        goal="Audit and verify privileged pods",
        phases=[phase_1, phase_2]
    )
    
    context = ContextPacket(
        goal=Goal(
            id="g1", 
            source=TriggerSource.cli, 
            raw_input=plan.goal, 
            created_at=datetime.utcnow()
        ),
        memory_hits=[],
        live_state={},
        recent_history=[],
        tool_catalog=[]
    )
    
    mock_run_agent.side_effect = [
        {"events": [], "final_text": "Found privileged pod xyz in namespace web", "model_used": "test"},
        {"events": [], "final_text": "Verified: Git manifests show pod xyz is indeed privileged", "model_used": "test"}
    ]
    
    results = await execute_plan(plan, context)
    
    assert len(results) == 2
    assert "Found privileged" in results[0][0]["final_text"]
    assert "Verified:" in results[1][0]["final_text"]
    
    # Check that database checkpoint is completed
    row = mock_db_checkpoints.execute("SELECT status FROM workflow_checkpoints WHERE workflow_id = 'wf-test-1' AND phase_index = 0").fetchone()
    assert row["status"] == "completed"
    
    # Test resumption
    mock_run_agent.reset_mock()
    # Execute same plan again, it should skip due to checkpoint completed
    resume_results = await execute_plan(plan, context)
    
    # Mock should not be called since it loads from checkpoint
    assert mock_run_agent.call_count == 0
    assert resume_results[0][0]["final_text"] == "Found privileged pod xyz in namespace web"
