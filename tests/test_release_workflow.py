"""The release workflow is valid YAML and wired the way the README promises."""
import re
from pathlib import Path

import pytest
import yaml

import core

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent
WF = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
TRIGGER = WF.get("on") or WF.get(True)            # PyYAML reads the bare key `on` as True


def test_runs_only_on_version_tags():
    assert TRIGGER == {"push": {"tags": ["v*.*.*"]}}


def test_pypi_uses_trusted_publishing_not_a_stored_token():
    job = WF["jobs"]["pypi"]
    assert job["permissions"] == {"id-token": "write"} and job["environment"] == "pypi"
    text = (ROOT / ".github/workflows/release.yml").read_text()
    assert "PYPI_API_TOKEN" not in text and "password: ${{ secrets.PYPI" not in text


def test_image_is_multi_arch_and_pushed_to_ghcr():
    steps = WF["jobs"]["image"]["steps"]
    build = next(s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action"))
    assert build["with"]["platforms"] == "linux/amd64,linux/arm64" and build["with"]["push"] is True
    assert any(s.get("with", {}).get("registry") == "ghcr.io" for s in steps)


def test_publishing_waits_for_the_build_and_its_tests():
    assert WF["jobs"]["pypi"]["needs"] == "build" and WF["jobs"]["image"]["needs"] == "build"
    runs = " ".join(s.get("run", "") for s in WF["jobs"]["build"]["steps"])
    assert "pytest" in runs and "python -m build" in runs and "twine check" in runs


def test_the_version_check_script_reads_the_real_version():
    script = next(s["run"] for s in WF["jobs"]["build"]["steps"] if "package version" in s.get("name", ""))
    found = re.search(r'__version__ = "(.+?)"', (ROOT / "core/__init__.py").read_text()).group(1)
    assert found == core.__version__ and "GITHUB_REF_NAME" in script
