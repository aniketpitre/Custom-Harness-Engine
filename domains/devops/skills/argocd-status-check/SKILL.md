---
name: argocd-status-check
description: Inspect ArgoCD applications and Kubernetes pod health using read-only evidence.
---

# ArgoCD Status Check

Use this skill for goals about application sync state, deployment health, or cluster status.

## Procedure

1. Call `argocd_app_list` to enumerate applications and capture sync and health status.
2. For applications that are not Synced or Healthy, call `argocd_app_get` for details.
3. Identify the affected destination namespace and call `kubectl_get_pods` for pod phases.
4. For unhealthy or failed pods, call `kubectl_describe_pod` and then `kubectl_logs` when logs are relevant.
5. Report observed facts separately from hypotheses.
6. Do not execute restart, delete, sync, or other mutating actions during this check.
7. Cite the application, namespace, pod, and observed status in the final result.

## Completion Criteria

The check is complete only when each reported issue is supported by live ArgoCD or Kubernetes evidence, or is explicitly marked as unverified.
