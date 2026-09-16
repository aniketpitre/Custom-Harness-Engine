import json
from typing import Any

from kubernetes import client, config

from core.secrets import get_secret
from domains.devops.tools._mcp import FastMCP


mcp = FastMCP("devops-kubectl")
_core_v1: client.CoreV1Api | None = None


def _get_core_v1() -> client.CoreV1Api:
    global _core_v1
    if _core_v1 is None:
        kubeconfig_path = get_secret("kubernetes", "kubeconfig_path")
        config.load_kube_config(config_file=kubeconfig_path)
        _core_v1 = client.CoreV1Api()
    return _core_v1


@mcp.tool()
def kubectl_get_pods(namespace: str) -> str:
    """Read-only: list pods and their phases in a namespace."""
    pods = _get_core_v1().list_namespaced_pod(namespace=namespace)
    return "\n".join(
        f"{pod.metadata.name}: {pod.status.phase}"
        for pod in pods.items
    ) or "<no pods>"


@mcp.tool()
def kubectl_describe_pod(namespace: str, pod_name: str) -> str:
    """Read-only: return the full Kubernetes object for a pod."""
    pod = _get_core_v1().read_namespaced_pod(name=pod_name, namespace=namespace)
    return json.dumps(pod.to_dict(), default=str, sort_keys=True)


@mcp.tool()
def kubectl_logs(namespace: str, pod_name: str, container: str | None = None) -> str:
    """Read-only: retrieve recent logs for a pod container."""
    kwargs: dict[str, Any] = {
        "name": pod_name,
        "namespace": namespace,
        "tail_lines": 200,
    }
    if container:
        kwargs["container"] = container
    return _get_core_v1().read_namespaced_pod_log(**kwargs)


if __name__ == "__main__":
    mcp.run()
