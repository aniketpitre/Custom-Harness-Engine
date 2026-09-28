import sys
from pathlib import Path

DYNAMIC_PLUGINS_DIR = Path("core/plugins/dynamic")
for filepath in DYNAMIC_PLUGINS_DIR.glob("*.py"):
    if filepath.name == "__init__.py": continue
    print(filepath.read_text())
