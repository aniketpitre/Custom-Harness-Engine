#!/usr/bin/env python3
"""
Test script to verify Phase 7 DevOps tools work through the agent engine
"""
import sys
import asyncio
import os
from datetime import datetime, timezone
from uuid import uuid4

# Add the project root to the Python path
sys.path.insert(0, '/workspaces/Custom-Harness-Engine')

# Set up Vault environment
os.environ["VAULT_ADDR"] = "http://127.0.0.1:8200"
os.environ["VAULT_TOKEN"] = "c6869775842d732f69f590ac45ec422847ca27ffa15a9bf9b45719437a6803f4"
os.environ["VAULT_MOUNT_POINT"] = "harness-secrets"

from core.primitives.goal import Goal, TriggerSource
from core.primitives.context = ContextPacket
from core.agent_engine = run_agent