# Implementation status (V3 roadmap)

Status of every item in `docs/Harness_Engine_Audit.md` §15 and `docs/IMPLEMENTATION_PLAN_V3.md`.
Tests are under `tests/`; run `pytest` (unit + integration) and `pytest -m live tests/live` (real infrastructure).

## Phase A - security and correctness

| # | Item | Status | Where / test |
|---|---|---|---|
| A1 | Rotate leaked Vault token, purge history, secret scanning | **Partly: action needed.** Scanner config, CI job and pre-commit hook added; the old token is still in git history | `.gitleaks.toml`, `.github/workflows/ci.yml`, `tests/test_project_hygiene.py` |
| A2 | API auth, loopback bind | Done, and the `default_unsafe_token_change_me` fallback is gone (no token configured = 503). Constant-time compare, per-token scopes, rate limit | `core/gateway/api.py`, `tests/test_api.py::TestAuth` |
| A3 | Self-edit gating and hardening | Done: `SelfEdit`/`Dynamic` capabilities, R3 approval showing the full source + sha256 (diff on update), name validation, AST allowlist, declared risk tier, out-of-process runner with filtered env and rlimits (+bwrap network isolation when installed), per-file plugins with quarantine | `core/plugins/dynamic.py`, `tests/test_security.py::TestSelfWrittenTools` |
| A4 | File/web confinement, SSRF | Done: shared `resolve_workspace_path`, symlink-safe, deny list, engine-source write protection; SSRF guard re-checked on every redirect hop; exact-replace edit; no `grep` option injection | `core/confine.py`, `domains/generic/*`, `tests/test_security.py` |
| A5 | Approval broker | Done: single consumer, approver allowlist, args-hash binding, timeout -> deny, once/session/always (never always for R3), API + Telegram + terminal channels, persisted | `core/approvals.py`, `core/gateway/telegram.py` |
| A6 | Argument-aware risk | Done: protected namespaces are R4 *before* any API call; sync risk depends on the app; shell command classifier; GitOps `repo_path` allowlist; taint raises mutating tiers | `domains/devops/plugin.py`, `core/policy.py` |
| A7 | Errors as tool results + loop guard | Done | `core/tools.py`, `core/loop.py` |
| A8 | Tracing import bug, dependencies, `workflow_checkpoints` | Done | `core/telemetry.py`, `pyproject.toml`, `core/memory/store.py` |
| A9 | Outcome enum, correct success | Done: `completed \| budget_exhausted \| turn_limit \| time_limit \| error \| cancelled \| loop_guard \| crashed`; success needs completed **and** not-failed verification | `core/receipts.py` |

## Phase B - loop, context, performance

| # | Item | Status |
|---|---|---|
| B1 | Event log; resume and fork at any event | Done (`core/eventlog.py`); hash chain, optional HMAC; receipts are projections; fork never splits a tool pair |
| B2 | Token-based cut-safe compaction | Done (`core/compaction.py`): prune first, pinned first user message, user-role summary, deterministic fallback, memory flush, retry on context-overflow; 1,000-transcript property test |
| B3 | Streaming, detached runs, cancel | Done (`core/runs.py`, `core/llm.py`); SSE tails a live buffer with `Last-Event-ID`, replays from the log after a restart |
| B4 | Parallel read-only tools, non-blocking handlers | Done: consecutive `parallel_safe` reads run concurrently; sync handlers run in threads |
| B5 | Retries, failover, per-model credentials | Done (`core/llm.py`, `core/secrets.py`) |
| B6 | Prompt caching, stable prefix, no JIT round trips | Done: sorted tools, no timestamps, cache markers for Anthropic models; `load_skill` removed |
| B7 | Secrets chain + cache, settings object, migrate once + WAL | Done |
| B8 | Per-tool output limits + `read_spill` | Done (8k default; head/tail preview; unique spill names) |

## Phase C - parity and extensibility

C1 bash (classifier, env filter, bwrap/docker), paged `read`, exact-replace `edit`, checkpoints + `/rewind` - done.
C2 `memory` tool (limits, scanning, frozen snapshot, provenance = external-fetched when tainted) and `session_search` - done.
C3 `skills_list`/`skill_view`/`skill_manage` (approval-gated, scanned), skill outcome metrics, curator - done.
C4 hook bus + shell-hook adapter (`config/hooks.yaml`) - done. C5 MCP client - done (stdio, tested against a real server).
C6 subagents (typed profiles, capability intersection, shared budget, concurrency and time limits, child sessions) - done;
**worktree isolation for subagents is not implemented** (GitOps itself uses a worktree).
C7 persistent cron, heartbeat, list/pause/delete - done. C8 `AGENTS.md` - done.

## Phase D - differentiators and Cordis

| # | Item | Status |
|---|---|---|
| D1 | Plugin fibers: disposers, lifecycle, dependencies, transactional reload | Done (`core/plugins/base.py`); no file watcher - reload via `POST /admin/reload` |
| D2 | Verifier registry + independent verifier agent | Done (`core/verifiers.py`) |
| D3 | Tamper-evident receipts | Done (hash chain, optional HMAC key) |
| D4 | GitOps via worktree | Done (user checkout untouched); post-merge verification = the `argocd_health` verifier configured on the agent |
| D5 | Taint tracking | Done |
| D6 | "Code" mode (scripting against a typed SDK) | **Deliberately not built** (bloat; see audit "what not to build") |

## Installation UX

| Item | Status |
|---|---|
| `harness` command (`init`, `serve`, `run`, `doctor`, `token`, `sessions`, `approvals`, `plugins`, `version`) | Done (`cli/main.py`) |
| Defaults packaged in the wheel; per-user config in `~/.harness` (`HARNESS_HOME`) | Done (`core/home.py`, `core/defaults/`); the old `config/` directory moved |
| No Vault/Docker needed: mode-600 `.env` written by `harness init`, Vault optional; secrets go to the OS keyring (`core/keystore.py`, `harness secret`, `--secret-store`) with a mode-600 file fallback | Done |
| `harness doctor` with per-check fixes and exit codes | Done (`cli/doctor.py`) |
| One-line installer (`install.sh`: uv → pipx → private venv; git/PyPI/wheel/path sources) | Done; tested with dry runs and a real clean-venv install |
| Wheel built, installed into an empty directory and run from another cwd | Covered by `tests/test_install_and_cli.py::TestWheel` |
| Publish to PyPI / GHCR on tag | **Not done** (next step); until then install from the git URL |

## Known limits

- The shell/dynamic-tool sandbox is only as strong as the backend: without `bwrap`/docker the process has the
  container's network. Set `HARNESS_SANDBOX` and install `bubblewrap`; `HARNESS_DYNAMIC_SANDBOX=bwrap` fails closed.
- SSRF checks resolve DNS before connecting; a DNS-rebinding race between check and connect is not pinned.
- No cost accounting (tokens only) and no multi-channel chat gateway.
- Docker and the live tests could not be exercised in the build environment; compose/Dockerfile are validated statically.

| Approvals with no setup: terminal prompt in `harness serve`/`run`, chained with API and Telegram (first answer wins) | Done: `core/gateway/channels.py`, `tests/test_terminal_approvals.py` |
