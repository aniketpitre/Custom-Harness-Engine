"""One settings object: environment > config/settings.yaml > defaults.

`settings()` is cheap and re-reads the environment on every call, so tests and
operators can change behaviour without restarting the process.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "groq/openai/gpt-oss-120b"
PROTECTED_NAMESPACES = ("kube-system", "kube-public", "kube-node-lease")


def _csv(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(p.strip() for p in os.getenv(name, default).split(",") if p.strip())


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def find_config(name: str) -> Path:
    """config/<name> in the working directory, else next to the installed sources."""
    local = Path("config") / name
    if local.exists():
        return local
    return Path(__file__).resolve().parent.parent / "config" / name


def _file_config() -> dict:
    path = Path(os.getenv("HARNESS_SETTINGS_FILE") or find_config("settings.yaml"))
    if not path.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    fallback_models: tuple[str, ...] = ()
    advisor_model: str | None = None
    compact_model: str | None = None
    db_path: Path = Path("data/memory.db")
    data_dir: Path = Path("data")
    workspace: Path = field(default_factory=Path.cwd)
    max_turns: int = 30
    token_budget: int = 200_000
    max_seconds: int = 3600
    context_window: int = 128_000
    reserve_tokens: int = 16_384
    keep_recent_tokens: int = 20_000
    llm_timeout: float = 120.0
    llm_retries: int = 3
    stream: bool = True
    max_parallel_tools: int = 6
    tool_timeout: float = 120.0
    tool_output_limit: int = 8_000
    approval_timeout: float = 300.0
    approvers: tuple[str, ...] = ()
    api_tokens: dict = field(default_factory=dict)
    api_rate_limit: int = 240
    gitops_repos: tuple[str, ...] = ()
    staging_apps: tuple[str, ...] = ()
    sandbox: str = "none"
    dynamic_sandbox: str = "auto"
    webhook_endpoints: tuple[str, ...] = ()
    webhook_secret: str | None = None
    web_allow_domains: tuple[str, ...] = ()
    memory_limit_chars: int = 2200
    memory_flush: bool = True
    otel_endpoint: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    max_subagents: int = 8
    subagent_timeout: float = 900.0
    heartbeat_file: str = "HEARTBEAT.md"
    stale_session_seconds: int = 0

    @property
    def spill_dir(self) -> Path:
        return self.data_dir / "spill"

    @property
    def dynamic_dir(self) -> Path:
        return self.data_dir / "dynamic_tools"

    @property
    def skills_dir(self) -> Path:
        return self.data_dir / "skills"

    @property
    def checkpoint_dir(self) -> Path:
        return self.data_dir / "checkpoints"


def _api_tokens() -> dict:
    tokens: dict[str, tuple[str, ...]] = {}
    single = os.getenv("HARNESS_API_TOKEN")
    if single:
        tokens[single] = ("*",)
    raw = os.getenv("HARNESS_API_TOKENS")
    if raw:
        # JSON: {"token": ["sessions:write", "sessions:read"]}
        try:
            for tok, scopes in json.loads(raw).items():
                tokens[str(tok)] = tuple(scopes)
        except (ValueError, AttributeError):
            pass
    return tokens


def settings() -> Settings:
    cfg = _file_config()
    model_cfg = cfg.get("model") or {}
    otel_cfg = cfg.get("otel") or {}
    db_path = Path(os.getenv("HARNESS_DB_PATH", "data/memory.db"))
    data_dir = Path(os.getenv("HARNESS_DATA_DIR", str(db_path.parent)))
    fallback = _csv("HARNESS_FALLBACK_MODELS") or tuple(
        m for m in [model_cfg.get("fallback")] if m
    )
    return Settings(
        model=os.getenv("HARNESS_MODEL") or model_cfg.get("primary") or DEFAULT_MODEL,
        fallback_models=fallback,
        advisor_model=os.getenv("HARNESS_ADVISOR_MODEL"),
        compact_model=os.getenv("HARNESS_COMPACT_MODEL"),
        db_path=db_path,
        data_dir=data_dir,
        workspace=Path(os.getenv("HARNESS_WORKSPACE", str(Path.cwd()))).resolve(),
        max_turns=_int("HARNESS_MAX_TURNS", 30),
        token_budget=_int("HARNESS_TOKEN_BUDGET", 200_000),
        max_seconds=_int("HARNESS_MAX_SECONDS", 3600),
        context_window=_int("HARNESS_CONTEXT_WINDOW", 128_000),
        reserve_tokens=_int("HARNESS_RESERVE_TOKENS", 16_384),
        keep_recent_tokens=_int("HARNESS_KEEP_RECENT_TOKENS", 20_000),
        llm_timeout=_float("HARNESS_LLM_TIMEOUT", 120.0),
        llm_retries=_int("HARNESS_LLM_RETRIES", 3),
        stream=_bool("HARNESS_STREAM", True),
        max_parallel_tools=_int("HARNESS_MAX_PARALLEL_TOOLS", 6),
        tool_timeout=_float("HARNESS_TOOL_TIMEOUT", 120.0),
        tool_output_limit=_int("HARNESS_TOOL_OUTPUT_LIMIT", 8_000),
        approval_timeout=_float("HARNESS_APPROVAL_TIMEOUT", 300.0),
        approvers=_csv("HARNESS_APPROVERS"),
        api_tokens=_api_tokens(),
        api_rate_limit=_int("HARNESS_API_RATE_LIMIT", 240),
        gitops_repos=_csv("HARNESS_GITOPS_REPOS"),
        staging_apps=_csv("HARNESS_STAGING_APPS"),
        sandbox=os.getenv("HARNESS_SANDBOX", "none"),
        dynamic_sandbox=os.getenv("HARNESS_DYNAMIC_SANDBOX", "auto"),
        webhook_endpoints=_csv("HARNESS_WEBHOOK_ENDPOINTS"),
        webhook_secret=os.getenv("HARNESS_WEBHOOK_SECRET"),
        web_allow_domains=_csv("HARNESS_WEB_ALLOW_DOMAINS"),
        memory_limit_chars=_int("HARNESS_MEMORY_LIMIT_CHARS", 2200),
        memory_flush=_bool("HARNESS_MEMORY_FLUSH", True),
        otel_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or otel_cfg.get("endpoint"),
        api_host=os.getenv("HARNESS_API_HOST", "127.0.0.1"),
        api_port=_int("HARNESS_API_PORT", 8000),
        max_subagents=_int("HARNESS_MAX_SUBAGENTS", 8),
        subagent_timeout=_float("HARNESS_SUBAGENT_TIMEOUT", 900.0),
        stale_session_seconds=_int("HARNESS_STALE_SESSION_SECONDS", 0),
    )
