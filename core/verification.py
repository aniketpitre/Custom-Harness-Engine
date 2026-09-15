from datetime import datetime, timezone
from pathlib import Path

from core.primitives.verification import VerificationResult


def verify_file_content(path: str, expected_content: str) -> VerificationResult:
    file_path = Path(path)
    observed = file_path.read_text(encoding="utf-8") if file_path.exists() else "<missing>"
    return VerificationResult(
        expected=expected_content,
        observed=observed,
        passed=observed.strip() == expected_content.strip(),
        method="file_check",
        checked_at=datetime.now(timezone.utc),
    )