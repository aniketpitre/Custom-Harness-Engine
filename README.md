# Harness Engine

Harness Engine is a general-purpose, agentic execution and learning runtime engineered to bridge high-level operational goals with verified, actionable outcomes. Unlike generic agentic frameworks, it is built with a "Safety & Observability First" philosophy, bridging the gap between autonomous utility and production-grade reliability.

## Why Harness Engine is Different

- **Policy-Tiered Execution (R0–R4)**: Every tool action is validated against a dynamic risk table before execution. R0 is read-only; destructive or production modifications (R2-R3) trigger mandatory human-in-the-loop approval gates via secondary channels (e.g., Telegram).
- **Verifiable Execution Loop**: Every operation produces a immutable `RunReceipt`. Verification gates explicitly validate outcomes against expected state (e.g., K8s pod liveness, configuration targets) *before* marking a goal complete, eliminating hallucinated success.
- **Robust Iterative Learning**: Successful verification outcomes automatically promote candidate tools/workflows to validated "Skills" (`SKILL.md` format), building an persistent organic toolset in real-time.
- **Production-Grade Hardening**: Built for high-stakes environments with built-in token budgeting, automated output-log spilling (`.workspace/spill/`), anomaly rollback mechanisms, and automated memory consolidation ("Dreams").
- **Hermes-Style Observability**: Integrated real-time dashboard provides terminal-native visibility into the live agent pipeline, featuring SSE event streaming, budget gauges, and adversarial cross-check status (Phase 0–24 implementation).

## Core Architecture

The Harness Engine follows a rigorous, non-linear execution pipeline:

```text
GOAL → CONTEXT → AGENT → POLICY → APPROVAL → EXECUTE → VERIFY → RECEIPT → LEARN → MEMORY
```

### Key Pillars
*   **Safety**: Built-in Risk Tiering prevents unauthorized actions.
*   **Verifiable Execution**: `RunReceipts` ensure outcomes match goals.
*   **Iterative Learning**: Automated skill promotion loop.
*   **Observability**: Real-time integration via SSE event streaming.

## Implementation Status (Phases 0–24)

### Phases 0–17: Core Runtime & Infrastructure
Completed core primitives, agent loop, DevOps packs, observability, interactive webhooks, and background infrastructure (scheduler, advisor, dreamer).

### Phases 18–24: Dashboard Implementation
Complete Hermes-style dashboard featuring:
- **Terminal-Native Layout**: Dark, dense, high-velocity stream visualization.
- **Real-time Steering**: Interactive interruption and session steering.
- **Advanced Observability**: Security/Budget gauges, Memory Dream visualizer, and Verification inspector.

*See `IMPLEMENTATION_CHECKPOINT.md` for status.*

## Getting Started

### Prerequisites
- Python 3.12+
- Docker & Docker Compose
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
- **API**: `uvicorn core.gateway.api:app --reload`
- **Dashboard (Frontend)**:
  ```bash
  cd frontend
  npm install
  npm run dev
  ```
  *(Then visit `http://localhost:5173`)*

---
*For technical details, see `general_purpose_agent_harness_architecture.md`.*
