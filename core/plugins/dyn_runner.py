"""Out-of-process runner for self-written tools. Run as: python -I dyn_runner.py <tool.py>

Reads a JSON object from stdin, imports the tool file, calls execute(args) (sync or async) and
prints one JSON line {"result": ...}. Resource limits are applied before the tool code is imported.
The engine never imports tool code in its own process.
"""
import asyncio
import importlib.util
import json
import sys


def _limits() -> None:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except Exception:  # noqa: BLE001 - best effort on platforms without rlimits
        pass


def main() -> None:
    _limits()
    path = sys.argv[1]
    args = json.loads(sys.stdin.read() or "{}")
    spec = importlib.util.spec_from_file_location("harness_dynamic_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.execute(args)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    sys.stdout.write("\n" + json.dumps({"result": result if isinstance(result, str) else json.dumps(result, default=str)}))


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:  # noqa: BLE001
        sys.stdout.write("\n" + json.dumps({"error": f"{type(error).__name__}: {error}"}))
        sys.exit(1)
