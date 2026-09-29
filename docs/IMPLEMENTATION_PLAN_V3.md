# Implementation Plan V3 - The Re-Architecting

## Context
This plan addresses the critical findings from `Harness_Engine_Audit.md`. The goal is to move from the current precarious architecture to a robust, secure, and performant agent framework by adopting the target architecture outlined in the audit (§14).

## Current Status
The current codebase works on a happy path but suffers from severe security vulnerabilities (unauthenticated control plane, path traversal, R0 tool access), fragility (crashing on tool errors, import-order bugs, non-atomic SQLite operations), and performance issues (blocking I/O, prompt-cache invalidating compaction).

## V3 Architecture
Based on the audit, we are moving to:
1.  **Core**: A minimal ~1,000 LOC core responsible for the loop, registry, policy, logging (event log), and context management.
2.  **Plugin System**: Everything domain-specific is moved to plugins with `Disposer` patterns (Cordis-lite).
3.  **Source of Truth**: An append-only event log (SQLite WAL). Receipts, SSE, metrics, and session search will be projections of this log.
4.  **Security**: Deny-by-default with argument-aware risk tiers, sandboxing, and strict network/path confinement.

## Roadmap & Prioritisation

### Phase A: Security and Correctness (High Priority)
- Rotate Vault token, add secret scanning.
- Authenticate API, bind to 127.0.0.1.
- Sanitize tool registration: check for R3 capability, use argument hashing for approval, run dynamic/sandbox tools out-of-process.
- Implement path confinement for all file tools (workspace confinement).
- Implement approval broker with argument-aware risk tiers and timeouts.
- Handle tool errors gracefully without crashing the loop.
- Fix tracing and orchestration table initialization.

### Phase B: Robustness and Performance (Medium Priority)
- Event log + replayable session projections (resume/fork).
- Token-based compaction (pruning, pinning, memory flush first).
- Streaming and async run execution.
- Parallel read access and non-blocking I/O (asyncio).

### Phase C: Feature Parity & Extensibility (Ongoing)
- Domain tools to plugin system.
- Hook system.
- Skill curation and management.
- Persistent cron scheduling.

## Verification
- Security regressions tests (path traversal, SSRF, injection).
- Transcript validator (ensuring tool calls are paired and valid).
- Concurrent sessions stress tests.
- Property test for compaction.

## Status update (September 2026)

Phases A to D are complete (details and tests in `IMPLEMENTATION_STATUS.md`). Delivered since: single-command
install (`harness init/doctor`, packaged defaults, installer), OS-keyring secret storage with optional Vault,
a live terminal approval prompt chained with API and Telegram, tag-driven release automation, and the DevOps CLI
theme. The next phases (E1 to E4: cost accounting, `harness chat`, permission modes, alert-driven investigation,
Slack approvals, MCP over HTTP, hardening) are planned in `ROADMAP.md`.
