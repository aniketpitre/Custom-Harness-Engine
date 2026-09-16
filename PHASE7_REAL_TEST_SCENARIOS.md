# Phase 7 Real Infrastructure Test Scenarios

These scenarios test the Phase 7 read-only DevOps pack against real Kubernetes and ArgoCD services. They do not use mocks, fake clients, sample responses, or fabricated cluster state.

Run only against a disposable cluster or an explicitly approved non-production namespace.

## Preconditions

The operator must provide all of the following before running the scenarios:

- A reachable Kubernetes cluster.
- A kubeconfig path readable by the harness.
- A Vault instance with runtime access.
- The kubeconfig path stored in Vault at:

```text
harness-secrets/kubernetes/kubeconfig_path
```

- An installed and authenticated `argocd` CLI.
- An ArgoCD server with at least one accessible application.
- A Vault runtime environment in the terminal:

```bash
export VAULT_ADDR="..."
export VAULT_TOKEN="..."
export VAULT_MOUNT_POINT="harness-secrets"
```

Do not put real tokens in this file or in shell scripts.

## Preflight

Run these commands from the repository root. Every command must return real environment information.

```bash
kubectl version --client
kubectl cluster-info
kubectl get nodes -o wide
kubectl get namespaces
argocd version --client
argocd app list --output json
```

Verify the application can retrieve the kubeconfig path without printing the path or secret values:

```bash
python3 - <<'PY'
from core.secrets import get_secret

path = get_secret("kubernetes", "kubeconfig_path")
print(f"kubeconfig secret available: {bool(path)}")
PY
```

Stop if any preflight command fails. Do not replace a failed result with test data.

## Scenario 1: Real Kubernetes Pod Listing

**Purpose:** prove `kubectl_get_pods` reaches the real Kubernetes API and returns live pod state.

Choose a namespace that exists and is approved for read-only inspection:

```bash
export TEST_NAMESPACE="<approved-existing-namespace>"
kubectl get namespace "$TEST_NAMESPACE"
kubectl get pods -n "$TEST_NAMESPACE" -o wide
```

Run the harness tool:

```bash
python3 - <<'PY'
import os
from domains.devops.tools.kubectl_tools import kubectl_get_pods

result = kubectl_get_pods(os.environ["TEST_NAMESPACE"])
print(result)
PY
```

Acceptance:

- The namespace exists in the real cluster.
- The harness output corresponds to the live `kubectl get pods` result.
- No write operation occurs.
- An empty namespace is valid only if both the direct command and harness report no pods.

## Scenario 2: Real Pod Description

**Purpose:** prove the harness can inspect a real pod object.

Select a running pod from Scenario 1:

```bash
export TEST_POD="<approved-existing-pod>"
kubectl get pod "$TEST_POD" -n "$TEST_NAMESPACE" -o json
```

Run the harness tool:

```bash
python3 - <<'PY'
import os
from domains.devops.tools.kubectl_tools import kubectl_describe_pod

print(kubectl_describe_pod(os.environ["TEST_NAMESPACE"], os.environ["TEST_POD"]))
PY
```

Acceptance:

- The harness returns the live pod object as JSON.
- The returned object contains the same pod name and namespace as the direct command.
- No pod mutation, restart, or deletion occurs.

## Scenario 3: Real Pod Logs

**Purpose:** prove the harness can retrieve live read-only container logs.

Determine a container name from the real pod:

```bash
kubectl get pod "$TEST_POD" -n "$TEST_NAMESPACE" \
  -o jsonpath='{.spec.containers[0].name}'
```

Run the harness tool:

```bash
python3 - <<'PY'
import os
from domains.devops.tools.kubectl_tools import kubectl_logs

print(kubectl_logs(
    os.environ["TEST_NAMESPACE"],
    os.environ["TEST_POD"],
))
PY
```

Acceptance:

- The command returns logs or the same legitimate empty/no-log result as Kubernetes.
- The tool reads at most the configured recent log window.
- No write operation occurs.

## Scenario 4: Real ArgoCD Application List

**Purpose:** prove `argocd_app_list` reaches the authenticated ArgoCD server.

Run the direct CLI command:

```bash
argocd app list --output json > /tmp/argocd-apps.json
python3 - <<'PY'
import json
from pathlib import Path

applications = json.loads(Path("/tmp/argocd-apps.json").read_text())
print(f"real applications returned: {len(applications)}")
PY
```

Run the harness tool:

```bash
python3 - <<'PY'
import json
from domains.devops.tools.argocd_tools import argocd_app_list

applications = json.loads(argocd_app_list())
print(f"harness applications returned: {len(applications)}")
for application in applications:
    metadata = application.get("metadata", {})
    status = application.get("status", {})
    print(metadata.get("name"), status.get("sync", {}).get("status"), status.get("health", {}).get("status"))
PY
```

Acceptance:

- The harness reaches the real ArgoCD endpoint.
- The application count agrees with the direct CLI result.
- Reported sync and health values are live values.
- No sync, refresh, delete, or other mutation is requested.

## Scenario 5: Real ArgoCD Application Detail

**Purpose:** prove `argocd_app_get` retrieves a specific live application.

Select an application from Scenario 4:

```bash
export TEST_APP="<approved-existing-argocd-application>"
argocd app get "$TEST_APP" --output json > /tmp/argocd-app.json
```

Run the harness tool:

```bash
python3 - <<'PY'
import json
import os
from domains.devops.tools.argocd_tools import argocd_app_get

application = json.loads(argocd_app_get(os.environ["TEST_APP"]))
print(application["metadata"]["name"])
print(application.get("status", {}).get("sync", {}).get("status"))
print(application.get("status", {}).get("health", {}).get("status"))
PY
```

Acceptance:

- The returned application name equals `TEST_APP`.
- The harness status matches the direct CLI result.
- No ArgoCD mutation is performed.

## Scenario 6: Agent End-to-End Read-Only Investigation

**Purpose:** prove Goal -> Context -> Agent -> Policy -> real read-only tools -> ActionRecord -> RunReceipt.

Use a goal that requires live evidence:

```bash
python3 -m core.gateway.cli \
  "Inspect the real ArgoCD applications and Kubernetes pod health in the approved namespace, then report only observed sync, health, and pod states."
```

Acceptance:

- The model calls one or more real Phase 7 read tools.
- The output references live ArgoCD or Kubernetes observations.
- The JSON receipt contains one or more `actions` entries.
- Each action has an R0 `ALLOW` policy decision.
- No R2, R3, or R4 tool is called.
- The run performs no writes.

## Scenario 7: MCP Server Registration

**Purpose:** prove the MCP server definitions expose real tool metadata without executing a cluster mutation.

Run each server in a separate terminal and connect with an MCP inspector/client configured for the installed MCP version:

```bash
python3 -m domains.devops.tools.kubectl_tools
python3 -m domains.devops.tools.argocd_tools
```

Acceptance:

- The server starts without import or registration errors.
- The five read-only tools are discoverable.
- No write-capable tool is exposed by either server.
- Stop the server after discovery if the inspector does not manage its lifecycle.

## Scenario 8: Negative Safety Checks

These checks must fail safely and must use real tool boundaries:

1. Call `kubectl_get_pods` with a namespace that does not exist. Expected result: real Kubernetes not-found error.
2. Call `kubectl_describe_pod` with a pod name that does not exist. Expected result: real Kubernetes not-found error.
3. Call `argocd_app_get` with an application name that does not exist. Expected result: real ArgoCD error.
4. Confirm the tool modules contain no restart, delete, sync, apply, or shell-string execution path.

Do not convert any expected error into a passing result.

## Scenario 9: Receipt and Policy Evidence

After Scenario 6, inspect the receipt fields:

```text
run_id
model_used
actions[].tool
actions[].action
actions[].policy_decision.decision
actions[].policy_decision.risk_tier
actions[].raw_result
started_at
finished_at
```

Acceptance:

- Every executed read tool is represented by an `ActionRecord`.
- Every Phase 7 action has risk tier `R0`.
- Raw results contain evidence from the real tool call.
- The receipt does not claim verification or mutation that did not happen.

## Cleanup

The scenarios are read-only and should not create cluster resources. Remove only local artifacts generated for comparison:

```bash
rm -f /tmp/argocd-apps.json /tmp/argocd-app.json
unset TEST_NAMESPACE TEST_POD TEST_APP
```

If a disposable cluster was provisioned outside this repository, delete it using its provider’s documented cleanup command after the scenarios complete.

## Phase 7 Completion Rule

Phase 7 is complete only when Scenarios 1 through 6 and Scenario 9 pass against real Kubernetes and ArgoCD services. Import checks, unit tests, Docker builds, and unavailable-client messages are useful readiness checks but do not count as real-cluster acceptance.
