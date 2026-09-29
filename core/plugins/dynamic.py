"""Self-written tools ("write_and_register_tool"), hardened.

* gated behind the SelfEdit capability and an R3 approval that shows the full source and hash
* names validated; source statically checked (import allowlist, no dunder access, no exec/eval/open,
  only imports / literals / function definitions at module level)
* every tool declares its own risk tier in TOOL_SCHEMA["x-risk"] (undeclared is rejected)
* executed in a subprocess with a filtered environment, resource limits and (when available)
  a bubblewrap network sandbox; the engine never imports the code
* each tool file is its own plugin: one bad file is quarantined and marked FAILED, the rest keep running
"""
from __future__ import annotations

import ast
import asyncio
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.safety import scan_text
from core.settings import settings
from core.tools import ToolSpec

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")
ALLOWED_IMPORTS = {"json", "re", "math", "datetime", "typing", "collections", "itertools", "functools",
                   "string", "textwrap", "hashlib", "base64", "decimal", "statistics", "csv", "uuid",
                   "random", "fractions", "operator", "enum", "dataclasses", "time", "html"}
FORBIDDEN_NAMES = {"exec", "eval", "compile", "__import__", "open", "input", "breakpoint", "globals",
                   "locals", "vars", "setattr", "delattr", "memoryview", "exit", "quit"}
RUNNER = Path(__file__).with_name("dyn_runner.py")


class ToolValidationError(ValueError):
    pass


def validate_source(name: str, code: str) -> dict[str, Any]:
    """Static checks. Returns the parsed TOOL_SCHEMA (with name and x-risk verified)."""
    if not NAME_RE.match(name):
        raise ToolValidationError("tool_name must match ^[a-z][a-z0-9_]{1,48}$")
    if len(code) > 50_000:
        raise ToolValidationError("source too large")
    findings = scan_text(code, allow=("external-url",))
    if findings:
        raise ToolValidationError(f"source rejected by content scan: {', '.join(findings)}")
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        raise ToolValidationError(f"syntax error: {error}") from error
    schema: dict[str, Any] | None = None
    has_execute = False
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    raise ToolValidationError(f"import not allowed: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                raise ToolValidationError(f"import not allowed: {node.module}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_execute = has_execute or node.name == "execute"
        elif isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except ValueError as error:
                raise ToolValidationError("module-level assignments must be literals") from error
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "TOOL_SCHEMA":
                schema = value
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstring
        else:
            raise ToolValidationError(f"top-level {type(node).__name__} statements are not allowed")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ToolValidationError(f"dunder attribute access is not allowed: {node.attr}")
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise ToolValidationError(f"use of {node.id} is not allowed")
    if not has_execute:
        raise ToolValidationError("source must define execute(args)")
    if not isinstance(schema, dict):
        raise ToolValidationError("source must define a literal TOOL_SCHEMA dict")
    fn = schema.get("function", schema)
    if fn.get("name") != name:
        raise ToolValidationError("TOOL_SCHEMA name must equal tool_name")
    risk = schema.get("x-risk") or fn.get("x-risk")
    if risk not in {"R0", "R1", "R2", "R3"}:
        raise ToolValidationError('TOOL_SCHEMA must declare "x-risk" as one of R0-R3')
    if not isinstance(fn.get("parameters"), dict):
        raise ToolValidationError("TOOL_SCHEMA must define parameters")
    return {"name": name, "description": fn.get("description", name), "parameters": fn["parameters"],
            "risk": RiskTier(risk)}


def _sandbox_argv(path: Path, workdir: str) -> list[str]:
    mode = settings().dynamic_sandbox
    base = [sys.executable, "-I", str(RUNNER), str(path)]
    if mode in {"auto", "bwrap"} and shutil.which("bwrap"):
        return ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--tmpfs", "/tmp", "--unshare-net",
                "--unshare-pid", "--die-with-parent", "--chdir", "/tmp", *base]
    if mode == "bwrap":
        raise RuntimeError("HARNESS_DYNAMIC_SANDBOX=bwrap but bubblewrap is not installed")
    return base


async def run_tool_file(path: Path, args: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="harness-dyn-") as workdir:
        proc = await asyncio.create_subprocess_exec(
            *_sandbox_argv(path, workdir), cwd=workdir, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                                             "PYTHONIOENCODING": "utf-8"},
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True)
        try:
            out, err = await asyncio.wait_for(proc.communicate(json.dumps(args).encode()), 30)
        except asyncio.TimeoutError:
            proc.kill()
            raise
        except asyncio.CancelledError:
            proc.kill()
            raise
    last = out.decode(errors="replace").strip().splitlines()[-1] if out.strip() else ""
    try:
        data = json.loads(last)
    except ValueError:
        raise RuntimeError(f"tool crashed: {err.decode(errors='replace')[-500:]}") from None
    if "error" in data:
        raise RuntimeError(data["error"])
    return str(data["result"])


class DynamicToolPlugin(Plugin):
    """One self-written tool file = one plugin."""

    def __init__(self, name: str, path: Path) -> None:
        self.name = f"dynamic:{name}"
        self.tool_name, self.path = name, path

    def register(self, ctx: PluginContext) -> None:
        meta = validate_source(self.tool_name, self.path.read_text(encoding="utf-8"))
        path = self.path

        async def handler(args: dict, run_ctx) -> str:
            return await run_tool_file(path, args)

        ctx.tool(ToolSpec(self.tool_name, meta["description"], meta["parameters"], handler,
                          capability="Dynamic", risk=meta["risk"], untrusted=True, timeout=45,
                          policy_tool="dynamic", policy_action=self.tool_name,
                          render=lambda a: f"dynamic tool {path.stem}({json.dumps(a)[:500]})"))


async def load_dynamic_tools(engine) -> None:
    """Load every stored tool as its own plugin. Invalid files are quarantined, not fatal."""
    directory = settings().dynamic_dir
    directory.mkdir(parents=True, exist_ok=True)
    for path in sorted(directory.glob("*.py")):
        name = path.stem
        try:
            record = await engine.plugins.load(DynamicToolPlugin(name, path))
            if record.state.value == "FAILED":
                raise ToolValidationError(record.error or "failed")
        except Exception:  # noqa: BLE001
            quarantine = directory / "quarantine"
            quarantine.mkdir(exist_ok=True)
            shutil.move(str(path), quarantine / path.name)


# -- the write_and_register_tool tool ---------------------------------------------------
def _hard_deny(args: dict) -> str | None:
    try:
        validate_source(args["tool_name"], args["python_code"])
    except ToolValidationError as error:
        return f"invalid tool source: {error}"
    return None


def _render(args: dict) -> str:
    code = args["python_code"]
    existing = settings().dynamic_dir / f"{args['tool_name']}.py"
    digest = hashlib.sha256(code.encode()).hexdigest()
    head = f"SELF-MODIFICATION: register tool '{args['tool_name']}'\nsha256: {digest}\n"
    if existing.exists():
        diff = "\n".join(difflib.unified_diff(existing.read_text().splitlines(), code.splitlines(),
                                               "current", "proposed", lineterm=""))
        return head + "DIFF against the registered version:\n" + diff[:3500]
    return head + "FULL SOURCE:\n" + code[:3500]


async def write_and_register(args: dict, ctx) -> str:
    name, code = args["tool_name"], args["python_code"]
    validate_source(name, code)  # re-validated at execution time
    directory = settings().dynamic_dir
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.py"
    tmp = path.with_suffix(".py.tmp")
    tmp.write_text(code, encoding="utf-8")
    old = path.read_text(encoding="utf-8") if path.exists() else None
    os.replace(tmp, path)
    try:
        record = await ctx.engine.plugins.load(DynamicToolPlugin(name, path))
        if record.state.value == "FAILED":
            raise ToolValidationError(record.error or "failed to load")
    except Exception:
        if old is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(old, encoding="utf-8")
        raise
    ctx.extras["refresh_tools"] = True
    return (f"Registered dynamic tool '{name}' (sha256 {hashlib.sha256(code.encode()).hexdigest()[:12]}). "
            "It is available on the next turn if your agent has the Dynamic capability.")


class SelfEditPlugin(Plugin):
    name = "selfedit"

    def register(self, ctx: PluginContext) -> None:
        ctx.tool(ToolSpec(
            "write_and_register_tool",
            "RISK R3: write a small pure-Python tool and register it. Source must define TOOL_SCHEMA (a literal "
            'dict including "x-risk": "R0".."R3") and execute(args). Runs sandboxed out-of-process; '
            "only a safe stdlib subset is importable. Requires human approval of the full source.",
            {"type": "object", "properties": {"tool_name": {"type": "string"}, "python_code": {"type": "string"}},
             "required": ["tool_name", "python_code"], "additionalProperties": False},
            write_and_register, capability="SelfEdit", risk=RiskTier.R3, hard_deny=_hard_deny, render=_render,
            policy_tool="harness", policy_action="write_and_register_tool", timeout=60))
