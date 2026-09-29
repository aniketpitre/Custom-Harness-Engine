"""Secret storage for `harness init`: the OS keyring when one is available, else a mode-600 file.

Secrets are the provider API keys, the API token, Telegram credentials and signing keys. With the keyring
store they are kept in the OS keychain (macOS Keychain, Windows Credential Locker, Secret Service/KWallet);
`$HARNESS_HOME/.env` then holds only non-secret settings plus `HARNESS_KEYRING_ITEMS`, the names to fetch.
There is deliberately no passphrase-encrypted file: it would have to be unlocked on every start, which
defeats a zero-config daemon. Headless machines (no keyring backend) use the mode-600 file.
"""
from __future__ import annotations

import re

SERVICE = "harness-engine"
ITEMS_VAR = "HARNESS_KEYRING_ITEMS"
_SECRET_NAME = re.compile(
    r"(_API_KEY|API_TOKENS?|_TOKEN|^HARNESS_WEBHOOK_SECRET|^HARNESS_RECEIPT_KEY|PASSWORD)$|^HARNESS_SECRET_",
    re.IGNORECASE)


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


def _module():
    try:
        import keyring

        return keyring
    except Exception:  # noqa: BLE001 - not installed / broken backend loading
        return None


def available() -> bool:
    """True when a real (non-null, non-failing) keyring backend can be used."""
    kr = _module()
    if kr is None:
        return False
    try:
        backend = kr.get_keyring()
        name = type(backend).__module__ + "." + type(backend).__name__
        if "fail" in name.lower() or "null" in name.lower():
            return False
        return getattr(backend, "priority", 1) > 0
    except Exception:  # noqa: BLE001
        return False


def backend_name() -> str:
    kr = _module()
    if kr is None:
        return "keyring not installed"
    try:
        return type(kr.get_keyring()).__name__
    except Exception:  # noqa: BLE001
        return "unavailable"


def get(name: str) -> str | None:
    kr = _module()
    if kr is None:
        return None
    try:
        return kr.get_password(SERVICE, name)
    except Exception:  # noqa: BLE001
        return None


def set_secret(name: str, value: str) -> None:
    kr = _module()
    if kr is None:
        raise RuntimeError('keyring is not installed: pip install "harness-engine[keyring]"')
    kr.set_password(SERVICE, name, value)
    if kr.get_password(SERVICE, name) != value:  # verify the write really happened
        raise RuntimeError("keyring did not store the secret")


def delete(name: str) -> bool:
    kr = _module()
    if kr is None:
        return False
    try:
        kr.delete_password(SERVICE, name)
        return True
    except Exception:  # noqa: BLE001
        return False
