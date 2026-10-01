"""The Penko Perry home directory: per-user config, secrets file and data (default ~/.penko, or $PENKO_HOME).

Layout:
  ~/.penko/.env            settings and secrets written by `penko init` (mode 600), as PENKO_* variables
  ~/.penko/config/         user overrides: agents.yaml, settings.yaml, mcp.yaml, hooks.yaml
  ~/.penko/data/           SQLite database, spilled outputs, checkpoints, skills, dynamic tools

Internally every setting is read through one canonical prefix (HARNESS_*); `.env` files are written with the
public PENKO_ prefix and both spellings are read, so older files keep working.

Config lookup order for `find_config(name)`: home -> ./config (working directory, for checkouts) ->
the defaults packaged with the wheel (core/defaults).
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

DEFAULTS_DIR = Path(__file__).resolve().parent / "defaults"


PUBLIC_PREFIX, INTERNAL_PREFIX = "PENKO_", "HARNESS_"


def public_name(key: str) -> str:
    """PENKO_X for an internal HARNESS_X setting name; other names (GROQ_API_KEY...) unchanged."""
    return PUBLIC_PREFIX + key[len(INTERNAL_PREFIX):] if key.startswith(INTERNAL_PREFIX) else key


def internal_name(key: str) -> str:
    return INTERNAL_PREFIX + key[len(PUBLIC_PREFIX):] if key.startswith(PUBLIC_PREFIX) else key


def harness_home() -> Path:
    explicit = os.environ.get("PENKO_HOME") or os.environ.get("HARNESS_HOME")
    if explicit:
        return Path(explicit).expanduser()
    home, legacy = Path.home() / ".penko", Path.home() / ".harness"
    return legacy if legacy.is_dir() and not home.exists() else home


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


def keyring_items(values: dict[str, str] | None = None) -> list[str]:
    from core.keystore import ITEMS_VAR

    raw = (values if values is not None else _read_env_file()).get(ITEMS_VAR, "")
    return [n.strip() for n in raw.split(",") if n.strip()]


def _read_env_file() -> dict[str, str]:
    """The .env with keys in their internal form (PENKO_X is read as HARNESS_X)."""
    path = env_file()
    raw = parse_env(path.read_text(encoding="utf-8")) if path.is_file() else {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if key.startswith(INTERNAL_PREFIX) and internal_name(public_name(key)) in out:
            continue          # the PENKO_ spelling wins over an older duplicate
        if internal_name(key) == "HARNESS_KEYRING_ITEMS":
            value = ",".join(internal_name(n.strip()) for n in value.split(",") if n.strip())
        out[internal_name(key)] = value
    return out


def load_env(override: bool = False) -> list[str]:
    """Load ~/.penko/.env, then any secrets kept in the OS keyring, into os.environ.

    Real environment variables always win (unless `override`). Returns the keys that were set."""
    from core import _apply_env_aliases, keystore

    _apply_env_aliases()
    file_values = _read_env_file()
    set_keys = []
    for key, value in file_values.items():
        if override or key not in os.environ:
            os.environ[key] = value
            set_keys.append(key)
    for name in keyring_items(file_values):
        if override or name not in os.environ:
            secret = keystore.get(name)
            if secret is not None:
                os.environ[name] = secret
                set_keys.append(name)
    return set_keys


def write_env(values: dict[str, str], store: str = "file") -> Path:
    """Persist settings. `store="keyring"` keeps secret-looking values in the OS keyring (verified by
    reading them back) and the rest in the mode-600 .env; `"file"` keeps everything in the .env.
    Existing unrelated keys are preserved; secrets are migrated between stores as requested."""
    from core import keystore

    ensure_home()
    merged = _read_env_file()
    merged.update({k: v for k, v in values.items() if v is not None})
    items = set(keyring_items(merged))
    if store == "keyring":
        for name in [n for n in merged if keystore.is_secret_name(n) and n != keystore.ITEMS_VAR]:
            keystore.set_secret(name, merged.pop(name))
            items.add(name)
        # secrets that already live in the keyring stay there
        merged[keystore.ITEMS_VAR] = ",".join(sorted(items))
    else:  # file: bring any keyring-held secrets back so the file is the single source
        for name in sorted(items):
            secret = keystore.get(name)
            if secret is not None and name not in merged:
                merged[name] = secret
        merged.pop(keystore.ITEMS_VAR, None)
    return _write_file(merged)


def _write_file(values: dict[str, str]) -> Path:
    """Atomically write the .env with mode 600."""
    path = env_file()
    def shown(key: str, value: str) -> str:
        if key == "HARNESS_KEYRING_ITEMS":
            value = ",".join(public_name(n) for n in value.split(",") if n)
        return f"{public_name(key)}={value}\n"

    body = "# Written by `penko init`. Keep private (mode 600).\n" + "".join(shown(k, v) for k, v in values.items())
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.replace(tmp, path)
    path.chmod(0o600)
    return path


def delete_secret(name: str) -> bool:
    """Remove a value from the .env and/or the keyring. Returns whether anything was removed."""
    from core import keystore

    name = internal_name(name)
    values = _read_env_file()
    items = set(keyring_items(values))
    removed = values.pop(name, None) is not None
    if name in items:
        items.discard(name)
        removed = keystore.delete(name) or removed
    if items:
        values[keystore.ITEMS_VAR] = ",".join(sorted(items))
    else:
        values.pop(keystore.ITEMS_VAR, None)
    if removed:
        _write_file(values)
        os.environ.pop(name, None)
        os.environ.pop(public_name(name), None)
    return removed


def is_private(path: Path) -> bool:
    try:
        return not (path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO))
    except OSError:
        return False
