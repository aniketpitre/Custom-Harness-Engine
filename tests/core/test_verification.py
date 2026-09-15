from core.verification import verify_file_content


def test_file_content_verification_passes_for_matching_content(tmp_path) -> None:
    target = tmp_path / "result.txt"
    target.write_text("verified output\n", encoding="utf-8")

    result = verify_file_content(str(target), "verified output")

    assert result.passed is True
    assert result.expected == "verified output"
    assert result.observed == "verified output\n"
    assert result.method == "file_check"


def test_file_content_verification_catches_mismatched_content(tmp_path) -> None:
    target = tmp_path / "result.txt"
    target.write_text("corrupted output", encoding="utf-8")

    result = verify_file_content(str(target), "expected output")

    assert result.passed is False
    assert result.expected == "expected output"
    assert result.observed == "corrupted output"


def test_file_content_verification_reports_missing_file(tmp_path) -> None:
    result = verify_file_content(str(tmp_path / "missing.txt"), "expected output")

    assert result.passed is False
    assert result.observed == "<missing>"