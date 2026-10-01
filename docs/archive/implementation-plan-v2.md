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
# Harness Engine Optimization Plan (Pi-Inspired Architecture)

**Objective**: Introduce Pi's defining optimizations (extreme speed, context frugality, and live self-modification) into the Harness Engine *without* sacrificing our core R0-R4 safety gates, VERIFY assertions, or observability pipeline.

This plan details new Implementation Phases (Phases 21-24) to seamlessly integrate these capabilities onto our existing V2 architecture.

---

## What makes Pi highly optimized? (The Gap Analysis)
1. **Dynamic Self-Modification**: Pi can write a new tool in TypeScript, reload its context, and instantly use it. Harness Engine has Hot Module Reload (`reload_registry()`) but no integrated tool to let the agent inject its own live code into the active memory pool.
2. **Context Compaction**: When Pi hits token limits, it replaces early conversational nodes with a dense AI summary, keeping the window lightning fast. Harness Engine currently just hits a token budget and halts.
3. **Tree-Based Sessions**: Pi allows users to fork standard conversations mid-way. Harness Engine uses flat, immutable linear sessions.
4. **JIT (Just-In-Time) Instructions**: Pi keeps system prompts tiny and loads complex instructions only when a specific tool or skill is invoked.

---

## Phase 21: Auto-Compaction Context Engine 
**Goal**: Prevent token bloat (and speed up inference) by automatically compressing historical turns in the middle of a long-running execution loop.

- **Implementation Details**:
  - Update `core/agent_engine.py`. Inside `run_agent_generator`, introduce a threshold (e.g., if `total_tokens` > 50,000).
  - When the threshold is reached, spawn an asynchronous fast model (e.g., Haiku or a dedicated summarization LLM) to compress the oldest N messages in `messages` array into a single `{"role": "system", "content": "Previous Summary: ..."}` node.
  - The agent loop continues without dropping session context but drastically reducing the active token footprint.

## Phase 22: Session Branching (The "Fork" Primitive)
**Goal**: Allow non-destructive alternative executions by converting our linear sessions into a tree, copying Pi’s `/tree` capability.

- **Implementation Details**:
  - Update `core/memory/store.py`. Add a `parent_id` column to the `sessions` table.
  - Create a new API endpoint `POST /sessions/{session_id}/fork`. This duplicates the `run_receipt` and `environment` up to a certain turn point into a new `session_id`.
  - Update the dashboard/frontend (if rebuilt in the future) or CLI to allow resuming from a chosen chronological node in a past session rather than starting fresh.

## Phase 23: On-Demand Skill & Tool Loading (JIT Context)
**Goal**: Slim down the massive default System Prompt by loading specific domain knowledge only when deemed necessary.

- **Implementation Details**:
  - Refactor `core/agent_engine.py`: Remove hardcoded Tool lists (`DEVOPS_READ_TOOLS`, etc.) from the initial model request.
  - Introduce an `agent_introspect` generic tool. The agent starts with a tiny prompt and a directory of available skill categories. If it detects a DevOps goal, it calls `load_skill("devops")`, dynamically mutating the `allowed_tools` and `tools` array for subsequent turns in the same loop. 
  - This massively reduces input token count for simple tasks (e.g., generic file search).

## Phase 24: Self-Editing Harness (Live Hot-Swapping)
**Goal**: Give the Harness Engine the ability to write a new tool, register it, and execute it *within the same running session*, just like Pi.

- **Implementation Details**:
  - Expose a `write_and_register_tool` native function to the Engine. 
  - The tool will write a Python function to a dedicated dynamically loaded directory (e.g., `core/plugins/dynamic/`).
  - Upon writing, the tool triggers the already implemented `reload_registry()` (from Phase 20).
  - The new function immediately manifests in the active agent's tool schema for the *very next turn*.
  - To maintain safety, code written this way triggers an R3 (Require Approval) Policy gate before the engine actually binds and executes it! This merges Pi's speed with Harness Engine's safety.

---

## Action Plan & Next Steps
We are currently fully complete through Phase 20. 

If this plan is approved:
1. **First Step (Phase 21)**: We will write the `ContextCompactor` inside the core engine loop to manage memory inflation constraints automatically natively.
2. **Second Step (Phase 24)**: We will build the `DynamicToolRegistry` allowing the agent to literally code its own tools in-flight (protected by an R3 Telegram approval). 

*All steps will involve writing unit tests to ensure our R0-R4 policy mechanisms are never bypassed during these optimizations.*
