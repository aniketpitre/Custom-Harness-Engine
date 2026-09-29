"""The web dashboard: served by the API, locked down with CSP, and never trusted with data without the token."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.gateway import api

pytestmark = pytest.mark.unit
UI = Path(api.__file__).resolve().parent.parent / "ui"


@pytest.fixture
def client():
    with TestClient(api.app) as c:
        yield c


def test_page_and_assets_are_served_without_a_token(client):
    page = client.get("/ui")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert '<script src="/ui/app.js"' in page.text and "<script>" not in page.text   # no inline script
    assert client.get("/ui/app.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/ui/app.css").headers["content-type"].startswith("text/css")
    assert client.get("/ui/../settings.py").status_code == 404
    assert client.get("/ui/secrets.py").status_code == 404
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/ui"


def test_security_headers(client):
    h = client.get("/ui").headers
    csp = h["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp
    assert "unsafe-eval" not in csp and h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"


def test_data_still_needs_the_token(client):
    assert client.get("/sessions").status_code == 401
    assert client.get("/usage").status_code == 401


def test_the_client_only_calls_endpoints_that_exist():
    js = (UI / "app.js").read_text()
    paths = {p.split("?")[0].split("${")[0].rstrip("/") for p in re.findall(r'api\(\s*[`"](/[^`"]*)', js)}
    routes = {r.path for r in api.app.routes}
    for p in paths:
        assert any(route == p or route.startswith(p + "/") or route.startswith(p + "{") or route.split("/{")[0] == p
                   for route in routes), f"dashboard calls {p}, which the API does not serve"


def test_untrusted_text_goes_through_esc():
    """Agent output is untrusted: every interpolated payload field in the templates must be escaped."""
    js = (UI / "app.js").read_text()
    risky = re.findall(r"\$\{(p\.(?:content|raw_result|reason|summary|plan|error)|a\.rendered|s\.goal|r\.final_text)\}", js)
    assert risky == [], f"unescaped interpolation: {risky}"


def test_ui_files_ship_in_the_wheel():
    text = (Path(api.__file__).resolve().parents[2] / "pyproject.toml").read_text()
    assert '"ui/*"' in text


def test_dashboard_command(monkeypatch, capsys):
    from cli.main import main

    monkeypatch.setenv("HARNESS_API_PORT", "9123")
    assert main(["dashboard", "--print-url"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == "http://127.0.0.1:9123/ui" and "test-token" not in out
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    assert main(["dashboard"]) == 0
    assert opened == ["http://127.0.0.1:9123/ui#token=test-token"]     # fragment: never sent to a server
    monkeypatch.delenv("HARNESS_API_TOKEN")
    assert main(["dashboard"]) == 1
