"""Terminal theme ("skin") for the harness CLI: mascot, banner, colours, glyphs, DevOps spinner verbs.

Styling only ever appears on an interactive terminal. Piped or redirected output, `--json`, and anything a
script might parse stay plain, so receipts and the doctor JSON never contain escape codes. Built-in skins
live here (the default is `perry`, the Penko Perry platypus in deep pale green); drop a YAML file in
`$HARNESS_HOME/skins/<name>.yaml` to add your own (it inherits every key you leave out from `perry`). Choose one with `penko theme set NAME` or `HARNESS_THEME=NAME`.

Environment: NO_COLOR disables colour, HARNESS_COLOR=always|never|auto, HARNESS_ASCII=1 disables emoji,
HARNESS_PLAIN=1 disables all styling.
"""
from __future__ import annotations

import os
import random
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

RESET = "\033[0m"
_ANSI = {"perry": "38;5;72", "perry-pale": "38;5;151", "perry-deep": "38;5;29", "bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35",
         "cyan": "36", "white": "37", "orange": "38;5;208", "teal": "38;5;37", "forest": "38;5;71",
         "gold": "38;5;178", "slate": "38;5;103", "violet": "38;5;141", "crimson": "38;5;160"}

PLAIN_GLYPHS = {"ok": "✓", "warn": "!", "fail": "✗", "arrow": "→", "mascot": "", "approve": "?", "tool": ">",
                "deny": "x", "run": ">", "receipt": "", "secure": "", "R0": "", "R1": "", "R2": "", "R3": "", "R4": ""}
ASCII_GLYPHS = {**PLAIN_GLYPHS, "mascot": "*"}

BANNER_ART = (
    r"      ,-.      ",
    r"   \ (   ) /   ",
    r"  --(  o  )--  ",
    r"   / (   ) \   ",
    r"      `-'      ",
)


@dataclass(frozen=True)
class Skin:
    name: str = "helm"
    description: str = "Ship's wheel: calm blue, for operators"
    tagline: str = "policy-gated agents for DevOps"
    prompt: str = "Approve? [y]es / [s]ession / [N]o: "
    colors: dict = field(default_factory=lambda: {
        "brand": "cyan", "accent": "bold", "ok": "green", "warn": "yellow", "fail": "red", "dim": "dim"})
    glyphs: dict = field(default_factory=lambda: {
        "ok": "✅", "warn": "⚠️ ", "fail": "❌", "arrow": "➜", "mascot": "🛞", "approve": "🔐", "tool": "🔧",
        "deny": "⛔", "run": "🚀", "receipt": "🧾", "secure": "🛡️ ",
        "R0": "🟢", "R1": "🟡", "R2": "🟠", "R3": "🔴", "R4": "⛔"})
    verbs: tuple = ("reconciling", "rolling out", "draining nodes", "reading the logs", "tracing the request",
                    "diffing manifests", "checking rollout health", "linting the change", "warming the cache",
                    "verifying the result", "tightening the policy", "waiting on the pipeline")


HELM = Skin()


def _skin(name: str, description: str, tagline: str, brand: str, mascot: str, **glyphs: str) -> Skin:
    colors = {**HELM.colors, "brand": brand}
    return replace(HELM, name=name, description=description, tagline=tagline, colors=colors,
                   glyphs={**HELM.glyphs, "mascot": mascot, **glyphs})


PERRY = replace(
    HELM, name="perry", description="Penko Perry: deep pale green, the platypus (default)", tagline="policy-gated agents for DevOps",
    colors={**HELM.colors, "brand": "perry", "accent": "bold+perry-pale"},
    glyphs={**HELM.glyphs, "mascot": "🌿", "run": "🌿"},
    verbs=("paddling upstream", "reconciling", "rolling out", "sniffing the logs", "tracing the request",
           "diffing manifests", "checking rollout health", "diving for root causes", "verifying the result",
           "tightening the policy", "waiting on the pipeline"))

BUILTIN: dict[str, Skin] = {
    "perry": PERRY,
    "helm": HELM,
    "harbor": _skin("harbor", "Container ship: teal and gold, for release day", "ship it, safely", "teal", "🚢",
                    run="⚓"),
    "ember": _skin("ember", "Incident orange: for on-call shifts", "calm hands in a hot incident", "orange", "🔥",
                   run="🚒"),
    "forest": _skin("forest", "Green pipeline: easy on the eyes", "green builds, quiet pagers", "forest", "🌲",
                    run="🌱"),
    "midnight": _skin("midnight", "Violet night mode", "the pager can wait, the audit trail can't", "violet", "🌙"),
    "mono": Skin(name="mono", description="No colour, no emoji: for logs and screen readers",
                 tagline="policy-gated agents for DevOps",
                 colors={k: "" for k in HELM.colors}, glyphs=dict(PLAIN_GLYPHS)),
}


# -- discovery -------------------------------------------------------------------------------
def skins_dir() -> Path:
    from core.home import harness_home

    return harness_home() / "skins"


def _load_user_skin(name: str) -> Skin | None:
    path = skins_dir() / f"{name}.yaml"
    if not path.is_file():
        return None
    try:
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    base = BUILTIN.get(str(raw.get("extends", "perry")), PERRY)
    verbs = raw.get("verbs")
    return replace(
        base, name=name, description=str(raw.get("description", base.description)),
        tagline=str(raw.get("tagline", base.tagline)), prompt=str(raw.get("prompt", base.prompt)),
        colors={**base.colors, **{k: str(v) for k, v in (raw.get("colors") or {}).items()}},
        glyphs={**base.glyphs, **{k: str(v) for k, v in (raw.get("glyphs") or {}).items()}},
        verbs=tuple(str(v) for v in verbs) if isinstance(verbs, list) and verbs else base.verbs)


def available() -> dict[str, Skin]:
    found = dict(BUILTIN)
    if skins_dir().is_dir():
        for path in sorted(skins_dir().glob("*.yaml")):
            skin = _load_user_skin(path.stem)
            if skin:
                found[path.stem] = skin
    return found


def current_name() -> str:
    return os.environ.get("HARNESS_THEME", "").strip().lower() or "perry"


def current() -> Skin:
    name = current_name()
    return _load_user_skin(name) or BUILTIN.get(name, PERRY)


# -- capability detection -----------------------------------------------------------------------
def _is_tty(stream) -> bool:
    try:
        return bool(stream and stream.isatty())
    except (ValueError, OSError):
        return False


def styled(stream=None) -> bool:
    """Only interactive terminals get the theme; pipes, files and CI logs stay plain."""
    if os.environ.get("HARNESS_PLAIN"):
        return False
    return _is_tty(stream or sys.stdout)


def use_color(stream=None) -> bool:
    mode = os.environ.get("HARNESS_COLOR", "auto").lower()
    if mode == "never" or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    if mode == "always":
        return True
    return styled(stream)


def use_emoji(stream=None) -> bool:
    if os.environ.get("HARNESS_ASCII") or not styled(stream) or current_name() == "mono":
        return False
    enc = (getattr(stream or sys.stdout, "encoding", None) or "").lower()
    return "utf" in enc


# -- rendering -----------------------------------------------------------------------------------
def paint(text: str, role: str, stream=None, skin: Skin | None = None) -> str:
    skin = skin or current()
    spec = skin.colors.get(role, role)
    if not spec or not use_color(stream):
        return text
    codes = ";".join(_ANSI.get(part, "") for part in str(spec).replace("+", " ").split() if _ANSI.get(part))
    return f"\033[{codes}m{text}{RESET}" if codes else text


def glyph(name: str, stream=None) -> str:
    """The themed glyph on a UTF-8 terminal, an ASCII fallback with HARNESS_ASCII, the classic mark when piped."""
    if use_emoji(stream):
        return current().glyphs.get(name, "")
    if styled(stream) and os.environ.get("HARNESS_ASCII"):
        return ASCII_GLYPHS.get(name, "")
    return PLAIN_GLYPHS.get(name, "")


def status_mark(status: str, stream=None) -> str:
    """`ok` / `warn` / `fail` as a coloured themed mark."""
    role = {"ok": "ok", "warn": "warn", "fail": "fail"}.get(status, "dim")
    return paint(glyph(status, stream).strip() or "-", role, stream)


def risk_mark(tier: str, stream=None) -> str:
    return glyph(tier, stream) or tier


def verb() -> str:
    return random.choice(current().verbs)


def banner(version: str, stream=None) -> str:
    """The mascot with the product name, version and tagline. Empty when output is not a terminal."""
    from core import brand

    stream = stream or sys.stdout
    if not styled(stream):
        return ""
    skin = current()
    side = [f"{brand.NAME} {version}", skin.tagline, f"theme: {skin.name} · `{brand.COMMAND} --help`"]
    if skin.name in {"perry", "mono"} or skin.glyphs.get("mascot") == PERRY.glyphs["mascot"]:
        art = brand.terminal_art(color=use_color(stream) and skin.name != "mono")
        width = max(len(_strip(a)) for a in art)
        side = [""] + side
        lines = [a + " " * (width - len(_strip(a))) + "   "
                 + (paint(t, "accent", stream) if i == 1 else paint(t, "dim", stream) if i == 3 else t)
                 for i, (a, t) in enumerate(zip(art, side + [""] * len(art), strict=False))]
        return "\n".join(line.rstrip() for line in lines) + "\n"
    mascot = glyph("mascot", stream).strip()
    title = side[0] + (f" {mascot}" if mascot else "")
    side[0] = title
    lines = []
    for art, text in zip(BANNER_ART, side + [""] * len(BANNER_ART), strict=False):
        lines.append(paint(art, "brand", stream) + "  " + (paint(text, "accent", stream) if text == title else text))
    return "\n".join(lines) + "\n"


def _strip(text: str) -> str:
    import re

    return re.sub(r"\033\[[0-9;]*m", "", text)


def preview(skin: Skin, stream=None) -> str:
    """One sample of what a skin looks like, used by `penko theme list --preview`."""
    stream = stream or sys.stdout
    marks = " ".join(paint(skin.glyphs.get(k, "").strip() or k, role, stream, skin)
                     for k, role in (("ok", "ok"), ("warn", "warn"), ("fail", "fail")))
    return f"{paint(skin.glyphs.get('mascot', '').strip() or '*', 'brand', stream, skin)} {skin.name:<9} {marks}  {skin.description}"
