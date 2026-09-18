#!/usr/bin/env python3
"""
Test script to verify Phase 7 DevOps tools work through the agent engine
"""
import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

# Set up Vault environment
os.environ["VAULT_ADDR"] = "http://127.0.0.1:8200"
os.environ["VAULT_TOKEN"] = "c6869775842d732f69f590ac45ec422847ca27ffa15a9bf9b45719437a6803f4"
os.environ["VAULT_MOUNT_POINT"] = "harness-secrets"

from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.agent_engine import run_agent

async def test_kubectl_tools():
    """Test that we can use kubectl tools through the agent engine"""
    
    # Create a goal to list pods in test-harness namespace
    goal = Goal(
        id=str(uuid4()),
        source=TriggerSource.cli,
        raw_input="List the pods in the test-harness namespace",
        created_at=datetime.now(timezone.utc),
        domain="devops"
    )
    
    # Create context with the goal
    context = ContextPacket(
        goal=goal,
        memory_hits=[],
        live_state={},
        recent_history=[],
        tool_catalog=[],  # Will be populated by agent_engine
        evidence=[]
    )
    
    # Run the agent with DevOps read tools allowed
    result = await run_agent(context, allowed_tools=[
        "read_directory", 
        "kubectl_get_pods",
        "kubectl_describe_pod", 
        "kubectl_logs"
    ])
    
    print("Agent result:")
    print(f"Final text: {result.get('final_text', 'No final text')}")
    print(f"Events count: {len(result.get('events', []))}")
    
    return result

if __name__ == "__main__":
    result = asyncio.run(test_kubectl_tools())
    print("\nTest completed successfully!")