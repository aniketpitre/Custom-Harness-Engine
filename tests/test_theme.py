"""The DevOps terminal theme: styled on a terminal, byte-for-byte plain when piped."""
import io
import json

import pytest

from cli.main import main
from core import theme
from core.home import ensure_home, load_env

pytestmark = pytest.mark.unit


class TTY(io.StringIO):
    encoding = "utf-8"

    def isatty(self):
        return True


@pytest.fixture
def tty(monkeypatch):
    out = TTY()
    monkeypatch.setattr(theme.sys, "stdout", out)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    return out


def test_piped_output_has_no_styling_at_all(capsys):
    assert theme.banner("1.0") == "" and theme.glyph("ok") == "✓" and theme.paint("x", "brand") == "x"
    assert main(["version"]) == 0
    out = capsys.readouterr().out
    assert "\033" not in out and out.startswith("penko-perry ")


def test_doctor_json_is_never_styled(tty, monkeypatch):
    monkeypatch.setattr(theme.sys, "stdout", tty)     # pytest re-installs its capture per phase
    main(["doctor", "--json"])
    text = tty.getvalue()
    assert "\033" not in text and json.loads(text)


def test_terminal_gets_banner_colour_and_emoji(tty):
    text = theme.banner("1.0", tty)
    assert "\033[38;5;65" in text and "▀" in text and "PenkoPerry Harness 1.0" in text      # the green pixel platypus
    assert "a custom harness engine for DevOps agents" in text
    assert theme.glyph("ok", tty) == "✅" and theme.risk_mark("R3", tty) == "🔴"


def test_no_color_and_ascii_switches(tty, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert "\033" not in theme.banner("1.0", tty)
    monkeypatch.setenv("HARNESS_ASCII", "1")
    assert theme.glyph("ok", tty) == "✓" and "🛞" not in theme.banner("1.0", tty)
    monkeypatch.delenv("HARNESS_ASCII")
    monkeypatch.setenv("HARNESS_PLAIN", "1")
    assert theme.banner("1.0", tty) == ""


def test_every_builtin_skin_is_complete_and_renders(tty):
    assert set(theme.BUILTIN) == {"perry", "helm", "harbor", "ember", "forest", "midnight", "mono"}
    assert theme.current_name() == "perry"
    for name, skin in theme.BUILTIN.items():
        assert set(skin.glyphs) >= set(theme.HELM.glyphs) and skin.verbs and skin.tagline, name
        assert skin.name in theme.preview(skin, tty)


def test_mono_skin_is_plain_even_on_a_terminal(tty, monkeypatch):
    monkeypatch.setenv("HARNESS_THEME", "mono")
    assert theme.glyph("ok", tty) == "✓" and "\033" not in theme.banner("1.0", tty)


def test_user_skin_inherits_missing_keys_and_can_be_selected(tty, monkeypatch):
    ensure_home()
    (theme.skins_dir()).mkdir(parents=True, exist_ok=True)
    (theme.skins_dir() / "acme.yaml").write_text(
        "extends: ember\ntagline: acme platform\ncolors: {brand: magenta}\nglyphs: {mascot: '🐝'}\nverbs: [buzzing]\n")
    assert "acme" in theme.available()
    monkeypatch.setenv("HARNESS_THEME", "acme")
    skin = theme.current()
    assert skin.tagline == "acme platform" and skin.glyphs["ok"] == "✅" and skin.verbs == ("buzzing",)
    assert "PenkoPerry Harness 1.0 🐝" in theme.banner("1.0", tty) and theme.verb() == "buzzing"


def test_broken_user_skin_is_ignored(monkeypatch):
    ensure_home()
    theme.skins_dir().mkdir(parents=True, exist_ok=True)
    (theme.skins_dir() / "bad.yaml").write_text("- just\n- a list\n")
    monkeypatch.setenv("HARNESS_THEME", "bad")
    assert theme.current().name == "perry" and "bad" not in theme.available()


def test_theme_set_persists_and_rejects_unknown(capsys):
    assert main(["theme", "set", "ember"]) == 0
    load_env(override=True)
    assert theme.current_name() == "ember"
    assert main(["theme", "set", "nope"]) == 2
    assert "Unknown theme" in capsys.readouterr().err
    assert main(["theme", "list"]) == 0 and "ember" in capsys.readouterr().out


def test_no_arguments_shows_the_banner_and_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage: penko" in out and "alias" in out


def test_doctor_uses_themed_marks_on_a_terminal(tty, monkeypatch):
    from cli.doctor import Check, render

    monkeypatch.setattr(theme.sys, "stdout", tty)
    text = render([Check("x", "ok", "fine"), Check("y", "fail", "bad", "do this")])
    assert "✅" in text and "❌" in text and "➜ do this" in text


def test_docs_reference_files_that_exist():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for doc in ("docs/OWASP_AGENTIC_MAPPING.md", "docs/ROADMAP.md"):
        text = (root / doc).read_text()
        for ref in re.findall(r"`((?:core|cli|domains|tests|\.github)/[\w./-]+\.(?:py|yml|yaml))`", text):
            assert (root / ref).exists(), f"{doc} mentions missing {ref}"


def test_brand_logo_files_match_the_pixel_grid():
    from pathlib import Path

    from core import brand

    root = Path(__file__).resolve().parent.parent
    assert (root / "core/ui/logo.svg").read_text() == brand.svg()
    assert (root / "docs/images/logo.svg").read_text() == brand.svg(pixel=16)
    assert (root / "docs/images/wordmark.svg").read_text() == brand.wordmark_svg()
    assert len({len(r) for r in brand.GRID}) == 1 and set("".join(brand.GRID)) <= set(brand.COLORS) | {"."}


def test_truecolor_terminals_get_the_exact_brand_green(monkeypatch):
    from core import brand

    monkeypatch.setenv("COLORTERM", "truecolor")
    assert "38;2;95;149;121" in "".join(brand.terminal_art(True))       # #5f9579
    monkeypatch.delenv("COLORTERM")
    assert "38;5;65" in "".join(brand.terminal_art(True))
