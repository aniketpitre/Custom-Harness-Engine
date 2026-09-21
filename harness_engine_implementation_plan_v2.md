# Implementation Plan v2 — Composability Evolution

This plan details the implementation of the minimal architectural primitives defined in `harness_engine_architecture_v2.md`.

## Phase 18: Effect Ownership (Temporal Composability)
**Goal:** Track side-effects and register disposers for agent-invoked resources within the agent loop.

- **Files to Modify:**
    - `/root/Harness-Engine/core/agent_engine.py`: Introduce `EffectStack` class. Add `EffectScope` wrapper to existing `run_agent()` loop.
    - `/root/Harness-Engine/core/primitives/execution.py`: Add `on_teardown` support to `RunReceipt`.

- **Reuse:** Use existing `async` loop structures.

- **Validation:** Write a test simulating a resource (socket/file) registration that is automatically closed when the agent turn completes (success or failure).

## Phase 19: Lifecycle Management (Spatial Composability)
**Goal:** Introduce explicit lifecycle states into the registry to facilitate safe component management.

- **Files to Modify:**
    - `/root/Harness-Engine/core/registry.py`: Add `LifecycleState` enum and integrate state tracking into current registry dictionaries.
    - `/root/Harness-Engine/core/gateway/api.py`: Expose lifecycle status via `/agents` API endpoint.

- **Reuse:** Reuse existing FastMCP-compliant registry structure.

- **Validation:** Test that agent calls fail gracefully (or pause) if the state is `FAILED`.

## Phase 20: Integration & HMR (Hot Module Reload) Foundation
**Goal:** Enable safe, non-process-level recovery when component registration changes.

- **Files to Modify:**
    - `/root/Harness-Engine/main.py`: Update the harness startup/reload path (non-process-restart) by resetting `Registry` states and triggering re-initialization of only changed components.

- **Validation:** Verify that after a component load error, the previous state is preserved and the harness remains active (no crash).
