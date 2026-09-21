# Architecture Update v2 — Spatiotemporal Composability Extensions

This document outlines the architectural evolution of the Harness Engine to include basic temporal and spatial composability, inspired by the Cordis paradigm, while maintaining Ponytail compatibility.

## 1. Goal
Introduce minimal architectural primitives to allow the Harness Engine to:
1.  **Track resource ownership** (Temporal Composability).
2.  **Manage component lifecycles** (Activation/Deactivation).
3.  **Ensure reliable teardown** of agent-invoked effects.

## 2. Minimalist Architectural Primitives

### A. LifecycleManager (Extension of AgentRegistry)
- **Addition:** Add `lifecycle_state` attribute (UNRESOLVED, ACTIVE, DEACTIVATING, INACTIVE, FAILED) to agent/tool registries.
- **Why:** Enable the runtime to understand whether a component is safe to re-use or requires teardown.

### B. EffectScope (Extension of AgentEngine)
- **Addition:** A LIFO stack-based context manager implemented in `core/agent_engine.py`.
- **Why:** Track effects (sockets, files, tasks) registered by an agent turn and execute their inverse on turn completion.
- **Primitive:** `ctx.effect(invoker, disposer)`.

### C. Reactive Coeffects (Foundation)
- **Addition:** Register dependencies as state-tracked objects in the `ComponentRegistry`.
- **Why:** Allow components to query "Is this dependency ready/healthy?" synchronously, preventing task failures due to known-down dependencies.

## 3. Integration Model

The existing infrastructure (`core/gateway`, `core/registry.py`, `core/agent_engine.py`) remains the primary runtime. The new primitives act as *extensions* managed by the existing phases rather than separate frameworks.

- **Phase-by-Phase Integration:**
    - Phase 18: Effect tracking is integrated into the existing `run_agent` loop wrapper.
    - Phase 19: Registry states are exposed through the existing API gateway (leveraged by Dashboard Phase D12-D15).
