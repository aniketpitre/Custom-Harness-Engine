"""Workspace-confined file tools: read_directory, read (paged), glob, grep, write, edit, read_spill."""
from __future__ import annotations

import fnmatch
import hashlib
import re
import shutil
import uuid
from pathlib import Path

from core.confine import DENY_PARTS, ConfinementError, resolve_workspace_path
from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.settings import settings
from core.tools import ToolSpec

MAX_LINE = 2000
MAX_READ_BYTES = 5_000_000
MAX_GREP_FILE = 1_000_000


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _is_denied(path: Path) -> bool:
    return any(part in DENY_PARTS for part in path.parts) or path.name.startswith(".env")


def read_directory(args: dict, ctx) -> str:
    directory = resolve_workspace_path(args.get("path", "."))
    if not directory.is_dir():
        raise NotADirectoryError(args.get("path", "."))
    entries = [f"{'[dir]' if e.is_dir() else '[file]'} {e.name}"
               for e in sorted(directory.iterdir(), key=lambda e: e.name.lower())
               if e.name not in DENY_PARTS and not e.name.startswith(".env")]
    return "\n".join(entries) or "<empty directory>"


def read_file(args: dict, ctx) -> str:
    path = resolve_workspace_path(args["path"])
    if not path.is_file():
        raise FileNotFoundError(args["path"])
    if path.stat().st_size > MAX_READ_BYTES:
        raise ValueError("File is too large to read; use grep or read a range with a smaller file")
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        raise ValueError("Binary file")
    lines = data.decode("utf-8", errors="replace").splitlines()
    offset, limit = max(int(args.get("offset", 1)), 1), min(int(args.get("limit", 2000)), 2000)
    chunk = lines[offset - 1: offset - 1 + limit]
    body = "\n".join(f"{offset + i:>6}\t{ln[:MAX_LINE]}" for i, ln in enumerate(chunk))
    more = f"\n[showing lines {offset}-{offset + len(chunk) - 1} of {len(lines)}]" if len(lines) > limit or offset > 1 else ""
    return (body or "<empty file>") + more


def glob_files(args: dict, ctx) -> str:
    pattern = args["pattern"]
    if pattern.startswith(("/", "~")) or ".." in Path(pattern).parts:
        raise ConfinementError("Glob patterns must be relative to the workspace")
    root = settings().workspace
    out = []
    for p in root.glob(pattern):
        try:
            resolved = resolve_workspace_path(p)
        except ConfinementError:
            continue
        if not _is_denied(resolved.relative_to(root)):
            out.append(str(resolved.relative_to(root)))
        if len(out) >= 500:
            break
    return "\n".join(sorted(out)) or "No files matched."


def grep_files(args: dict, ctx) -> str:
    rx = re.compile(args["pattern"], re.IGNORECASE if args.get("ignore_case") else 0)
    base = resolve_workspace_path(args.get("path", "."))
    root = settings().workspace
    file_glob = args.get("glob")
    files = [base] if base.is_file() else base.rglob("*")
    hits: list[str] = []
    for f in files:
        try:
            if not f.is_file() or f.is_symlink() or _is_denied(f.relative_to(root)) or \
               any(p in {".git", "node_modules", "__pycache__", ".venv"} for p in f.parts):
                continue
            if file_glob and not fnmatch.fnmatch(f.name, file_glob):
                continue
            if f.stat().st_size > MAX_GREP_FILE:
                continue
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(root)}:{n}:{line[:300]}")
                    if len(hits) >= 200:
                        return "\n".join(hits) + "\n[truncated at 200 matches]"
        except (OSError, ValueError):
            continue
    return "\n".join(hits) or "No matches found."


# -- writes with checkpoints ----------------------------------------------------
def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def checkpoint_pre(args: dict) -> dict:
    path = resolve_workspace_path(args["path"], write=True)
    state: dict = {"path": str(path), "existed": path.is_file(), "sha256": _sha(path), "rollback": True}
    if path.is_file():
        backup_dir = settings().checkpoint_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{uuid.uuid4().hex}.bak"
        shutil.copy2(path, backup)
        state["backup"] = str(backup)
    return state


def checkpoint_post(args: dict) -> dict:
    path = resolve_workspace_path(args["path"], write=True)
    return {"path": str(path), "sha256": _sha(path)}


def restore_checkpoint(pre_state: dict) -> str:
    """Undo a write/edit from its recorded pre-state."""
    path = Path(pre_state["path"])
    resolve_workspace_path(path, write=True)
    if pre_state.get("existed"):
        shutil.copy2(pre_state["backup"], path)
        return f"Restored {path}"
    path.unlink(missing_ok=True)
    return f"Removed {path} (it did not exist before)"


def write_file(args: dict, ctx) -> str:
    path = resolve_workspace_path(args["path"], write=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"], encoding="utf-8")
    return f"File {args['path']} written ({len(args['content'])} chars)."


def edit_file(args: dict, ctx) -> str:
    path = resolve_workspace_path(args["path"], write=True)
    if not path.is_file():
        raise FileNotFoundError(args["path"])
    text, old, new = path.read_text(encoding="utf-8"), args["old_string"], args["new_string"]
    if not old:
        raise ValueError("old_string must not be empty")
    count = text.count(old)
    if count == 0:
        raise ValueError("old_string not found")
    if count > 1 and not args.get("replace_all"):
        raise ValueError(f"old_string is not unique ({count} matches); add context or set replace_all")
    path.write_text(text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1),
                    encoding="utf-8")
    return f"Edited {args['path']} ({count if args.get('replace_all') else 1} replacement)."


def read_spill(args: dict, ctx) -> str:
    spill = settings().spill_dir.resolve()
    path = Path(args["path"]).resolve()
    if spill not in path.parents:
        raise ConfinementError("Only spilled tool outputs can be read with read_spill")
    text = path.read_text(encoding="utf-8", errors="replace")
    offset, limit = max(int(args.get("offset", 0)), 0), min(int(args.get("limit", 6000)), 20000)
    return text[offset: offset + limit] + (f"\n[chars {offset}-{offset + limit} of {len(text)}]"
                                            if len(text) > offset + limit else "")


class FsPlugin(Plugin):
    name = "fs"

    def register(self, ctx: PluginContext) -> None:
        R = dict(capability="Read", risk=RiskTier.R0, read_only=True, parallel_safe=True)
        ctx.tool(ToolSpec("read_directory", "List entries in a directory inside the workspace.",
                          _obj({"path": {"type": "string", "description": "Relative path, '.' for the workspace root."}},
                               ["path"]), read_directory, policy_tool="filesystem",
                          policy_action="read_directory", **R))
        ctx.tool(ToolSpec("read", "Read a text file (paged, 2000 lines max per call).",
                          _obj({"path": {"type": "string"}, "offset": {"type": "integer", "minimum": 1},
                                "limit": {"type": "integer", "minimum": 1, "maximum": 2000}}, ["path"]),
                          read_file, policy_tool="filesystem", policy_action="read", **R))
        ctx.tool(ToolSpec("glob", "Find files by glob pattern relative to the workspace.",
                          _obj({"pattern": {"type": "string"}}, ["pattern"]), glob_files,
                          policy_tool="filesystem", policy_action="glob", **R))
        ctx.tool(ToolSpec("grep", "Search file contents with a regular expression (workspace only).",
                          _obj({"pattern": {"type": "string"}, "path": {"type": "string"},
                                "glob": {"type": "string"}, "ignore_case": {"type": "boolean"}}, ["pattern"]),
                          grep_files, policy_tool="filesystem", policy_action="grep", **R))
        ctx.tool(ToolSpec("read_spill", "Page through a truncated tool output saved to disk.",
                          _obj({"path": {"type": "string"}, "offset": {"type": "integer"},
                                "limit": {"type": "integer"}}, ["path"]), read_spill,
                          policy_tool="filesystem", policy_action="read_spill", **R))
        W = dict(capability="Write", risk=RiskTier.R1, snapshot=(checkpoint_pre, checkpoint_post),
                 policy_tool="filesystem")
        ctx.tool(ToolSpec("write", "Create or overwrite a file inside the workspace.",
                          _obj({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
                          write_file, policy_action="write",
                          render=lambda a: f"write {a['path']} ({len(a['content'])} chars)\n{a['content'][:1500]}", **W))
        ctx.tool(ToolSpec("edit", "Replace an exact string in a file (fails unless it is unique).",
                          _obj({"path": {"type": "string"}, "old_string": {"type": "string"},
                                "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}},
                               ["path", "old_string", "new_string"]), edit_file, policy_action="edit",
                          render=lambda a: f"edit {a['path']}\n- {a['old_string'][:600]}\n+ {a['new_string'][:600]}", **W))
