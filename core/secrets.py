"""Secret provider chain: environment -> Vault, with one lazy client and a TTL cache."""
from __future__ import annotations

import os
import re
import threading
import time

DEFAULT_VAULT_MOUNT_POINT = "harness-secrets"
CACHE_TTL_SECONDS = 300

_lock = threading.Lock()
_client = None
_client_key: tuple[str, str] | None = None
_cache: dict[tuple[str, str, str], tuple[float, str]] = {}

_PROVIDER_ENV = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "nvidia_nim": "NVIDIA_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def clear_cache() -> None:
    global _client, _client_key
    with _lock:
        _cache.clear()
        _client = None
        _client_key = None


def get_vault_client():
    """Return one shared, authenticated hvac client (recreated if the env changes)."""
    global _client, _client_key
    address = os.environ.get("VAULT_ADDR")
    token = os.environ.get("VAULT_TOKEN")
    token_file = os.environ.get("VAULT_TOKEN_FILE")
    if not token and token_file and os.path.isfile(token_file):
        token = open(token_file, encoding="utf-8").read().strip()  # least-privilege token from init
    if not address or not token:
        raise RuntimeError("VAULT_ADDR and VAULT_TOKEN must be set")
    with _lock:
        if _client is not None and _client_key == (address, token):
            return _client
    import hvac

    client = hvac.Client(url=address, token=token)
    if not client.is_authenticated():
        raise RuntimeError("Vault authentication failed")
    with _lock:
        _client, _client_key = client, (address, token)
    return client


def _env_name(path: str, key: str) -> str:
    return "HARNESS_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", f"{path}_{key}").upper()


def _vault_read(path: str, key: str) -> str:
    mount_point = os.environ.get("VAULT_MOUNT_POINT", DEFAULT_VAULT_MOUNT_POINT)
    response = get_vault_client().secrets.kv.v2.read_secret_version(
        path=path, mount_point=mount_point
    )
    try:
        value = response["data"]["data"][key]
    except (KeyError, TypeError) as error:
        raise KeyError(f"Secret key not found: {path}/{key}") from error
    if not isinstance(value, str) or not value:
        raise ValueError(f"Secret value must be a non-empty string: {path}/{key}")
    return value


def get_secret(path: str, key: str) -> str:
    """Resolve a secret: env override (HARNESS_SECRET_<PATH>_<KEY>) first, then Vault."""
    override = os.environ.get(_env_name(path, key))
    if override:
        return override
    mount = os.environ.get("VAULT_MOUNT_POINT", DEFAULT_VAULT_MOUNT_POINT)
    cache_key = (mount, path, key)
    now = time.monotonic()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    value = _vault_read(path, key)
    _cache[cache_key] = (now, value)
    return value


def get_llm_key(model: str) -> str | None:
    """Per-model credentials. Returns None to let LiteLLM use its own env lookup."""
    provider = model.split("/", 1)[0].lower() if "/" in model else ""
    env_name = _PROVIDER_ENV.get(provider)
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    if provider and os.environ.get("HARNESS_LLM_API_KEY"):
        return os.environ["HARNESS_LLM_API_KEY"]
    try:
        stored_provider = get_secret("llm", "provider").lower()
        if not provider or stored_provider == provider or stored_provider in model.lower():
            return get_secret("llm", "api_key")
    except Exception:
        pass
    if provider == "groq":
        try:
            return get_secret("groq", "api_key")
        except Exception:
            return None
    return None
