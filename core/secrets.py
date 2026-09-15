import os

import hvac


DEFAULT_VAULT_MOUNT_POINT = "harness-secrets"


def get_vault_client() -> hvac.Client:
    address = os.environ.get("VAULT_ADDR")
    token = os.environ.get("VAULT_TOKEN")
    if not address or not token:
        raise RuntimeError("VAULT_ADDR and VAULT_TOKEN must be set")

    client = hvac.Client(url=address, token=token)
    if not client.is_authenticated():
        raise RuntimeError("Vault authentication failed")
    return client


def get_secret(path: str, key: str) -> str:
    mount_point = os.environ.get("VAULT_MOUNT_POINT", DEFAULT_VAULT_MOUNT_POINT)
    response = get_vault_client().secrets.kv.v2.read_secret_version(
        path=path,
        mount_point=mount_point,
    )
    try:
        value = response["data"]["data"][key]
    except (KeyError, TypeError) as error:
        raise KeyError(f"Secret key not found: {path}/{key}") from error
    if not isinstance(value, str) or not value:
        raise ValueError(f"Secret value must be a non-empty string: {path}/{key}")
    return value