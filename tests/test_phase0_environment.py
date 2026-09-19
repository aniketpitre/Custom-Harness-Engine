"""Phase 0: Environment and project setup — verify files and structure exist."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_toml_exists():
    assert (ROOT / "pyproject.toml").is_file()


def test_docker_compose_exists():
    assert (ROOT / "docker-compose.yml").is_file()


def test_env_example_exists():
    assert (ROOT / ".env.example").is_file()


def test_gitignore_excludes_env():
    gitignore = (ROOT / ".gitignore").read_text()
    assert ".env" in gitignore


def test_core_package_exists():
    assert (ROOT / "core" / "__init__.py").is_file()


def test_domains_package_exists():
    assert (ROOT / "domains" / "__init__.py").is_file()
