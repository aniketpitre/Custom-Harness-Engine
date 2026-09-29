"""SKILL.md discovery with progressive disclosure (level 0 index, level 1 body, level 2 files)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.confine import ENGINE_ROOT
from core.settings import settings

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    version: str = "0.1.0"
    authorship: str = "human-authored"


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, text[end + 4:].lstrip("\n")


def skill_dirs() -> list[Path]:
    dirs = sorted((ENGINE_ROOT / "domains").glob("*/skills"))
    dirs.append(settings().skills_dir)
    return [d for d in dirs if d.is_dir()]


def discover_skills(dirs: list[Path] | None = None) -> list[Skill]:
    found: dict[str, Skill] = {}
    for base in dirs if dirs is not None else skill_dirs():
        for path in sorted(base.glob("*/SKILL.md")):
            meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            name = meta.get("name") or path.parent.name
            if not NAME_RE.match(name):
                continue
            desc = meta.get("description") or next(
                (ln.strip("# ").strip() for ln in body.splitlines() if ln.strip()), name)
            found[name] = Skill(name, desc[:200], path, meta.get("version", "0.1.0"),
                                "agent-created" if meta.get("authorship") == "agent-created" else "human-authored")
    return sorted(found.values(), key=lambda s: s.name)


def get_skill(name: str, dirs: list[Path] | None = None) -> Skill | None:
    return next((s for s in discover_skills(dirs) if s.name == name), None)


def skills_index(skills: list[Skill], limit_chars: int = 3000) -> str:
    lines, used = [], 0
    for s in skills:
        line = f"- {s.name}: {s.description}"
        if used + len(line) > limit_chars:
            lines.append("- ... (more; call skills_list)")
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)
