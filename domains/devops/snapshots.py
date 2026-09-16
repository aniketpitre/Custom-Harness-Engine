import time

from kubernetes import client

from domains.devops.tools.kubectl_tools import _get_core_v1


def pod_snapshot(namespace: str, pod_name: str) -> dict[str, object]:
    pod = _get_core_v1().read_namespaced_pod(name=pod_name, namespace=namespace)
    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "uid": pod.metadata.uid,
        "phase": pod.status.phase,
        "ready": _is_ready(pod),
        "resources": [
            container.resources.to_dict() if container.resources else None
            for container in pod.spec.containers
        ],
    }


def pod_snapshot_after_restart(
    namespace: str,
    pod_name: str,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            snapshot = pod_snapshot(namespace, pod_name)
            if snapshot["phase"] == "Running":
                return snapshot
        except client.exceptions.ApiException as error:
            last_error = error
        time.sleep(2)
    if last_error is not None:
        raise TimeoutError(f"Pod was not recreated before timeout: {last_error}") from last_error
    raise TimeoutError("Pod was not Running before timeout")


def rollback_pod_restart(
    namespace: str,
    pod_name: str,
    pre_state: dict[str, object],
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Confirm the controller restored the pod's pre-restart healthy condition."""
    post_state = pod_snapshot_after_restart(namespace, pod_name, timeout_seconds)
    if pre_state.get("phase") == "Running" and not post_state["ready"]:
        raise RuntimeError("Pod was recreated but did not return to Ready")
    return post_state


def _is_ready(pod: client.V1Pod) -> bool:
    return any(
        condition.type == "Ready" and condition.status == "True"
        for condition in (pod.status.conditions or [])
    )
