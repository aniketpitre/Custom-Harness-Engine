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

Partially implemented.

- `core/agent_engine.py` uses LiteLLM with the configured Groq model.
- The runtime supports a local `read_directory` function tool.
- `core/gateway/cli.py` creates a Goal, assembles Context from memory, runs the agent, and emits a JSON `RunReceipt`.
- The receipt currently has an empty `actions` list because tool action recording is not yet wired.
- The current runtime is not using the Claude Agent SDK from the original plan.

### Phase 3: Verification

Core verifier implemented and tested.

- `core/verification.py` contains `verify_file_content`.
- `tests/core/test_verification.py` verifies matching content, mismatches, and missing files.
- Verification is not yet wired into the normal agent run lifecycle.

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
- `tests/core/test_secrets.py` covers loader validation and malformed responses.

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

Partially implemented and live-tested.

Implemented:

- `domains/devops/policy_table.py` contains R0 read-only entries, R2 restart/sync entries, R3 production sync, and R4 destructive entries.
- `resolve_policy` requires approval for R2/R3 and denies R4.
- `core/gateway/telegram.py` sends inline Approve/Deny buttons and records the Telegram user ID in memory.
- `build_approval_application` and `run_approval_bot` provide a Telegram polling application.
- A Telegram update-offset race was fixed: stale updates are drained before sending the approval message, then matching callbacks are polled using the captured offset.

Live acceptance performed without mocks:

1. A real Telegram R3 request was approved. No infrastructure action was attached to that request.
2. A second real Telegram R3 request was denied.
3. The attached safe local no-op did not execute:

```text
LIVE_APPROVAL_RESULT=DENIED
SAFE_NOOP_EXECUTED=false
```

Limitations:

- The live acceptance used a safe no-op rather than a real infrastructure mutation.
- The current production tool exposed by `core/agent_engine.py` is only the R0 `read_directory` tool, so there is not yet a real R2/R3 DevOps tool wired through the agent.
- `ActionRecord.approved_by` is not yet persisted into the normal run receipt.
- The Telegram module contains both direct polling in `request_approval` and an application callback path; consolidate these when integrating the long-running gateway.

## Files Added or Changed During This Work

Tracked files with current working-tree changes:

- `.env.example`: added Telegram bot token and approval chat ID placeholders.
- `core/gateway/telegram.py`: added Telegram application helpers and fixed update-offset ordering for live approvals.
- `docker-compose.yml`: passes Telegram bootstrap secrets to `vault-init`.
- `docker/init-vault.sh`: seeds Telegram credentials in Vault.

New file:

- `tests/core/test_secrets.py`: Vault loader contract tests.

The local `.env` contains real values and is ignored. Never copy its contents into this file, source code, documentation, terminal output, or commits.

## Verification Commands

Run from the repository root:

```bash
python3 -m pytest -q
python3 -m compileall -q core domains tests
python3 -m pytest -q tests/core/test_secrets.py
sh -n docker/init-vault.sh
docker compose config --quiet
```

Last verified result after removing mock approval coverage:

```text
35 passed
```

Use `python3 -m pytest`, not the bare `pytest` executable, because the bare executable previously used an interpreter that did not resolve the editable repository import path.

## Security Rules

- Never print, paste, or commit values from `.env`.
- Never place real tokens in Markdown, tests, scripts, command arguments, or chat.
- Use Vault for runtime credentials through `core.secrets.get_secret`.
- Keep `secrets/`, `.env`, and `data/` out of commits.
- Do not run real production actions during testing.
- For live approval tests, use a clearly labeled harmless action and require an explicit human decision.

## Next Recommended Work

Proceed to Phase 7, but keep the scope read-only:

1. Add a real Kubernetes read-only tool under `domains/devops/tools/kubectl_tools.py`.
2. Load the kubeconfig path through Vault rather than hardcoding it.
3. Add a real ArgoCD read-only tool under `domains/devops/tools/argocd_tools.py`.
4. Register those tools in the agent engine with R0 policy entries.
5. Add the first DevOps skill under `domains/devops/skills/`.
6. Run the CLI against a real test cluster and verify the returned state.
7. Record each tool call in `ActionRecord` before adding any write or rollback action.

Do not begin Phase 8 or Phase 10 write actions until real read-only tools, action receipts, and verification are connected end to end.
