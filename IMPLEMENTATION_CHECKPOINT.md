# Custom Harness Engine Implementation Checkpoint

**Checkpoint date:** 2026-09-20
**Repository:** Custom-Harness-Engine
**Current branch:** main
**Python:** 3.12.3 (runtime), 3.14.2 (system)

This file is a handoff for another coding agent. Read it before changing the implementation. Preserve existing user changes and do not expose or commit secrets.

## Project Intent

This repository is building a general-purpose agent execution runtime with DevOps as the first domain pack:

```text
Goal -> Context -> Agent -> Policy -> Approval -> Execution -> Verification -> Receipt -> Learning -> Memory
```

The implementation sequence is documented in `harness-engine-implementation-plan.md`. The architecture is documented in `general_purpose_agent_harness_architecture.md`.

## Quick Status (2026-09-20)

**Test suite: 65 passed, 0 failed** (`python3 -m pytest tests/ -k "not test_phase10_real" -v`)

| Phase | Name                           | Status           | Remaining                                                        |
|-------|--------------------------------|------------------|------------------------------------------------------------------|
| 0     | Environment & project setup    | ✅ DONE           | —                                                                |
| 1     | Core primitives                | ✅ DONE           | —                                                                |
| 2     | Minimal agent loop             | ✅ DONE           | —                                                                |
| 3     | Verification                   | ✅ DONE           | —                                                                |
| 4     | Memory                         | ✅ DONE           | —                                                                |
| 5     | Vault secrets                  | ✅ DONE           | —                                                                |
| 6     | Policy & approval gate         | ✅ DONE           | —                                                                |
| 7     | DevOps read-only domain pack   | ✅ DONE           | —                                                                |
| 8     | Checkpointing & rollback       | ✅ DONE           | —                                                                |
| 9     | Learning loop                  | ✅ DONE           | —                                                                |
| 10    | Write actions & GitOps path    | ✅ DONE           | —                                                                |
| 11    | Observability                  | ✅ DONE           | —                                                                |
| 12    | Orchestration layer            | ✅ DONE           | —                                                                |
| 13    | Hardening                      | ✅ DONE (in code) | —                                                                |
| 14    | Unified Control Plane & API    | ✅ DONE           | —                                                                |
| 15    | Event Streaming & Interactive  | ✅ DONE           | —                                                                |
| 16    | Context & Execution Hardening  | ✅ DONE           | —                                                                |
| 17    | Background Infrastructure      | ✅ DONE           | —                                                                |

### What a new session should do next

The codebase for the initial Data Plane (Phases 0-13) and the Phase 14 Control Plane are fully tested and verified ✅. The infrastructure for Phases 15-17 is complete. The custom dashboard (Phases 18-24 / D0-D11) is implemented.

### Key runtime notes for a fresh agent

- **Model**: LiteLLM + Groq at `groq/openai/gpt-oss-120b`. Set via `HARNESS_MODEL` env var.
- **Vault**: Dev instance at `http://127.0.0.1:8200`. Start with `docker compose up vault vault-init -d`. Token in `.env` as `VAULT_DEV_ROOT_TOKEN_ID`; app code reads `VAULT_TOKEN`.
- **Kubernetes**: Kind cluster named `harness`. Kubeconfig stored in Vault at `kubernetes/kubeconfig_path`. Namespaces: `test-harness`, `argocd`.
- **`allowed_tools` parameter**: Uses capability strings `"Read"`, `"DevOpsRead"`, `"DevOpsWrite"` — NOT individual tool names.
- **pytest**: Uses `asyncio_mode = auto` in `pytest.ini`. Run with `python3 -m pytest tests/ -v`.
- **ArgoCD CLI**: Installed at `/usr/local/bin/argocd` v3.5.3. Must use `--core` flag (no ArgoCD API server). Set namespace first: `kubectl config set-context --current --namespace=argocd`.
- **Telegram**: Approval gate for R2/R3 actions. Bot token and chat ID in Vault at `telegram/bot_token` and `telegram/approval_chat_id`.
- **FastAPI**: REST API Gateway at `core/gateway/api.py`. Run with `uvicorn core.gateway.api:app`. Dependencies: `fastapi`, `uvicorn`.
- **Dashboard**: React/Vite/Tailwind terminal-style UI monitoring Harness primitives. Run with `npm run dev` in `frontend/`.
- **Security**: Never print secret values. Never run mutations against production. Never substitute mocks for live acceptance.

## Detailed Phase Status

(Phases 0-17 maintained as above)

## Dashboard Implementation (Phases D0-D11)

### What
A full-stack, terminal-native dashboard (React/Vite).

### Why
To provide real-time, high-velocity observability for agent execution flow, security (policy/risk tiers), and budget tracking. It bridges the gap between raw API outputs and operator-friendly steering.

### How
By reusing existing Harness Engine API primitives (`/sessions`, `/stream`, `/interrupt`) and providing a dedicated high-bandwidth UI layer for stream logging and state management.

### Status

| Phase | Description | Status |
| :--- | :--- | :--- |
| **D0** | Backend API Extensions + Auth | ✅ DONE |
| **D1** | Frontend Scaffold (React/Vite) | ✅ DONE |
| **D2** | Overview (Landing Page) | ✅ DONE |
| **D3** | Live Run Page (SSE + Interruption) | ✅ DONE |
| **D4** | Runs Page (FTS Search) | ✅ DONE |
| **D5** | Settings, Secrets & Channels | ✅ DONE |
| **D6** | Skills, Tools & Learning Queue | ✅ DONE |
| **D7** | Analytics Page | ✅ DONE |
| **D8** | Approvals, Triggers & Webhooks | ✅ DONE |
| **D9** | Orchestration & Verification | ✅ DONE |
| **D10** | System & Memory Dreams | ✅ DONE |
| **D11** | Hardening & Deployment | ✅ DONE |
