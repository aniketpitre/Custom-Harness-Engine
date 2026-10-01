"""OS-keyring secret storage: init, load, migration, rotation, doctor, and headless fallback."""
import os

import keyring
import pytest
from keyring.backend import KeyringBackend

from cli import doctor
from cli.main import main
from core import home, keystore


class MemoryKeyring(KeyringBackend):
    priority = 5

    def __init__(self):
        self.data = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.data:
            raise keyring.errors.PasswordDeleteError("missing")
        del self.data[(service, username)]


class BrokenWriteKeyring(MemoryKeyring):
    def set_password(self, service, username, password):
        pass  # silently drops the write, like a locked keychain


@pytest.fixture
def kr():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("HARNESS_MODEL", "HARNESS_API_TOKEN", "GROQ_API_KEY", "OPENAI_API_KEY", "HARNESS_KEYRING_ITEMS"):
        monkeypatch.delenv(k, raising=False)


def test_secret_name_classification():
    yes = ["GROQ_API_KEY", "OPENAI_API_KEY", "HARNESS_API_TOKEN", "HARNESS_API_TOKENS", "HARNESS_SECRET_TELEGRAM_BOT_TOKEN",
           "HARNESS_WEBHOOK_SECRET", "HARNESS_RECEIPT_KEY", "GITHUB_TOKEN", "DB_PASSWORD"]
    no = ["HARNESS_MODEL", "HARNESS_APPROVERS", "OPENAI_API_BASE", "HARNESS_TOKEN_BUDGET", "HARNESS_KEYRING_ITEMS",
          "HARNESS_MAX_TURNS", "HARNESS_SANDBOX"]
    assert all(keystore.is_secret_name(n) for n in yes)
    assert not any(keystore.is_secret_name(n) for n in no)


def test_available_only_for_a_real_backend(kr):
    assert keystore.available() is True and keystore.backend_name() == "MemoryKeyring"
    from keyring.backends.fail import Keyring as Fail

    keyring.set_keyring(Fail())
    assert keystore.available() is False


def test_init_stores_secrets_in_the_keyring_not_in_the_env_file(kr, capsys):
    assert main(["init", "-y", "--provider", "groq", "--api-key", "gsk-very-secret", "--model", "groq/m",
                 "--telegram-bot-token", "123:abc", "--telegram-chat-id", "42"]) == 0
    out = capsys.readouterr().out
    text = home.env_file().read_text()
    assert "gsk-very-secret" not in text and "123:abc" not in text and "PENKO_API_TOKEN=" not in text
    assert "PENKO_MODEL=groq/m" in text and "HARNESS_" not in text and "=42" not in text
    items = home.keyring_items()
    assert {"GROQ_API_KEY", "HARNESS_API_TOKEN", "HARNESS_SECRET_TELEGRAM_BOT_TOKEN"} <= set(items)
    assert kr.data[(keystore.SERVICE, "GROQ_API_KEY")] == "gsk-very-secret"
    assert len(kr.data[(keystore.SERVICE, "HARNESS_API_TOKEN")]) == 64
    assert "OS keyring (MemoryKeyring)" in out and "gsk-very-secret" not in out
    assert home.env_file().stat().st_mode & 0o777 == 0o600


def test_load_env_pulls_secrets_from_the_keyring_and_env_still_wins(kr, monkeypatch):
    main(["init", "-y", "--provider", "groq", "--api-key", "from-keyring"])
    for k in ("GROQ_API_KEY", "HARNESS_API_TOKEN", "HARNESS_MODEL"):
        os.environ.pop(k, None)
    home.load_env()
    assert os.environ["GROQ_API_KEY"] == "from-keyring" and len(os.environ["HARNESS_API_TOKEN"]) == 64
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    os.environ.pop("HARNESS_API_TOKEN")
    home.load_env()
    assert os.environ["GROQ_API_KEY"] == "from-env"                      # real environment wins
    from core.secrets import get_llm_key

    monkeypatch.setenv("GROQ_API_KEY", "from-keyring")
    assert get_llm_key("groq/x") == "from-keyring"                       # reaches the LLM layer


def test_token_command_reads_from_the_keyring(kr, capsys):
    main(["init", "-y", "--provider", "groq", "--api-key", "k"])
    capsys.readouterr()
    os.environ.pop("HARNESS_API_TOKEN", None)
    assert main(["token"]) == 0
    assert capsys.readouterr().out.strip() == kr.data[(keystore.SERVICE, "HARNESS_API_TOKEN")]


def test_rerun_keeps_token_and_migrates_a_file_install_into_the_keyring(kr, monkeypatch):
    main(["init", "-y", "--provider", "groq", "--api-key", "k1", "--secret-store", "file"])
    token = home._read_env_file()["HARNESS_API_TOKEN"]
    monkeypatch.delenv("HARNESS_API_TOKEN", raising=False)
    main(["init", "-y", "--provider", "groq", "--secret-store", "keyring"])
    text = home.env_file().read_text()
    assert token not in text and "k1" not in text
    assert kr.data[(keystore.SERVICE, "HARNESS_API_TOKEN")] == token and kr.data[(keystore.SERVICE, "GROQ_API_KEY")] == "k1"


def test_moving_back_to_the_file_brings_secrets_along(kr, monkeypatch):
    main(["init", "-y", "--provider", "groq", "--api-key", "k1", "--secret-store", "keyring"])
    token = kr.data[(keystore.SERVICE, "HARNESS_API_TOKEN")]
    monkeypatch.delenv("HARNESS_API_TOKEN", raising=False)
    main(["init", "-y", "--provider", "groq", "--secret-store", "file"])
    values = home._read_env_file()
    assert values["HARNESS_API_TOKEN"] == token and values["GROQ_API_KEY"] == "k1" and "HARNESS_KEYRING_ITEMS" not in values


def test_headless_machines_fall_back_to_the_file(capsys):
    """No keyring backend (containers, servers): auto picks the mode-600 file."""
    from keyring.backends.fail import Keyring as Fail

    previous = keyring.get_keyring()
    keyring.set_keyring(Fail())
    try:
        assert main(["init", "-y", "--provider", "groq", "--api-key", "k"]) == 0
        assert "GROQ_API_KEY=k" in home.env_file().read_text() and not home.keyring_items()
        assert main(["init", "-y", "--provider", "groq", "--secret-store", "keyring"]) == 2
        assert "No usable OS keyring" in capsys.readouterr().err
    finally:
        keyring.set_keyring(previous)


def test_a_keyring_that_silently_drops_writes_is_detected():
    previous = keyring.get_keyring()
    keyring.set_keyring(BrokenWriteKeyring())
    try:
        with pytest.raises(RuntimeError, match="did not store"):
            main(["init", "-y", "--provider", "groq", "--api-key", "k", "--secret-store", "keyring"])
        assert "GROQ_API_KEY" not in home.env_file().read_text() if home.env_file().exists() else True
    finally:
        keyring.set_keyring(previous)


def test_secret_set_list_delete(kr, capsys, monkeypatch):
    main(["init", "-y", "--provider", "groq", "--api-key", "old"])
    capsys.readouterr()
    monkeypatch.setenv("NEW_VALUE", "rotated")
    assert main(["secret", "set", "GROQ_API_KEY", "--from-env", "NEW_VALUE"]) == 0
    assert "OS keyring" in capsys.readouterr().out and kr.data[(keystore.SERVICE, "GROQ_API_KEY")] == "rotated"
    assert "rotated" not in home.env_file().read_text()
    assert main(["secret", "list"]) == 0
    listing = capsys.readouterr().out
    assert "GROQ_API_KEY" in listing and "keyring" in listing and "rotated" not in listing
    assert main(["secret", "delete", "GROQ_API_KEY"]) == 0
    assert (keystore.SERVICE, "GROQ_API_KEY") not in kr.data and "GROQ_API_KEY" not in home.keyring_items()
    assert main(["secret", "delete", "GROQ_API_KEY"]) == 1
    assert main(["secret", "set"]) == 2 and main(["secret", "set", "X", "--from-env", "NOPE"]) == 2


def test_secret_set_in_a_file_install_stays_in_the_file(capsys, monkeypatch):
    from keyring.backends.fail import Keyring as Fail

    previous = keyring.get_keyring()
    keyring.set_keyring(Fail())
    try:
        main(["init", "-y", "--provider", "groq", "--api-key", "old"])
        monkeypatch.setenv("V", "new")
        assert main(["secret", "set", "GROQ_API_KEY", "--from-env", "V"]) == 0
        assert "GROQ_API_KEY=new" in home.env_file().read_text()
        assert main(["secret", "delete", "GROQ_API_KEY"]) == 0 and "GROQ_API_KEY" not in home.env_file().read_text()
    finally:
        keyring.set_keyring(previous)


class TestDoctorSecretStore:
    def _check(self):
        return {c.name: c for c in doctor.collect()}["secret store"]

    def test_ok_with_keyring(self, kr):
        main(["init", "-y", "--provider", "groq", "--api-key", "k"])
        c = self._check()
        assert c.status == "ok" and "MemoryKeyring" in c.detail

    def test_missing_items_named_with_the_fix(self, kr):
        main(["init", "-y", "--provider", "groq", "--api-key", "k"])
        del kr.data[(keystore.SERVICE, "GROQ_API_KEY")]
        c = self._check()
        assert c.status == "fail" and "GROQ_API_KEY" in c.detail and "penko secret set GROQ_API_KEY" in c.fix

    def test_keyring_configured_but_unavailable(self, kr):
        from keyring.backends.fail import Keyring as Fail

        main(["init", "-y", "--provider", "groq", "--api-key", "k"])
        keyring.set_keyring(Fail())
        c = self._check()
        assert c.status == "fail" and "no keyring backend" in c.detail and "secret-store file" in c.fix

    def test_warns_when_secrets_sit_in_the_file_but_a_keyring_exists(self, kr):
        main(["init", "-y", "--provider", "groq", "--api-key", "k", "--secret-store", "file"])
        c = self._check()
        assert c.status == "warn" and "--secret-store keyring" in c.fix

    def test_file_store_is_ok_without_keyring(self):
        from keyring.backends.fail import Keyring as Fail

        previous = keyring.get_keyring()
        keyring.set_keyring(Fail())
        try:
            main(["init", "-y", "--provider", "groq", "--api-key", "k"])
            assert self._check().status == "ok"
        finally:
            keyring.set_keyring(previous)


def test_env_file_uses_penko_names_and_reads_older_files(monkeypatch):
    """The .env is written with PENKO_* names; a file with the older prefix still loads."""
    import os

    home.ensure_home()
    home.env_file().write_text("HARNESS_MODEL=old/model\nHARNESS_MAX_TURNS=7\nPENKO_MAX_TURNS=9\n")
    for k in ("HARNESS_MODEL", "HARNESS_MAX_TURNS"):
        monkeypatch.delenv(k, raising=False)
    home.load_env()
    assert os.environ["HARNESS_MODEL"] == "old/model" and os.environ["HARNESS_MAX_TURNS"] == "9"   # PENKO_ wins
    home.write_env({"HARNESS_APPROVERS": "cli:me"})
    text = home.env_file().read_text()
    assert "PENKO_MODEL=old/model" in text and "PENKO_APPROVERS=cli:me" in text and "HARNESS_" not in text


def test_penko_variables_in_the_shell_are_honoured(monkeypatch):
    import os

    from core import _apply_env_aliases
    from core.settings import settings

    monkeypatch.setenv("PENKO_MAX_TURNS", "4")
    _apply_env_aliases()
    assert settings().max_turns == 4
    monkeypatch.delenv("PENKO_MAX_TURNS")
    os.environ.pop("HARNESS_MAX_TURNS", None)


def test_default_home_is_dot_penko(monkeypatch, tmp_path):
    monkeypatch.delenv("HARNESS_HOME", raising=False)
    monkeypatch.delenv("PENKO_HOME", raising=False)
    monkeypatch.setattr(home.Path, "home", lambda: tmp_path)
    assert home.harness_home() == tmp_path / ".penko"
    (tmp_path / ".harness").mkdir()          # an existing older install keeps its data
    assert home.harness_home() == tmp_path / ".harness"
    (tmp_path / ".penko").mkdir()
    assert home.harness_home() == tmp_path / ".penko"
