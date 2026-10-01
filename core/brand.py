"""Penko Perry brand: name, colours and the pixel platypus.

One pixel grid is the single source for the SVG logo, the dashboard mark and the terminal banner, so they can
never drift apart. Regenerate the static logo files with `python -m core.brand` after changing the grid.
"""
from __future__ import annotations

NAME = "Penko Perry"
COMMAND = "penko"
TAGLINE = "policy-gated agents for DevOps"

# deep pale green palette
COLORS = {
    "B": "#5f9579",   # body: deep pale green
    "D": "#2f5c48",   # tail and feet: deep green
    "t": "#4a7d65",   # tail texture
    "N": "#26352e",   # duck bill: deep charcoal green
    "n": "#5a6b62",   # nostril
    "L": "#c4dfd0",   # belly: pale green
    "E": "#14231c",   # eye
    "W": "#ffffff",   # eye glint
}
BRAND_LIGHT = "#3d7a5f"   # UI accent on light surfaces (4.9:1 on #fcfcfb)
BRAND_DARK = "#7fbf9f"    # UI accent on dark surfaces

# side view, facing right: paddle tail on the left, duck bill on the right, webbed feet below
GRID = (
    "...........BBBBBBBBBB..........",
    ".........BBBBBBBBBBBBBB........",
    ".DDD....BBBBBBBBBBBBBBBB.......",
    "DDtDD..BBBBBBBBBBBBBBBWEB......",
    "DDDtDDBBBBBBBBBBBBBBBBEEBBNNNN.",
    "DDtDDDBBBBBBBBBBBBBBBBBBBNNnNNN",
    "DDDtD.BBLLLLLLLLLLLLLLBBBNNNNN.",
    ".DDD...BLLLLLLLLLLLLLLBB.......",
    "........DDD........DDD.........",
    ".......D.D.D......D.D.D........",
)


def svg(pixel: int = 10, pad: int = 1, title: str = NAME) -> str:
    """The logo as crisp pixel-art SVG."""
    w, h = len(GRID[0]) + 2 * pad, len(GRID) + 2 * pad
    rects = []
    for y, row in enumerate(GRID):
        x = 0
        while x < len(row):
            ch = row[x]
            if ch == ".":
                x += 1
                continue
            run = x
            while run < len(row) and row[run] == ch:
                run += 1
            rects.append(f'<rect x="{x + pad}" y="{y + pad}" width="{run - x}" height="1" fill="{COLORS[ch]}"/>')
            x = run
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w * pixel}" height="{h * pixel}" '
            f'shape-rendering="crispEdges" role="img" aria-label="{title}"><title>{title}</title>'
            + "".join(rects) + "</svg>")


def wordmark_svg() -> str:
    """Logo plus the name, for the README header."""
    mark = svg(pixel=1, pad=0)
    inner = mark[mark.index(">") + 1:mark.rindex("</svg>")].replace(f"<title>{NAME}</title>", "")
    gw, gh = len(GRID[0]), len(GRID)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {gw + 78} {gh + 2}" width="{(gw + 78) * 6}" '
            f'height="{(gh + 2) * 6}" role="img" aria-label="{NAME}"><title>{NAME}</title>'
            f'<g transform="translate(1 1)" shape-rendering="crispEdges">{inner}</g>'
            f'<text x="{gw + 5}" y="{gh - 1}" font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif" '
            f'font-size="8.4" font-weight="700" fill="{COLORS["D"]}">{NAME}</text></svg>')


# terminal colours (xterm-256) closest to the palette
ANSI = {"B": "38;5;65", "D": "38;5;23", "t": "38;5;29", "N": "38;5;236", "n": "38;5;242", "L": "38;5;151",
        "E": "38;5;234", "W": "38;5;231"}


def terminal_art(color: bool) -> list[str]:
    """The platypus in half-block characters: two pixel rows per text row, so it keeps its proportions."""
    rows = list(GRID) + (["." * len(GRID[0])] if len(GRID) % 2 else [])
    out = []
    for top, bottom in zip(rows[::2], rows[1::2], strict=True):
        line = []
        for a, b in zip(top, bottom, strict=True):
            if a == "." and b == ".":
                line.append(" ")
            elif not color:
                line.append("█" if a != "." and b != "." else ("▀" if a != "." else "▄"))
            elif a != "." and b != ".":
                fg, bg = _bg(a), _bg(b)
                line.append(f"\033[38;{fg};48;{bg}m▀\033[0m")
            elif a != ".":
                line.append(f"\033[38;{_bg(a)}m▀\033[0m")
            else:
                line.append(f"\033[38;{_bg(b)}m▄\033[0m")
        out.append("".join(line).rstrip())
    return out


def _bg(ch: str) -> str:
    """Colour spec for 38;…/48;…: exact 24-bit brand colour where the terminal supports it, else xterm-256."""
    import os

    if os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
        h = COLORS[ch].lstrip("#")
        return "2;" + ";".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    return "5;" + ANSI[ch].split(";")[-1]


if __name__ == "__main__":   # regenerate the static logo files
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    (root / "core" / "ui" / "logo.svg").write_text(svg(), encoding="utf-8")
    (root / "docs" / "images" / "logo.svg").write_text(svg(pixel=16), encoding="utf-8")
    (root / "docs" / "images" / "wordmark.svg").write_text(wordmark_svg(), encoding="utf-8")
    print("\n".join(terminal_art(True)))
