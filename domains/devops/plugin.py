"""DevOps domain plugin: kubectl, ArgoCD and GitOps tools with argument-aware risk."""
from __future__ import annotations

import fnmatch
import re

from core.plugins.base import Plugin, PluginContext
from core.primitives.policy import RiskTier
from core.settings import PROTECTED_NAMESPACES, settings
from core.tools import ToolSpec

_K8S_NAME = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")
_APP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _check_k8s(*names: str | None) -> None:
    for n in names:
        if n is not None and not _K8S_NAME.fullmatch(n):
            raise ValueError(f"Invalid Kubernetes name: {n!r}")


# -- handlers (sync; the registry runs them in a worker thread) -------------------------
def _get_pods(args: dict, ctx) -> str:
    from domains.devops.tools.kubectl_tools import kubectl_get_pods

    _check_k8s(args["namespace"])
    return kubectl_get_pods(args["namespace"])


def _describe(args: dict, ctx) -> str:
    from domains.devops.tools.kubectl_tools import kubectl_describe_pod

    _check_k8s(args["namespace"], args["pod_name"])
    return kubectl_describe_pod(args["namespace"], args["pod_name"])


def _logs(args: dict, ctx) -> str:
    from domains.devops.tools.kubectl_tools import kubectl_logs

    _check_k8s(args["namespace"], args["pod_name"], args.get("container"))
    return kubectl_logs(args["namespace"], args["pod_name"], args.get("container"))


def _app_list(args: dict, ctx) -> str:
    from domains.devops.tools.argocd_tools import argocd_app_list

    return argocd_app_list()


def _app_get(args: dict, ctx) -> str:
    from domains.devops.tools.argocd_tools import argocd_app_get

    _app(args["app_name"])
    return argocd_app_get(args["app_name"])


def _app(name: str) -> str:
    if not _APP_NAME.fullmatch(name):
        raise ValueError(f"Invalid application name: {name!r}")
    return name


def _restart(args: dict, ctx) -> str:
    from domains.devops.snapshots import pod_snapshot_after_restart
    from domains.devops.tools.kubectl_tools import kubectl_restart_pod

    ns, pod = args["namespace"], args["pod_name"]
    _check_k8s(ns, pod)
    result = kubectl_restart_pod(ns, pod)
    after = pod_snapshot_after_restart(ns, pod)
    if not after["ready"]:
        raise RuntimeError("Pod was deleted and recreated but did not return to Ready")
    return result


def _pod_pre(args: dict) -> dict:
    from domains.devops.snapshots import pod_snapshot

    return pod_snapshot(args["namespace"], args["pod_name"])


def _pod_post(args: dict) -> dict:
    from domains.devops.snapshots import pod_snapshot

    return pod_snapshot(args["namespace"], args["pod_name"])


def _sync(args: dict, ctx) -> str:
    from domains.devops.tools.argocd_tools import argocd_app_sync

    return argocd_app_sync(_app(args["app_name"]))


def _gitops(args: dict, ctx) -> str:
    from domains.devops.git_actions import create_change_pr

    return create_change_pr(**args)


# -- argument-aware risk ---------------------------------------------------------------
def restart_hard_deny(args: dict) -> str | None:
    return (f"namespace '{args['namespace']}' is protected" if args["namespace"] in PROTECTED_NAMESPACES
            else None)


def sync_risk(args: dict, ctx) -> RiskTier:
    """R2 only for apps explicitly listed as staging; everything else is treated as production."""
    staging = settings().staging_apps
    return RiskTier.R2 if any(fnmatch.fnmatch(args["app_name"], p) for p in staging) else RiskTier.R3


def gitops_hard_deny(args: dict) -> str | None:
    from domains.devops.git_actions import allowed_repo

    st = settings()
    if not allowed_repo(args["repo_path"], st.gitops_repos, st.workspace):
        return "repo_path is not in the GitOps repository allowlist (HARNESS_GITOPS_REPOS)"
    return None


def _render_gitops(a: dict) -> str:
    return (f"PR: {a['pr_title']}\nrepo: {a['repo_path']}  branch: {a['branch_name']}\nfile: {a['file_path']}\n"
            f"commit: {a['commit_message']}\n\n{a['pr_body'][:800]}\n\n--- new content ---\n{a['content'][:1500]}")


class DevOpsPlugin(Plugin):
    name = "devops"

    def register(self, ctx: PluginContext) -> None:
        read = dict(capability="DevOpsRead", risk=RiskTier.R0, read_only=True, parallel_safe=True)
        ns = {"namespace": {"type": "string"}}
        ctx.tool(ToolSpec("kubectl_get_pods", "List pod names and phases in a Kubernetes namespace.",
                          _obj(ns, ["namespace"]), _get_pods, policy_tool="kubectl", policy_action="get", **read))
        ctx.tool(ToolSpec("kubectl_describe_pod", "Read the full object for a Kubernetes pod.",
                          _obj({**ns, "pod_name": {"type": "string"}}, ["namespace", "pod_name"]), _describe,
                          untrusted=True, policy_tool="kubectl", policy_action="describe", **read))
        ctx.tool(ToolSpec("kubectl_logs", "Read the last 200 log lines of a pod.",
                          _obj({**ns, "pod_name": {"type": "string"}, "container": {"type": "string"}},
                               ["namespace", "pod_name"]), _logs, untrusted=True, output_limit=8000,
                          policy_tool="kubectl", policy_action="logs", **read))
        ctx.tool(ToolSpec("argocd_app_list", "List ArgoCD applications with sync and health status.",
                          _obj({}, []), _app_list, policy_tool="argocd", policy_action="app_list", **read))
        ctx.tool(ToolSpec("argocd_app_get", "Read details for one ArgoCD application.",
                          _obj({"app_name": {"type": "string"}}, ["app_name"]), _app_get, untrusted=True,
                          policy_tool="argocd", policy_action="app_get", **read))
        ctx.tool(ToolSpec(
            "kubectl_restart_pod", "Restart a pod by deleting it so its controller recreates it (protected "
            "namespaces are blocked). Requires approval.", _obj({**ns, "pod_name": {"type": "string"}},
                                                                  ["namespace", "pod_name"]),
            _restart, capability="DevOpsWrite", risk=RiskTier.R2, hard_deny=restart_hard_deny,
            snapshot=(_pod_pre, _pod_post), timeout=240, policy_tool="kubectl", policy_action="restart_pod",
            render=lambda a: f"kubectl restart pod {a['namespace']}/{a['pod_name']}"))
        ctx.tool(ToolSpec(
            "argocd_app_sync", "Sync an ArgoCD application. Apps not listed as staging are treated as "
            "production (R3, explicit approval).", _obj({"app_name": {"type": "string"}}, ["app_name"]),
            _sync, capability="DevOpsWrite", risk=sync_risk, policy_tool="argocd", policy_action="app_sync",
            render=lambda a: f"argocd sync {a['app_name']}"))
        ctx.tool(ToolSpec(
            "gitops_propose_change", "Propose a configuration change as a pull request instead of "
            "mutating the cluster. Requires approval.",
            _obj({k: {"type": "string"} for k in ("repo_path", "file_path", "content", "branch_name",
                                                  "commit_message", "pr_title", "pr_body")},
                 ["repo_path", "file_path", "content", "branch_name", "commit_message", "pr_title", "pr_body"]),
            _gitops, capability="DevOpsWrite", risk=RiskTier.R2, hard_deny=gitops_hard_deny, timeout=180,
            policy_tool="gitops", policy_action="propose_change", render=_render_gitops))
