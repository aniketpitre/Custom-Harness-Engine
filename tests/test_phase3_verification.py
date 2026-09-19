"""Phase 3: Verification — verify_file_content and wiring into context."""
from core.verification import verify_file_content
from core.primitives.context import ContextPacket
from core.primitives.goal import Goal, TriggerSource
from core.agent_engine import _run_requested_verification
from datetime import datetime, timezone

NOW = datetime.now(timezone.utc)


def test_verification_passes_matching(tmp_path):
    f = tmp_path / "ok.txt"
    f.write_text("hello world\n")
    result = verify_file_content(str(f), "hello world")
    assert result.passed is True
    assert result.method == "file_check"


def test_verification_fails_mismatch(tmp_path):
    f = tmp_path / "bad.txt"
    f.write_text("wrong")
    result = verify_file_content(str(f), "expected")
    assert result.passed is False


def test_verification_reports_missing(tmp_path):
    result = verify_file_content(str(tmp_path / "no.txt"), "anything")
    assert result.passed is False
    assert result.observed == "<missing>"


def test_run_requested_verification_returns_none_without_request():
    ctx = ContextPacket(
        goal=Goal(id="g1", source=TriggerSource.cli, raw_input="test", created_at=NOW),
        live_state={},
    )
    assert _run_requested_verification(ctx) is None


def test_run_requested_verification_with_valid_request(tmp_path):
    f = tmp_path / "v.txt"
    f.write_text("content")
    ctx = ContextPacket(
        goal=Goal(id="g1", source=TriggerSource.cli, raw_input="test", created_at=NOW),
        live_state={"verification": {"path": str(f), "expected_content": "content"}},
    )
    result = _run_requested_verification(ctx)
    assert result is not None
    assert result.passed is True
