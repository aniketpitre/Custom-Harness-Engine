# Harness Engine

Harness Engine is a general-purpose, agentic execution and learning runtime engineered to bridge high-level operational goals with verified, actionable outcomes. Unlike generic agentic frameworks, it is built with a "Safety & Observability First" philosophy, bridging the gap between autonomous utility and production-grade reliability.

## Why Harness Engine is Different

- **Policy-Tiered Execution (R0–R4)**: Every tool action is validated against a dynamic risk table before execution. R0 is read-only; destructive or production modifications (R2-R3) trigger mandatory human-in-the-loop approval gates via secondary channels (e.g., Telegram).
- **Verifiable Execution Loop**: Every operation produces a immutable `RunReceipt`. Verification gates explicitly validate outcomes against expected state (e.g., K8s pod liveness, configuration targets) *before* marking a goal complete, eliminating hallucinated success.
- **Robust Iterative Learning**: Successful verification outcomes automatically promote candidate tools/workflows to validated "Skills" (`SKILL.md` format), building an persistent organic toolset in real-time.
- **Production-Grade Hardening**: Built for high-stakes environments with built-in token budgeting, automated output-log spilling (`.workspace/spill/`), anomaly rollback mechanisms, and automated memory consolidation ("Dreams").
- **SSE Event Streaming**: Real-time visibility into the live agent pipeline via `/sessions/{id}/stream`, with mid-task steering via `/sessions/{id}/interrupt`.

## Core Architecture

The Harness Engine follows a rigorous, non-linear execution pipeline:

```text
GOAL → CONTEXT → AGENT → POLICY → APPROVAL → EXECUTE → VERIFY → RECEIPT → LEARN → MEMORY
```

### Key Pillars
*   **Safety**: Built-in Risk Tiering prevents unauthorized actions.
*   **Verifiable Execution**: `RunReceipts` ensure outcomes match goals.
*   **Iterative Learning**: Automated skill promotion loop.
*   **Observability**: Real-time SSE event streaming and interruption support.

## Implementation Status

### Phases 0–17: Core Runtime & Infrastructure
Completed core primitives, agent loop, DevOps packs, observability, interactive webhooks, and background infrastructure (scheduler, advisor, dreamer).

### Phases 18–20: Composability & HMR
- **Phase 18**: Effect Ownership — `EffectStack`/`EffectScope` for temporal composability.
- **Phase 19**: Lifecycle Management — `LifecycleState` enum for agent registry states.
- **Phase 20**: Hot Module Reload — transactional `reload_registry()` without process restart.

*See `IMPLEMENTATION_CHECKPOINT.md` and `IMPLEMENTATION_CHECKPOINT_V2.md` for status.*

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/agents` | List registered agents with lifecycle states |
| GET | `/agents/{id}` | Get agent profile |
| POST | `/sessions` | Create a new execution session |
| GET | `/sessions/{id}` | Get session status and receipt |
| GET | `/sessions/{id}/stream` | SSE stream of agent execution events |
| POST | `/sessions/{id}/interrupt` | Inject mid-task steering message |
| POST | `/cron` | Schedule recurring agent execution |
| POST | `/memory/dream` | Trigger memory consolidation |

## Getting Started

### Prerequisites
- Python 3.12+
- Docker & Docker Compose (optional, for Vault)
- HashiCorp Vault (accessible, with tokens)

### Setup
1. **Clone & Install**:
   ```bash
   git clone <repo>
   cd harness-engine
   source .venv/bin/activate
   pip install -e .
   ```
2. **Environment**: Configure `.env` based on `.env.example`.
3. **Vault**: Ensure Vault is seeded with Groq/Telegram/Kubernetes secrets.

### Running
```bash
python main.py
# or
uvicorn core.gateway.api:app --host 0.0.0.0 --port 8000
```

---
*For technical details, see `general_purpose_agent_harness_architecture.md`.*
