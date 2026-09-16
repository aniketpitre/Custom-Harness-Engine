from types import SimpleNamespace

import pytest

import core.secrets as secrets


class FakeVaultClient:
    def __init__(self, authenticated: bool = True, response: dict | None = None) -> None:
        self.authenticated = authenticated
        self.calls: list[dict[str, str]] = []
        self.secrets = SimpleNamespace(
            kv=SimpleNamespace(
                v2=SimpleNamespace(read_secret_version=self.read_secret_version)
            )
        )
        self.response = response or {"data": {"data": {"api_key": "secret-value"}}}

    def is_authenticated(self) -> bool:
        return self.authenticated

    def read_secret_version(self, **kwargs: str) -> dict:
        self.calls.append(kwargs)
        return self.response


def test_get_vault_client_requires_connection_environment(monkeypatch) -> None:
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="VAULT_ADDR and VAULT_TOKEN"):
        secrets.get_vault_client()


def test_get_vault_client_rejects_failed_authentication(monkeypatch) -> None:
    fake_client = FakeVaultClient(authenticated=False)
    monkeypatch.setenv("VAULT_ADDR", "http://vault.test:8200")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setattr(secrets.hvac, "Client", lambda **_: fake_client)

    with pytest.raises(RuntimeError, match="Vault authentication failed"):
        secrets.get_vault_client()


def test_get_secret_reads_configured_mount_and_returns_value(monkeypatch) -> None:
    fake_client = FakeVaultClient()
    monkeypatch.setenv("VAULT_ADDR", "http://vault.test:8200")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setenv("VAULT_MOUNT_POINT", "test-secrets")
    monkeypatch.setattr(secrets.hvac, "Client", lambda **_: fake_client)

    assert secrets.get_secret("groq", "api_key") == "secret-value"
    assert fake_client.calls == [
        {"path": "groq", "mount_point": "test-secrets"}
    ]


def test_get_secret_rejects_missing_key(monkeypatch) -> None:
    fake_client = FakeVaultClient(response={"data": {"data": {}}})
    monkeypatch.setenv("VAULT_ADDR", "http://vault.test:8200")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setattr(secrets.hvac, "Client", lambda **_: fake_client)

    with pytest.raises(KeyError, match="groq/missing"):
        secrets.get_secret("groq", "missing")


@pytest.mark.parametrize("value", [None, ""])
def test_get_secret_rejects_empty_values(monkeypatch, value) -> None:
    fake_client = FakeVaultClient(response={"data": {"data": {"api_key": value}}})
    monkeypatch.setenv("VAULT_ADDR", "http://vault.test:8200")
    monkeypatch.setenv("VAULT_TOKEN", "test-token")
    monkeypatch.setattr(secrets.hvac, "Client", lambda **_: fake_client)

    with pytest.raises(ValueError, match="non-empty string"):
        secrets.get_secret("groq", "api_key")