"""Phase 2: Minimal agent loop — agent_engine tool dispatch and wiring."""
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock
import json

import pytest

from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.agent_engine import (
    _read_directory,
    _build_prompt,
    _dispatch_devops_read_tool,
    READ_DIRECTORY_TOOL,
    DEVOPS_READ_TOOLS,
    DEVOPS_ACTION_TOOLS,
)


NOW = datetime.now(timezone.utc)


def _make_context(raw_input="test goal"):
    return ContextPacket(
        goal=Goal(id="g1", source=TriggerSource.cli, raw_input=raw_input, created_at=NOW),
        memory_hits=[], live_state={}, recent_history=[], tool_catalog=[], evidence=[],
    )


def test_read_directory_lists_current_dir():
    result = _read_directory(".")
    assert "[dir]" in result or "[file]" in result


def test_read_directory_rejects_parent_traversal():
    with pytest.raises(PermissionError):
        _read_directory("../../..")


def test_read_directory_rejects_nonexistent_dir():
    with pytest.raises(NotADirectoryError):
        _read_directory("nonexistent_dir_xyz")


def test_build_prompt_includes_goal():
    context = _make_context("List all pods")
    prompt = _build_prompt(context)
    assert "List all pods" in prompt


def test_tool_schemas_are_well_formed():
    assert READ_DIRECTORY_TOOL["type"] == "function"
    assert READ_DIRECTORY_TOOL["function"]["name"] == "read_directory"

    for tool in DEVOPS_READ_TOOLS:
        assert tool["type"] == "function"
        assert "name" in tool["function"]

    for tool in DEVOPS_ACTION_TOOLS:
        assert tool["type"] == "function"
        assert "name" in tool["function"]


def test_tool_schema_names():
    read_names = {t["function"]["name"] for t in DEVOPS_READ_TOOLS}
    assert read_names == {"kubectl_get_pods", "kubectl_describe_pod", "kubectl_logs", "argocd_app_list", "argocd_app_get"}

    write_names = {t["function"]["name"] for t in DEVOPS_ACTION_TOOLS}
    assert write_names == {"gitops_propose_change", "kubectl_restart_pod", "argocd_app_sync_production"}
