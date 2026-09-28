# Implementation Checkpoint v2

- [x] Phase 18: Effect Ownership (`EffectStack`, `EffectScope` in `core/agent_engine.py`, `teardown_tasks` in `RunReceipt`)
- [x] Phase 19: Lifecycle Management
- [x] Phase 20: Integration & HMR (Hot Module Reload) Foundation

- [x] Phase 21: Auto-Compaction Context Engine
- [x] Phase 22: Session Branching (The "Fork" Primitive)
- [x] Phase 23: On-Demand Skill & Tool Loading (JIT Context)
- [x] Phase 24: Self-Editing Harness (Live Hot-Swapping)
- [x] Phase 25: Setup Wizard & User Guide

### Phase A Progress (V3 Architecture)
- [x] A1: Purge hardcoded Vault tokens from tests
- [x] A2: Authenticate API and bind to 127.0.0.1

> **Note on Test Failures for A2**: API integration tests (Phase 15, 16, 17, 22) are currently failing with 401 Unauthorized because they have not yet been updated to mock the new `HARNESS_API_TOKEN` Bearer authentication.
