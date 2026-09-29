"""Content scanning for memory writes, skills, project instructions and self-written tools."""
from __future__ import annotations

import re

INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤﻿\U000e0000-\U000e007f]")
_PATTERNS = {
    "prompt-injection": re.compile(
        r"(ignore|disregard|forget)\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|prompts?|rules)|"
        r"you\s+are\s+now\s+(in\s+)?(developer|dan|jailbreak)|reveal\s+(your\s+)?system\s+prompt", re.I),
    "exfiltration": re.compile(
        r"(curl|wget|nc|ncat)\b[^\n]*(\$\w*(KEY|TOKEN|SECRET|PASSWORD)|\.ssh|\.aws|/etc/passwd)|"
        r"cat\s+[^\n|]*(\.ssh|\.aws|\.kube|\.env)\b", re.I),
    "credential": re.compile(
        r"AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(password|secret|api[_-]?key|token)\s*[=:]\s*['\"]?[A-Za-z0-9/+_\-]{12,}", re.I),
    "safety-bypass": re.compile(r"disable[-_ ]?(check|safety|policy|approval)|--no-verify|bypass\s+approval", re.I),
    "external-url": re.compile(r"https?://", re.I),
}


def scan_text(text: str, allow: tuple[str, ...] = ()) -> list[str]:
    """Names of suspicious patterns found in `text` (empty list = clean)."""
    findings = [name for name, rx in _PATTERNS.items() if name not in allow and rx.search(text)]
    if INVISIBLE.search(text):
        findings.append("invisible-unicode")
    return findings
