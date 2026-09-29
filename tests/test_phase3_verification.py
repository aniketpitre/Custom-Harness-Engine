"""Phase 3: Verification — verify_file_content and wiring into context."""
from core.verification import verify_file_content
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


async def test_run_verification_none_without_request():
    from core.verifiers import run_verification

    assert await run_verification(None) is None


async def test_run_verification_legacy_spec_and_typed_spec(tmp_path):
    from core.verifiers import run_verification

    f = tmp_path / "v.txt"
    f.write_text("content")
    legacy = await run_verification({"path": str(f), "expected_content": "content"})
    typed = await run_verification({"type": "file_content", "path": str(f), "expected_content": "nope"})
    assert legacy.passed is True and typed.passed is False


async def test_unknown_or_broken_verifier_is_a_failed_verification():
    from core.verifiers import run_verification

    assert (await run_verification({"type": "nonsense"})).passed is False
    broken = await run_verification({"type": "file_content", "path": 5})
    assert broken.passed is False and "error" in broken.observed
