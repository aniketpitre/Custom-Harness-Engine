"""skills_list / skill_view (progressive disclosure) and skill_manage (approval-gated writes)."""
from __future__ import annotations

import shutil

from core.confine import ConfinementError
from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.safety import scan_text
from core.settings import settings
from core.skills import NAME_RE, discover_skills, get_skill, parse_frontmatter, skills_index
from core.tools import ToolSpec


def skills_list(args: dict, ctx) -> str:
    return skills_index(discover_skills(), 20000) or "No skills installed."


def skill_view(args: dict, ctx) -> str:
    skill = get_skill(args["name"])
    if skill is None:
        raise FileNotFoundError(f"Unknown skill: {args['name']}")
    ctx.extras.setdefault("skills_used", set()).add(skill.name)
    if args.get("path"):
        target = (skill.path.parent / args["path"]).resolve()
        if skill.path.parent.resolve() not in target.parents:
            raise ConfinementError("Skill files must be inside the skill directory")
        return target.read_text(encoding="utf-8")[:20000]
    return skill.path.read_text(encoding="utf-8")[:20000]


def _validate_skill(args: dict) -> str | None:
    name = args.get("name", "")
    if not NAME_RE.match(name):
        return "Skill name must be a lowercase hyphenated identifier"
    if args["action"] in {"create", "patch"}:
        body = args.get("content") or args.get("new_string") or ""
        findings = scan_text(body)
        if findings:
            return f"Skill content rejected by scan: {', '.join(findings)}"
    return None


def skill_manage(args: dict, ctx) -> str:
    st = settings()
    name, action = args["name"], args["action"]
    directory = st.skills_dir / name
    path = directory / "SKILL.md"
    if action == "create":
        if directory.exists() or get_skill(name):
            raise FileExistsError(f"Skill already exists: {name}")
        directory.mkdir(parents=True)
        meta = f"---\nname: {name}\ndescription: {args.get('description', name)}\nversion: 0.1.0\n" \
               "authorship: agent-created\n---\n\n"
        path.write_text(meta + args["content"] + "\n", encoding="utf-8")
        return f"Skill {name} created."
    if not path.exists():
        raise FileNotFoundError(f"Skill not found in the agent skills directory: {name}")
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    if meta.get("authorship") != "agent-created":
        raise PermissionError("Only agent-created skills can be modified")
    if action == "delete":
        shutil.rmtree(directory)
        return f"Skill {name} deleted."
    if action == "patch":
        old, new = args["old_string"], args["new_string"]
        if body.count(old) != 1:
            raise ValueError("old_string must match exactly once")
        text = path.read_text(encoding="utf-8").replace(old, new, 1)
        path.write_text(text, encoding="utf-8")
        return f"Skill {name} patched."
    raise ValueError(f"Unknown action: {action}")


class SkillsPlugin(Plugin):
    name = "skills"

    def register(self, ctx: PluginContext) -> None:
        read = dict(capability="Read", risk=RiskTier.R0, read_only=True, parallel_safe=True,
                    policy_tool="skills")
        ctx.tool(ToolSpec("skills_list", "List available skills (name and description).",
                          {"type": "object", "properties": {}, "additionalProperties": False},
                          skills_list, policy_action="list", **read))
        ctx.tool(ToolSpec("skill_view", "Load a skill's instructions (or one of its files).",
                          {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}},
                           "required": ["name"], "additionalProperties": False},
                          skill_view, policy_action="view", **read))
        ctx.tool(ToolSpec(
            "skill_manage", "Create, patch or delete an agent-created skill. Requires approval.",
            {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["create", "patch", "delete"]}, "name": {"type": "string"},
                "description": {"type": "string"}, "content": {"type": "string"},
                "old_string": {"type": "string"}, "new_string": {"type": "string"}},
             "required": ["action", "name"], "additionalProperties": False},
            skill_manage, capability="SkillsWrite", risk=RiskTier.R2,
            hard_deny=_validate_skill, policy_tool="skills", policy_action="manage",
            render=lambda a: f"skill {a['action']}: {a['name']}\n{(a.get('content') or a.get('new_string') or '')[:1500]}"))
