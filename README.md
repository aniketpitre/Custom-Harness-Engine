# Harness Engine

A general-purpose, policy-gated agent runtime: it turns goals into **verified** outcomes and keeps an
auditable, tamper-evident record of everything it did. DevOps/SRE is the first domain pack.

```text
GOAL → CONTEXT → AGENT → POLICY → APPROVAL → EXECUTE → VERIFY → RECEIPT → LEARN → MEMORY
```

## What is different

- **Argument-aware, deny-by-default policy (R0–R4).** One `invoke()` path serves every tool - built-in,
  MCP and self-written. Rules (`deny > ask > allow`), a hard blocklist, per-call risk from the arguments
  (protected namespaces, production apps, shell command classification) and **taint**: after untrusted
  content (web pages, logs, MCP output) enters the context, mutating actions are raised one tier.
- **Approvals that mean something.** Bound to the SHA-256 of the exact arguments, an approver allowlist,
  `once / session / always` scopes (never `always` for R3), **timeout → deny**, Telegram or API channels.
- **Append-only, hash-chained event log** (SQLite WAL) is the single source of truth. Model transcript,
  receipts, SSE, resume, fork-at-any-event and session search are all projections of it. Optional HMAC
  (`HARNESS_RECEIPT_KEY`) makes the chain unforgeable without the key.
- **Detached runs.** Runs are background tasks; closing the SSE stream never cancels them. Resume a stream
  with `Last-Event-ID`; cancel explicitly. Sessions orphaned by a crash are failed on restart.
- **Verification is a gate.** A run is `success` only when it completed **and** its verification
  (file, HTTP probe, command, Kubernetes rollout, ArgoCD health, or an independent read-only verifier agent) passed.
- **Fast loop.** Streaming, parallel read-only tools, sync handlers in worker threads, retries with jittered
  backoff and model failover, stable prompt prefix + Anthropic cache markers, token-based cut-safe
  compaction (prune → summarise, never splits tool pairs), lazy imports of heavy optional packages.
- **Composable.** Plugins own their tools, hooks and services through disposers; reload is transactional,
  dependencies activate/deactivate reactively, and a failing plugin (or a bad self-written tool) is isolated.

## Layout

```text
core/           loop, tools (registry + invoke), policy, approvals, hooks, eventlog, compaction, llm,
                engine + plugin manager, runs (detached), scheduler, gateway (api, cli, telegram, webhooks)
core/plugins/   memory, skills, advisor, subagents, self-written tools (out-of-process), MCP client
domains/        generic (fs, web, shell) and devops (kubectl, argocd, gitops) packs, skills
config/         agents.yaml, settings.yaml, mcp.yaml.example, hooks.yaml.example
docs/           design documents, audit, implementation status
```

## Run it

```bash
pip install -e ".[dev]"                # or ".[runtime]" for the integrations only
export HARNESS_API_TOKEN=$(openssl rand -hex 32)   # required: the API fails closed without a token
export GROQ_API_KEY=...                # or any LiteLLM provider key; Vault is optional
python main.py                         # API on 127.0.0.1:8000
python -m core.gateway.cli "List the files in the workspace"   # one-shot, prints the RunReceipt
```

Docker (Vault + harness, least-privilege token, loopback only): `./start.sh` - see `DOCKER.md`.

## API (all routes need `Authorization: Bearer <token>`; scopes per route)

| Method | Path | |
|---|---|---|
| GET | `/health` | liveness (no auth) |
| GET | `/agents`, `/agents/{id}` | profiles with lifecycle state |
| POST | `/sessions` | create (`run: true` starts it); optional `verification` spec |
| POST | `/sessions/{id}/run`, `/cancel`, `/interrupt`, `/fork`, `/rewind` | control |
| GET | `/sessions/{id}`, `/events`, `/stream`, `/verify-chain` | state, log, SSE (`Last-Event-ID`), tamper check |
| GET / POST | `/approvals`, `/approvals/{id}` | pending / decide |
| GET POST DELETE | `/cron`, `/cron/{id}`, `/cron/{id}/pause`, `/heartbeat` | persistent schedules |
| POST | `/memory/dream`, `/sessions/{id}/skill/promote`, `/admin/reload`; GET `/skills`, `/admin/plugins` | |

## Capabilities (agent `allowed_tools`)

`Read` (read_directory, read, glob, grep, read_spill, skills, session_search) · `Write` (write, edit with
checkpoints) · `Shell` (bash: classifier + optional bwrap/docker sandbox) · `Web` (SSRF-guarded fetch/search) ·
`Memory` · `Advisor` · `Subagents` · `SkillsWrite` · `SelfEdit`/`Dynamic` · `MCP` · `DevOpsRead` · `DevOpsWrite`.
`Generic` = Read + Write + Web + Memory.

## Tests

```bash
pytest                 # unit + integration (no network, no external services)
pytest -m live tests/live   # needs real Vault / cluster / ArgoCD / GitHub
ruff check .
```

See `docs/IMPLEMENTATION_STATUS.md` for how each audit finding was addressed and the known limits.
