"""Confinement helpers shared by every file, web and shell tool.

* workspace path confinement (symlink-safe, deny list, engine-source write protection)
* SSRF guard for outbound HTTP
* environment filtering for child processes
* shell command classifier (hard blocklist + risk tier)
"""
from __future__ import annotations

import fnmatch
import ipaddress
import os
import re
import shlex
import socket
from pathlib import Path
from urllib.parse import urlsplit

from core.primitives.policy import RiskTier

ENGINE_ROOT = Path(__file__).resolve().parent.parent
DENY_PARTS = {".ssh", ".aws", ".kube", ".gnupg", ".docker", "secrets"}
DENY_NAMES = {".env", ".netrc", "id_rsa", "id_ed25519", "credentials"}
ENGINE_PROTECTED = ("core", "domains", "cli", "main.py", "pyproject.toml", ".git", ".github")


class ConfinementError(PermissionError):
    pass


def _roots(roots: list[Path] | None) -> list[Path]:
    if roots:
        return [Path(r).resolve() for r in roots]
    from core.settings import settings

    return [settings().workspace]


def resolve_workspace_path(
    path: str | os.PathLike, *, write: bool = False, roots: list[Path] | None = None
) -> Path:
    """Resolve `path` inside the workspace, following symlinks. Raises ConfinementError."""
    allowed = _roots(roots)
    raw = Path(path)
    candidate = raw if raw.is_absolute() else allowed[0] / raw
    resolved = candidate.resolve()
    root = next((r for r in allowed if resolved == r or r in resolved.parents), None)
    if root is None:
        raise ConfinementError("Path is outside the workspace")
    for part in resolved.relative_to(root).parts:
        if part in DENY_PARTS:
            raise ConfinementError(f"Access to '{part}' is restricted")
    if resolved.name in DENY_NAMES or resolved.name.startswith(".env."):
        raise ConfinementError(f"Access to '{resolved.name}' is restricted")
    if write:
        for protected in ENGINE_PROTECTED:
            target = (ENGINE_ROOT / protected).resolve()
            if resolved == target or target in resolved.parents:
                raise ConfinementError("Writes to PenkoPerry Harness's own sources are not allowed")
    return resolved


# ---------------------------------------------------------------------------
# SSRF
# ---------------------------------------------------------------------------
_METADATA_HOSTS = {"metadata.google.internal", "metadata", "instance-data"}


class SSRFError(PermissionError):
    pass


def _ip_blocked(ip: ipaddress._BaseAddress) -> bool:
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 6 and ip in ipaddress.ip_network("fc00::/7"))
    )


def check_url(url: str, allow_domains: tuple[str, ...] = ()) -> str:
    """Validate an outbound URL; raises SSRFError. Returns the (unchanged) URL."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise SSRFError("Only http and https URLs are allowed")
    if parts.username or parts.password:
        raise SSRFError("URLs with credentials are not allowed")
    host = (parts.hostname or "").lower()
    if not host or host in _METADATA_HOSTS:
        raise SSRFError("Blocked host")
    if allow_domains and not any(host == d or host.endswith("." + d) for d in allow_domains):
        raise SSRFError("Host is not in the allowed domain list")
    try:
        literal = ipaddress.ip_address(host)
        infos = [literal]
    except ValueError:
        try:
            infos = [
                ipaddress.ip_address(i[4][0])
                for i in socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
            ]
        except socket.gaierror as error:
            raise SSRFError(f"Cannot resolve host: {host}") from error
    if any(_ip_blocked(ip) for ip in infos):
        raise SSRFError("Host resolves to a private, loopback or link-local address")
    return url


# ---------------------------------------------------------------------------
# Environment filtering
# ---------------------------------------------------------------------------
_SECRET_ENV = re.compile(
    r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|AUTH)", re.IGNORECASE
)


def safe_env(extra_allow: tuple[str, ...] = (), extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for child processes: drops anything that looks like a secret and VAULT_*."""
    env = {}
    for name, value in os.environ.items():
        if name in extra_allow:
            env[name] = value
        elif name.startswith(("VAULT_", "HARNESS_", "PENKO_")) or _SECRET_ENV.search(name):
            continue
        else:
            env[name] = value
    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------------------
# Shell command classifier
# ---------------------------------------------------------------------------
HARD_DENY = [
    r"\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*r)[a-zA-Z]*\s+(/|~|\$HOME|\*)(\s|$)",
    r"\brm\s+-[a-zA-Z]*\s+--no-preserve-root",
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\s+[^|;&]*\bof=/dev/",
    r":\(\)\s*\{\s*:\|:&\s*\};:",
    r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b",
    r"\bchmod\s+-R\s+0?777\s+/(\s|$)",
    r"\b(shutdown|reboot|halt|poweroff)\b",
    r"\bterraform\s+destroy\b",
    r"\bkubectl\s+delete\s+(ns|namespace)\b",
    r"\bdrop\s+(table|database)\b",
    r">\s*/dev/sd[a-z]",
    r"\bgit\s+push\b(?=[^|;&]*(--force|\s-f\b))(?=[^|;&]*\b(main|master)\b)",
    r"--no-verify",
]
_HARD_DENY_RE = [re.compile(p, re.IGNORECASE) for p in HARD_DENY]

READ_ONLY_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "grep", "rg", "find", "stat", "file",
    "du", "df", "date", "whoami", "id", "uname", "env", "printenv", "which", "type", "sort",
    "uniq", "cut", "tr", "diff", "basename", "dirname", "realpath", "tree", "true", "false",
    "jq", "yq", "sed", "awk", "test", "[",
}
READ_ONLY_SUBCOMMANDS = {
    "git": {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files", "remote", "blame"},
    "kubectl": {"get", "describe", "logs", "top", "version", "api-resources", "explain", "config"},
    "docker": {"ps", "images", "logs", "inspect", "version"},
    "argocd": {"app"},
    "pip": {"list", "show", "freeze"},
    "python": set(),
}
_SPLIT_RE = re.compile(r"\|\||&&|;|\||\n")
_DANGEROUS_FIND = {"-exec", "-execdir", "-delete", "-ok", "-fprint"}


def _segment_tier(segment: str) -> RiskTier:
    segment = segment.strip()
    if not segment:
        return RiskTier.R0
    if re.search(r"\$\(|`|<\(|>\s*[^&]|>>", segment):
        return RiskTier.R2
    try:
        words = shlex.split(segment)
    except ValueError:
        return RiskTier.R2
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    if not words:
        return RiskTier.R0
    cmd = os.path.basename(words[0])
    if cmd == "find" and any(w in _DANGEROUS_FIND for w in words):
        return RiskTier.R2
    if cmd in {"sed", "awk"} and any(w.startswith("-i") for w in words[1:]):
        return RiskTier.R2
    if cmd in {"env", "printenv"}:
        return RiskTier.R2  # would print secrets from the harness environment
    if cmd in READ_ONLY_SUBCOMMANDS:
        sub = next((w for w in words[1:] if not w.startswith("-")), "")
        if sub in READ_ONLY_SUBCOMMANDS[cmd]:
            if cmd == "argocd" and any(w in {"sync", "delete", "rollback", "set", "create"} for w in words):
                return RiskTier.R2
            if cmd == "git" and sub == "branch" and any(w in {"-D", "-d", "-m", "-M"} for w in words):
                return RiskTier.R2
            return RiskTier.R0
        return RiskTier.R2
    if cmd in READ_ONLY_COMMANDS:
        return RiskTier.R0
    return RiskTier.R2


def classify_command(command: str) -> RiskTier:
    """R4 for hard-blocked patterns, R0 for read-only pipelines, R2 (ask) otherwise."""
    if any(p.search(command) for p in _HARD_DENY_RE):
        return RiskTier.R4
    tiers = [_segment_tier(s) for s in _SPLIT_RE.split(command)]
    return RiskTier.R2 if any(t is not RiskTier.R0 for t in tiers) else RiskTier.R0


def matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(value, p) for p in patterns)
