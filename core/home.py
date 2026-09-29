"""The Harness home directory: per-user config, secrets file and data (default ~/.harness).

Layout:
  $HARNESS_HOME/.env            secrets and settings written by `harness init` (mode 600)
  $HARNESS_HOME/config/         user overrides: agents.yaml, settings.yaml, mcp.yaml, hooks.yaml
  $HARNESS_HOME/data/           SQLite database, spilled outputs, checkpoints, skills, dynamic tools

Config lookup order for `find_config(name)`: home -> ./config (working directory, for checkouts) ->
the defaults packaged with the wheel (core/defaults).
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"


def harness_home() -> Path:
    return Path(os.environ.get("HARNESS_HOME") or Path.home() / ".harness").expanduser()


def find_config(name: str) -> Path:
    for candidate in (harness_home() / "config" / name, Path("config") / name):
        if candidate.is_file():
            return candidate
    return DEFAULTS_DIR / name


def ensure_home() -> Path:
    home = harness_home()
    for sub in ("", "config", "data"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    try:
        home.chmod(0o700)
    except OSError:
        pass
    return home


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip().removeprefix("export ").strip()] = value
    return values


def env_file() -> Path:
    return harness_home() / ".env"


def load_env(override: bool = False) -> list[str]:
    """Load $HARNESS_HOME/.env into os.environ (real environment variables win). Returns keys set."""
    path = env_file()
    if not path.is_file():
        return []
    set_keys = []
    for key, value in parse_env(path.read_text(encoding="utf-8")).items():
        if override or key not in os.environ:
            os.environ[key] = value
            set_keys.append(key)
    return set_keys


def write_env(values: dict[str, str]) -> Path:
    """Merge `values` into the .env file (mode 600, atomic). Existing unrelated keys are preserved."""
    ensure_home()
    path = env_file()
    merged = parse_env(path.read_text(encoding="utf-8")) if path.is_file() else {}
    merged.update({k: v for k, v in values.items() if v is not None})
    body = "# Written by `harness init`. Keep private (mode 600).\n" + "".join(
        f"{k}={v}\n" for k, v in merged.items())
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(tmp, path)
    path.chmod(0o600)
    return path


def is_private(path: Path) -> bool:
    try:
        return not (path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))
    except OSError:
        return False
