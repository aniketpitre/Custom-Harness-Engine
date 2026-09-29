"""The default plugin set. Domain packs load lazily: heavy imports happen inside handlers."""
from __future__ import annotations

from core.plugins.base import Plugin


def builtin_plugins() -> list[Plugin]:
    from core.plugins.advisor import AdvisorPlugin
    from core.plugins.dynamic import SelfEditPlugin
    from core.plugins.memory_tool import MemoryPlugin
    from core.plugins.skills_tool import SkillsPlugin
    from core.plugins.subagents_tool import SubagentsPlugin
    from domains.devops.plugin import DevOpsPlugin
    from domains.generic.fs import FsPlugin
    from domains.generic.shell import ShellPlugin
    from domains.generic.web import WebPlugin

    return [FsPlugin(), WebPlugin(), ShellPlugin(), MemoryPlugin(), SkillsPlugin(), AdvisorPlugin(),
            SubagentsPlugin(), SelfEditPlugin(), DevOpsPlugin()]
