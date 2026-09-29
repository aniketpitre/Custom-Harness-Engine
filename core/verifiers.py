"""Verifier registry: a run is only "verified" when an observable post-condition holds.

A spec is a dict with a `type` (default `file_content` for backward compatibility):
  file_content   {path, expected_content}
  http_probe     {url, expected_status?=200, contains?}
  command        {command, expected_exit?=0}   (read-only commands only)
  k8s_rollout    {namespace, name}             deployment or pod name
  argocd_health  {app_name}                    Synced + Healthy
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from core.primitives.verification import VerificationResult

Verifier = Callable[[dict[str, Any]], Awaitable[VerificationResult]]
_REGISTRY: dict[str, Verifier] = {}


def _result(expected: str, observed: str, passed: bool, method: str) -> VerificationResult:
    return VerificationResult(expected=expected, observed=observed, passed=passed, method=method,
                              checked_at=datetime.now(timezone.utc))


def register_verifier(name: str, fn: Verifier):
    _REGISTRY[name] = fn
    return lambda: _REGISTRY.pop(name, None)


def verifier_names() -> list[str]:
    return sorted(_REGISTRY)


async def run_verification(spec: dict[str, Any] | None) -> VerificationResult | None:
    if not spec:
        return None
    kind = spec.get("type") or ("file_content" if "path" in spec else None)
    fn = _REGISTRY.get(kind or "")
    if fn is None:
        return _result(str(spec), f"unknown verifier type: {kind!r}", False, "verifier_error")
    try:
        return await fn(spec)
    except Exception as error:  # noqa: BLE001 - a broken verifier is a failed verification
        return _result(str(spec), f"verifier error: {error}", False, kind or "verifier_error")


async def _file_content(spec):
    from core.verification import verify_file_content

    path, expected = spec.get("path"), spec.get("expected_content")
    if not isinstance(path, str) or not isinstance(expected, str):
        raise ValueError("Verification requires string path and expected_content")
    return await asyncio.to_thread(verify_file_content, path, expected)


async def _http_probe(spec):
    import httpx

    url, want = spec["url"], int(spec.get("expected_status", 200))
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        resp = await client.get(url)
    ok = resp.status_code == want and (spec.get("contains") in resp.text if spec.get("contains") else True)
    return _result(f"HTTP {want}", f"HTTP {resp.status_code}", ok, "http_probe")


async def _command(spec):
    from core.confine import classify_command, safe_env
    from core.primitives.policy import RiskTier

    command = spec["command"]
    if classify_command(command) is not RiskTier.R0:
        raise PermissionError("verification commands must be read-only")
    proc = await asyncio.create_subprocess_exec(
        "bash", "-c", command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env=safe_env())
    out, _ = await asyncio.wait_for(proc.communicate(), 60)
    want = int(spec.get("expected_exit", 0))
    return _result(f"exit {want}", f"exit {proc.returncode}: {out.decode(errors='replace')[:500]}",
                   proc.returncode == want, "command")


def _k8s_rollout_sync(spec):
    from kubernetes import client

    from domains.devops.tools.kubectl_tools import _get_core_v1

    ns, name = spec["namespace"], spec["name"]
    apps = client.AppsV1Api(_get_core_v1().api_client)
    try:
        d = apps.read_namespaced_deployment(name, ns)
        want, ready = d.spec.replicas or 0, d.status.ready_replicas or 0
        updated = d.status.updated_replicas or 0
        ok = ready >= want and updated >= want
        return _result(f"{want} ready replicas", f"{ready} ready, {updated} updated", ok, "k8s_rollout")
    except client.exceptions.ApiException as error:
        if error.status != 404:
            raise
    pod = _get_core_v1().read_namespaced_pod(name, ns)
    ready = any(c.type == "Ready" and c.status == "True" for c in (pod.status.conditions or []))
    return _result("pod Running and Ready", f"{pod.status.phase}, ready={ready}",
                   pod.status.phase == "Running" and ready, "k8s_rollout")


async def _k8s_rollout(spec):
    return await asyncio.to_thread(_k8s_rollout_sync, spec)


async def _argocd_health(spec):
    from domains.devops.tools.argocd_tools import argocd_app_get

    data = json.loads(await asyncio.to_thread(argocd_app_get, spec["app_name"]))
    status = data.get("status", {})
    sync, health = status.get("sync", {}).get("status"), status.get("health", {}).get("status")
    return _result("Synced/Healthy", f"{sync}/{health}", sync == "Synced" and health == "Healthy",
                   "argocd_health")


async def verify_with_agent(parent_ctx, claim: str) -> VerificationResult:
    """Independent verifier: a read-only subagent that has not seen the work checks the claim."""
    from core.subagents import run_subagent

    goal = ("You are an independent verifier. Using only read-only tools, check whether this claim is true "
            f"and supported by evidence:\n\n{claim}\n\nAnswer with PASS or FAIL on the first line, then "
            "one sentence of evidence.")
    caps = [c for c in ("Read", "DevOpsRead") if c in parent_ctx.allowed] or ["Read"]
    result = await run_subagent(parent_ctx, goal, capabilities=caps, label="verifier")
    text = (result.get("final_text") or "").strip()
    passed = result.get("status") == "success" and text.upper().startswith("PASS")
    return _result("PASS", text[:300] or result.get("error", "no verdict"), passed, "verifier_agent")


for _name, _fn in {"file_content": _file_content, "http_probe": _http_probe, "command": _command,
                   "k8s_rollout": _k8s_rollout, "argocd_health": _argocd_health}.items():
    register_verifier(_name, _fn)
