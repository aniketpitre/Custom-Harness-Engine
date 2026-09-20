# Harness Engine

Harness Engine is a general-purpose, agentic execution and learning runtime designed to safely bridge high-level goals with verified, actionable outcomes. While initially architected with a DevOps domain pack, the engine is designed for cross-domain functional extensibility (Coding, Research, Data).

## Architecture

The Harness Engine follows a rigorous execution pipeline:

```text
GOAL → CONTEXT → AGENT → POLICY → EXECUTE → VERIFY → RECEIPT → LEARN → MEMORY
```

### Key Pillars
*   **Safety First**: Built-in Risk Tiering (R0–R4), mandatory human-in-the-loop approval gates (for R2+ actions), and automated anomaly/rollback mechanisms.
*   **Verifiable Execution**: Every action produces a `RunReceipt`, which is validated by an automated verification gate, ensuring agents do not hallucinate outcomes.
*   **Iterative Learning**: Successful, verified workflows are promoted to validated "Skills" that the agent can reuse in future sessions.
*   **Operational Hardening**: Middleware for token budgeting, output spilling (for large logs/traces), and secure sandbox environment management.

## Project Status

All phases (0-17) defined in the implementation plan have been completed and verified.

| Phase | Description | Status |
| :--- | :--- | :--- |
| 0-14 | Core Primitives, Agent Loop, Policy, DevOps Pack, Observability, API | ✅ DONE |
| 15 | Event Streaming & Interactivity | ✅ DONE |
| 16 | Context & Execution Hardening | ✅ DONE |
| 17 | Background Infrastructure (Scheduler, Dreams, Advisor, Webhooks) | ✅ DONE |

## Getting Started

### Prerequisites
*   Python 3.12+
*   Docker/Docker Compose (for Vault development instance)
*   HashiCorp Vault installed and accessible.

### Setup
1.  **Repository**:
    ```bash
    git clone <repository-url>
    cd harness-engine
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e .
    ```
2.  **Environment**:
    Load necessary environment variables (see `.env.example`).
3.  **Secrets (Vault)**:
    Ensure Vault is running and seeded with required secrets (Groq API, Telegram tokens, Kubernetes config). The application expects `VAULT_ADDR` and `VAULT_TOKEN` to be set in the runtime environment.

### Running the System
The Harness Engine operates primarily via its API Gateway:
```bash
uvicorn core.gateway.api:app --reload
```
You can interact via the documented endpoints (`POST /sessions`, `POST /cron`, `GET /stream`, etc.).

## Implementation Plan Trace

The full sequence of implementation (Phases 0–17) is tracked in `harness-engine-implementation-plan.md`. Detailed status and check-off for every step is maintained in `IMPLEMENTATION_CHECKPOINT.md`.

## Testing
The system includes a comprehensive test suite (74+ tests) covering primitives, policy logic, domain-specific tools (Kubernetes/ArgoCD), event streaming, hardening mechanisms, and background infrastructure.
```bash
python3 -m pytest tests/ -v
```

---
*For architectural details, refer to `general_purpose_agent_harness_architecture.md`.*
