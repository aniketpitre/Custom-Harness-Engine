import json
import shutil
import subprocess

from domains.devops.tools._mcp import FastMCP


mcp = FastMCP("devops-argocd")


def _run_argocd(arguments: list[str]) -> str:
    if shutil.which("argocd") is None:
        raise RuntimeError("argocd CLI is not installed or is not on PATH")

    # Checkpoint specifies using --core since the API server is not exposed
    result = subprocess.run(
        ["argocd", "--core", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown argocd error"
        raise RuntimeError(message)
    return result.stdout


@mcp.tool()
def argocd_app_list() -> str:
    """Read-only: list ArgoCD applications as JSON."""
    output = _run_argocd(["app", "list", "--output", "json"])
    return json.dumps(json.loads(output), sort_keys=True)


@mcp.tool()
def argocd_app_get(app_name: str) -> str:
    """Read-only: inspect one ArgoCD application as JSON."""
    output = _run_argocd(["app", "get", app_name, "--output", "json"])
    return json.dumps(json.loads(output), sort_keys=True)


@mcp.tool()
def argocd_app_sync(app_name: str) -> str:
    """Action: sync one ArgoCD application."""
    output = _run_argocd(["app", "sync", app_name])
    return output

if __name__ == "__main__":
    mcp.run()
