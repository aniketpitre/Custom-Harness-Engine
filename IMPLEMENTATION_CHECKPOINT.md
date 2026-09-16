
# Custom Harness Engine Implementation Checkpoint

**Checkpoint date:** 2026-09-16
**Repository:** Custom-Harness-Engine
**Current branch:** main
**Python:** 3.14.2

This file is a handoff for another coding agent. Read it before changing the implementation. Preserve existing user changes and do not expose or commit secrets.

## Project Intent

This repository is building a general-purpose agent execution runtime with DevOps as the first domain pack:

```text
Goal -> Context -> Agent -> Policy -> Approval -> Execution -> Verification -> Receipt -> Learning -> Memory
```

The implementation sequence is documented in `harness-engine-implementation-plan.md`. The architecture is documented in `general_purpose_agent_harness_architecture.md`.

## Current Phase Status

### Phase 0: Environment and project setup

Complete enough for local development.

- Python 3.14, Node 24, Docker, and Git are available.
- `pyproject.toml` defines the project and dependencies.
- Docker Compose provides a development-only Vault instance.
- `.gitignore` excludes `.env`, `data/`, local secrets, bytecode, and build artifacts.
- `.env.example` contains placeholders for Vault, Groq, Telegram, and model configuration.

### Phase 1: Core primitives

Implemented and tested.

Files:

- `core/primitives/goal.py`
- `core/primitives/context.py`
- `core/primitives/evidence.py`
- `core/primitives/policy.py`
- `core/primitives/execution.py`
- `core/primitives/verification.py`
- `core/primitives/learning.py`
- `tests/core/test_primitives.py`
- `tests/core/test_policy.py`

Implemented concepts:

- Goal and trigger source.
- Context packet and evidence provenance.
- Risk tiers R0 through R4.
- Policy decisions: `ALLOW`, `REQUIRE_APPROVAL`, and `DENY`.
- Action records and run receipts, including checkpoint fields.
- Verification results.
- Candidate skill lifecycle: `pending_approval -> validated/rejected -> active`.

### Phase 2: Minimal agent loop

Implemented for the project-selected LiteLLM + Groq/Grok integration. The original implementation plan's Claude Agent SDK example is not the runtime target for this repository.

- `core/agent_engine.py` uses LiteLLM with the configured Groq model.
- The runtime supports a local `read_directory` function tool.
- `core/gateway/cli.py` creates a Goal, assembles Context from memory, runs the agent, and emits a JSON `RunReceipt`.
- Successful tool calls now return `ActionRecord` objects with policy metadata and raw results; CLI receipts include those actions.
- The runtime intentionally uses LiteLLM with the configured Groq/Grok model and Vault-provided API credentials.
- Live Groq CLI smoke validation passed on 2026-09-16 with Vault running and the configured credential.

### Phase 3: Verification

Core verifier implemented, wired into receipts, and tested through a live create-then-verify run.

- `core/verification.py` contains `verify_file_content`.
- `tests/core/test_verification.py` verifies matching content, mismatches, and missing files.
- Verification is wired into the normal agent result and CLI receipt when `handle_cli_input` receives an explicit verification request containing `path` and `expected_content`.
- Live acceptance passed on 2026-09-16: a real temporary file was created, the live Groq handler ran, and the receipt reported `status=success`, `verification_passed=true`, and `method=file_check`.

### Phase 4: Memory

Implemented and tested.

- `core/memory/store.py` provides SQLite FTS5 storage.
- Memory entries include authorship and provenance.
- Searches filter by domain and update `last_used_at` and `use_count`.
- `core/gateway/cli.py` includes matching memory entries in `ContextPacket.memory_hits`.
- `tests/core/test_memory_store.py` covers retrieval, domain filtering, limits, plain goal text, provenance constraints, and CLI context assembly.

### Phase 5: Vault secrets

Implemented, tested, and live-validated.

- `core/secrets.py` reads `VAULT_ADDR`, `VAULT_TOKEN`, and optional `VAULT_MOUNT_POINT` from the environment.
- Vault authentication is required before reading secrets.
- `get_secret(path, key)` reads KV v2 values and rejects missing or empty values.
- `docker/init-vault.sh` initializes `harness-secrets/groq` and `harness-secrets/telegram`.
- `docker-compose.yml` passes Telegram bootstrap values to `vault-init` and only Vault connection settings to the harness container.
- Vault access was validated through the live Docker/Vault path; no mock-based Vault test is retained in the repository.

Live validation performed:

- Started the local Vault container.
- Seeded the Groq API key and Telegram bot credentials.
- Retrieved `groq/api_key`, `telegram/bot_token`, and `telegram/approval_chat_id` through `core.secrets`.
- Secret values were never printed.
- Temporary Vault containers and data were removed after testing.

Important environment distinction:

- Compose uses `VAULT_DEV_ROOT_TOKEN_ID` to start the development Vault.
- Application code requires the runtime variable `VAULT_TOKEN`.
- For direct host testing, map `VAULT_TOKEN="$VAULT_DEV_ROOT_TOKEN_ID"` after loading `.env`.

### Phase 6: Policy and approval gate

Implementation complete for the available policy, Telegram, and R2 action paths. Live infrastructure acceptance remains pending.

Completed:

- `domains/devops/policy_table.py` contains R0 read-only entries, R2 restart/sync entries, R3 production sync, and R4 destructive entries.
- `resolve_policy` requires approval for R2/R3 and denies R4.
- `core/gateway/telegram.py` sends inline Approve/Deny buttons and records the Telegram user ID in memory.
- `build_approval_application` and `run_approval_bot` provide a Telegram polling application.
- A Telegram update-offset race was fixed: stale updates are drained before sending the approval message, then matching callbacks are polled using the captured offset.
- `kubectl_restart_pod` is implemented as a real Kubernetes API action and is exposed to the agent as an R2 `DevOpsWrite` tool.
- Policy is resolved before the R2 action executes.
- Successful approved actions carry the Telegram approver ID in `PolicyDecision.approved_by` and `ActionRecord.approved_by`.

Live acceptance performed without mocks:

1. A real Telegram R3 request was approved. No infrastructure action was attached to that request.
2. A second real Telegram R3 request was denied.
3. The attached safe local no-op did not execute:

```text
LIVE_APPROVAL_RESULT=DENIED
SAFE_NOOP_EXECUTED=false
```

Live tests completed:

- Real Telegram approval completed successfully.
- Real Telegram denial completed successfully and prevented the attached safe no-op.
- Policy resolution for R2/R3 actions was verified.

Remaining:

- Run `kubectl_restart_pod` against a real approved non-critical pod, approve it through Telegram, verify the pod is recreated, and verify the R2 `ALLOW` action records the Telegram user ID.
- Implement or connect a real R3 action before claiming R3 acceptance; currently only the R2 restart action is executable.
- Consolidate the direct polling path and application callback path in the Telegram gateway.
- Do not run the live mutation against production.

### Phase 7: DevOps read-only domain pack

Implementation complete; real-cluster acceptance remains pending environment access.

Added:

- `domains/devops/tools/_mcp.py`: compatibility import for MCP v1 `FastMCP` and installed MCP v2 `MCPServer`.
- `domains/devops/tools/kubectl_tools.py`: lazy Vault-backed Kubernetes client with `kubectl_get_pods`, `kubectl_describe_pod`, and `kubectl_logs`.
- `domains/devops/tools/argocd_tools.py`: subprocess-based, argument-list-only ArgoCD wrapper with `argocd_app_list` and `argocd_app_get`.
- `domains/devops/skills/argocd-status-check/SKILL.md`: read-only procedure for correlating ArgoCD application state with Kubernetes pod evidence.

Runtime wiring:

- `core/agent_engine.py` advertises and dispatches the five read-only tools.
- Every DevOps tool resolves through the existing R0 policy table before execution.
- `core/gateway/cli.py` grants CLI runs the `DevOpsRead` capability.
- Kubernetes configuration is loaded lazily from the Vault secret `kubernetes/kubeconfig_path`.
- ArgoCD commands cannot execute shell strings and have a 30-second timeout.

Completed:

- All five tool schemas imported successfully.
- Both MCP servers imported successfully under the installed MCP v2 package.
- Python compilation passed.
- The five tools are registered in the agent and use R0 policy checks.
- Action records are generated for successful read-only tool calls.
- `PHASE7_REAL_TEST_SCENARIOS.md` documents the live acceptance procedure.
- The repository suite currently passes: `29 passed`.

Real preflight retest performed afterward:

- `kubectl version --client` succeeded with client version `v1.37.0`.
- `kubectl cluster-info` and `kubectl get namespaces` attempted the real default endpoint and received connection refused from `localhost:8080`.
- The `argocd` CLI was not installed or available on `PATH`.
- Direct Python tool execution reported the real missing ArgoCD executable and missing Vault runtime variables rather than returning fabricated cluster data.
- Attempted to provision a real disposable Minikube cluster with Docker and then with containerd; both control-plane startup paths failed in this dev container because the Minikube node SSH/control-plane lifecycle could not be maintained.
- The failed disposable cluster was deleted and no broken Minikube container or active kubeconfig was left behind.
- The Phase 7.5 acceptance is therefore still blocked and is not marked complete.

Remaining:

- `kubectl` client is installed, but `$HOME/.kube/config` contains no usable clusters, users, or current context.
- `argocd` is not installed or available on `PATH`.
- A disposable local cluster cannot currently be provisioned with Minikube in this Docker-in-container environment.
- Provide a real kubeconfig through Vault at `kubernetes/kubeconfig_path`.
- Install and authenticate the ArgoCD CLI or connect an authenticated ArgoCD API client.
- Run real Kubernetes scenarios 1-3, ArgoCD scenarios 4-5, agent scenario 6, and receipt scenario 9 from `PHASE7_REAL_TEST_SCENARIOS.md`.
- Do not claim Phase 7.5 completion until those scenarios pass against real services.

Pending real Phase 7 acceptance test:

- The real test scenario suite is documented in `PHASE7_REAL_TEST_SCENARIOS.md`.
- A real preflight was attempted on 2026-09-16. The kubeconfig file existed but contained no clusters, users, or contexts; `kubectl` therefore fell back to `localhost:8080` and was refused. The file is still present but unusable.
- Minikube was attempted with Docker and containerd, but the control plane could not remain healthy in this Docker-in-container environment. The failed profile was deleted.
- Local Vault was not running during the latest attempt, so `kubernetes/kubeconfig_path` could not be retrieved.
- The ArgoCD CLI is not installed, so real ArgoCD application scenarios could not start.
- Scenarios 1-6 and 9 in `PHASE7_REAL_TEST_SCENARIOS.md` remain pending and must be run against real Kubernetes and ArgoCD services before Phase 7.5 can be marked complete.
- Do not substitute mocks, fake clients, sample cluster state, or import/build checks for this acceptance.

Partial-phase audit:

- Phase 2 uses the intended LiteLLM + Groq/Grok runtime. Tool action recording is wired into receipts and live Groq smoke validation passed.
- A live Groq CLI smoke test was attempted during the pending-item review on 2026-09-16, but stopped before the provider call because Vault at `127.0.0.1:8200` was not running. No live Groq result or model receipt was claimed.
- A live Groq CLI smoke test then passed on 2026-09-16 after starting Vault: the configured `groq/openai/gpt-oss-120b` model returned successfully, called the real `filesystem/read_directory` tool, and produced a successful JSON receipt with an R0 `ALLOW` action.
- Phase 3 code and live acceptance are complete for the explicit file-verification workflow. Broader domain-specific verification remains future work.
- Phase 6 now has a real R2 `kubectl_restart_pod` implementation wired through the agent and gated by Telegram approval. Live execution remains pending until a real Kubernetes context and approved non-critical pod are available. The Telegram module also retains both direct polling and application callback paths that should be consolidated.
- A fresh Phase 6 real-action preflight on 2026-09-16 confirmed policy outcomes for `kubectl/restart_pod` (R2), `argocd/app_sync_staging` (R2), and `argocd/app_sync_production` (R3) are `REQUIRE_APPROVAL`. The R2 restart implementation now exists, but Kubernetes has no current context and refuses `localhost:8080`, while ArgoCD CLI is unavailable; therefore no Telegram approval was sent without a real executable target.
- A final retest on 2026-09-16 reached the same infrastructure result: Kubernetes still falls back to refused `localhost:8080` and ArgoCD remains unavailable. The real R2 action is now executable in code, but its Telegram approval and pod restart remain correctly blocked until a real target cluster and approved non-critical pod exist.
- Phase 7 remains partial because the read-only tools and skill are wired, but Scenarios 1-6 and 9 in `PHASE7_REAL_TEST_SCENARIOS.md` have not passed against real Kubernetes and ArgoCD services.
- DevOps policy is now resolved before the DevOps function executes. The R2 `kubectl_restart_pod` action is implemented but has not executed without real cluster access.

## Files Added or Changed During This Work

Tracked files changed across the implementation checkpoint:

- `.env.example`: added Telegram bot token and approval chat ID placeholders.
- `core/gateway/telegram.py`: added Telegram application helpers and fixed update-offset ordering for live approvals.
- `docker-compose.yml`: passes Telegram bootstrap secrets to `vault-init`.
- `docker/init-vault.sh`: seeds Telegram credentials in Vault.
- `core/agent_engine.py`: registers and dispatches the five read-only DevOps tools through R0 policy checks.
- `core/agent_engine.py`: records successful filesystem and DevOps tool calls as `ActionRecord` values.
- `core/agent_engine.py`: exposes the approval-gated R2 `kubectl_restart_pod` action.
- `core/gateway/cli.py`: grants CLI runs the `DevOpsRead` capability.
- `core/gateway/cli.py`: places recorded actions into `RunReceipt.actions`.
- `core/gateway/cli.py`: accepts an explicit verification request and stores its result in `RunReceipt.verification`.
- `core/snapshots.py`: generic pre-state/action/post-state execution helper.
- `domains/devops/snapshots.py`: real Kubernetes pod snapshots and restart rollback verification.
- `IMPLEMENTATION_CHECKPOINT.md`: this handoff record.

New files:

- `domains/devops/tools/_mcp.py`: MCP v1/v2 compatibility import.
- `domains/devops/tools/kubectl_tools.py`: Vault-backed Kubernetes read tools.
- `domains/devops/tools/argocd_tools.py`: read-only ArgoCD CLI wrapper.
- `domains/devops/skills/argocd-status-check/SKILL.md`: read-only ArgoCD/Kubernetes investigation procedure.
- `PHASE7_REAL_TEST_SCENARIOS.md`: executable real-infrastructure scenarios for Kubernetes, ArgoCD, MCP, agent runs, negative safety checks, and receipt evidence.

Removed file:

- `tests/core/test_secrets.py`: removed because it used a fake Vault client and the project requirement is real integration testing rather than mock acceptance tests.

The local `.env` contains real values and is ignored. Never copy its contents into this file, source code, documentation, terminal output, or commits.

## Verification Commands

Run from the repository root:

```bash
python3 -m pytest -q
python3 -m compileall -q core domains tests
sh -n docker/init-vault.sh
docker compose config --quiet
```

Last verified result after removing mock-based approval and Vault tests:

```text
29 passed
```

The 29-test suite contains schema, policy, memory, and file-verification tests. It does not claim live Kubernetes, ArgoCD, Vault, or Telegram behavior.

Real action-recording check:

- Called the actual `read_directory` implementation against the repository working directory.
- Received `filesystem/read_directory` with policy decision `ALLOW`.
- Received a non-empty raw result in the generated `ActionRecord`.

Use `python3 -m pytest`, not the bare `pytest` executable, because the bare executable previously used an interpreter that did not resolve the editable repository import path.

## Security Rules

- Never print, paste, or commit values from `.env`.
- Never place real tokens in Markdown, tests, scripts, command arguments, or chat.
- Use Vault for runtime credentials through `core.secrets.get_secret`.
- Keep `secrets/`, `.env`, and `data/` out of commits.
- Do not run real production actions during testing.
- For live approval tests, use a clearly labeled harmless action and require an explicit human decision.
- Do not add fake clients, mock approval flows, sample cluster state, or fabricated integration results for Phase 7 acceptance.

## Next Recommended Work

Finish Phase 7.5, keeping the scope read-only:

1. Provide a real kubeconfig path through Vault at `kubernetes/kubeconfig_path`.
2. Install/configure the real ArgoCD CLI or replace the wrapper with an authenticated ArgoCD API client.
3. Run the CLI against a real test cluster and verify returned Kubernetes and ArgoCD state.
4. Record each real tool call in `ActionRecord` before adding any write or rollback action.

For the pending Phase 6 live action acceptance, after a real context and approved non-critical pod are available, run the agent with a goal naming that exact pod. Confirm Telegram approval, pod deletion/recreation through Kubernetes, the returned R2 `ALLOW` decision, and the approver ID in `ActionRecord.approved_by`. Do not run this against production.

The detailed procedure is in `PHASE7_REAL_TEST_SCENARIOS.md`. Phase 7 must not be marked complete from imports, Docker builds, or unavailable-client messages; Scenarios 1 through 6 and Scenario 9 must pass against real Kubernetes and ArgoCD services.

Do not begin additional Phase 10 write actions until the Phase 8 snapshot and rollback acceptance passes against a real non-critical pod.

### Phase 8: Checkpointing and rollback

Implementation complete for the real R2 pod restart path; live acceptance remains pending.

Completed:

- `core/snapshots.py` provides the generic pre-state/action/post-state executor.
- `domains/devops/snapshots.py` captures real pod identity, phase, readiness, and container resources.
- The R2 restart path now captures pre/post snapshots and sets `ActionRecord.rollback_available=True` after the pod is recreated and running.
- `rollback_pod_restart` verifies that a controller-recreated pod returns to its prior healthy condition; it does not claim success if the pod remains unhealthy.

Remaining:

- Run the real restart, snapshot, recreation, and rollback acceptance against an approved non-critical pod.
- Confirm the resulting receipt contains both snapshots and rollback availability.
- Confirm the rollback verification observes the recreated pod returning to its prior healthy condition.
- Do not mark Phase 8 live acceptance complete from code compilation or unavailable-cluster results.

### Phase 9: Learning loop

Implementation and live acceptance complete for the Phase 9 learning loop.

Completed:

- `draft_skill_if_warranted` creates a pending candidate only for receipts with at least five actions and passing verification.
- `synthesize_validation_test` creates a validation assertion from the passing receipt verification.
- `run_validation_test` evaluates only the restricted generated string-comparison assertion form.
- `promote_candidate_skill` requires Telegram approval, validates the generated assertion, and writes only validated skills.
- `write_skill_to_registry` records `authorship: agent-created`, version, and source run in the skill front matter.
- `core/memory/curator.py` records skill outcomes and prunes low-performing agent-created memory entries while preserving human-authored entries.
- `RunReceipt.candidate_skill` exposes eligible drafts for the promotion workflow.

Live acceptance completed on 2026-09-16:

- A real Groq run performed five real `filesystem/read_directory` actions against `core`, `domains`, `tests`, `config`, and `docker`.
- The same receipt contained passing real file verification and generated a `pending_approval` candidate linked to the actual run ID.
- The candidate was approved through real Telegram, its restricted validation passed, and it reached `validated` status.
- The validated skill was written to a temporary registry with `authorship: agent-created` and the source run ID in front matter; the temporary registry was removed after inspection.
- A second live promotion passed into the persistent repository registry: `domains/devops/skills/use-the-read-directory-tool/SKILL.md` reached `validated`, contains `authorship: agent-created`, and was retrieved successfully from a separate process after promotion.
- Curator acceptance passed using real persisted skill/document content and real directory outcomes `[success, failure, failure]`: the low-performing `agent-created` memory entry was removed, while the `human-authored` implementation-plan entry remained untouched.

Historical note:

- The first real eligibility attempt hit the former four-turn agent limit; after increasing the budget to eight, the same scenario completed successfully with five actions and passing verification.

### Phase 10: Write actions and GitOps path

Implementation complete for the GitOps wrapper and routing layer; real PR/merge/ArgoCD acceptance remains pending an approved target.

Completed:

- `domains/devops/git_actions.py` provides a real GitPython-based change, commit, push, and `gh pr create` workflow.
- `resolve_gitops_route` registers the R2/R3 GitOps-managed action set and requires approval before PR creation.
- The wrapper requires a clean working tree, an existing remote, a non-protected branch name, an explicit repository-relative target path, and a non-empty change.
- The wrapper returns the created PR reference and restores the original branch after the operation.

Validation completed:

- Real `gh` authentication is active for the repository owner.
- Real routing returns `REQUIRE_APPROVAL/R2` for pod restart and staging sync, `REQUIRE_APPROVAL/R3` for production sync, and `DENY/R4` for unregistered Terraform destruction.
- The wrapper was exercised against the current dirty repository and refused before mutation with `GitOps action requires a clean working tree`.
- No pull request was created; the repository currently has no open PRs.

Remaining:

- Route approved R2+ GitOps-manageable actions through this wrapper.
- Run a real low-risk test change against an explicitly approved repository and branch.
- Confirm a real PR is opened, merged manually, and synchronized by ArgoCD.
- Verify the post-merge live state and record the result in a `RunReceipt`.
- Do not invoke the wrapper against this repository or production without an explicit approved target.
