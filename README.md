# Harness Engine

**A general-purpose agent runtime that turns goals into *verified* outcomes, and can prove what it did.**

Most agent frameworks optimise what an agent *can do*. Harness Engine optimises whether the agent
*actually accomplished the goal* - safely, observably, and with a tamper-evident record - while staying
small and fast. DevOps/SRE (Kubernetes, ArgoCD, GitOps) is the first domain pack; the core is domain-neutral.

```text
GOAL → CONTEXT → AGENT → POLICY → APPROVAL → EXECUTE → VERIFY → RECEIPT → LEARN → MEMORY
```

- [Why Harness Engine](#why-harness-engine)
- [Feature overview](#feature-overview)
- [Architecture](#architecture)
- [How a run works](#how-a-run-works)
- [Safety model](#safety-model)
- [The event log](#the-event-log-source-of-truth)
- [Context, memory and skills](#context-memory-and-skills)
- [Plugins and extensibility](#plugins-and-extensibility)
- [Comparison with other agents](#how-it-compares)
- [Quick start](#quick-start) · [Configuration](#configuration) · [API](#api) · [Docker](#docker)
- [Testing](#testing) · [Project layout](#project-layout) · [Limitations](#known-limitations) · [Docs](#documentation)

---

## Why Harness Engine

The design goal is to keep the strengths of the well-known agents while fixing the things they leave to the
user. Each point below is something the code enforces and the test suite checks - not a roadmap item.

1. **Safety is structural, not a prompt.** Every tool - built-in, MCP, or written by the agent itself - goes
   through *one* `invoke()` path: capability check, argument validation, hooks, policy, approval, execution,
   output limiting, verification, receipt. There is no side door, so a new tool cannot forget to be safe.
2. **Risk depends on the arguments, not just the tool name.** Restarting a pod in `kube-system` is denied
   *before* any API call; syncing an ArgoCD app is R3 unless the app is explicitly listed as staging;
   `git push --force origin main` is blocked while `git status` runs freely.
3. **Approvals mean something.** They are bound to the SHA-256 of the exact arguments, restricted to an
   approver allowlist, scoped (once / session / always - never "always" for R3), and **an unanswered approval is a
   denial**, not a hang. The model is told why and adapts.
4. **"Done" is verified, not claimed.** A run is `success` only if it completed *and* its verification passed
   (file, HTTP probe, command, Kubernetes rollout, ArgoCD health, or an independent read-only verifier agent).
5. **Everything is an append-only, hash-chained event log.** Transcripts, receipts, streaming, resume, fork
   and search are projections of one table. Tampering is detectable; with an HMAC key it is unforgeable.
6. **Untrusted content is tracked.** Web pages, logs and MCP output are wrapped, sanitised, and *taint* the run:
   after untrusted content enters the context, mutating actions are raised one risk tier.
7. **Fast and light.** Streaming, parallel read-only tools, worker threads for blocking handlers, retries with
   failover, a stable cache-friendly prompt prefix, token-based compaction, and lazy imports (API cold import
   went from ~5.5 s to ~0.5 s).
8. **Composable.** Plugins own their tools, hooks and services through disposers. Reload is transactional,
   dependencies activate and deactivate reactively, and one broken plugin (or a bad self-written tool) is
   isolated instead of taking the process down.
9. **Small and inspectable.** The kernel is ~2,500 lines in 13 modules; everything domain-specific is a plugin.

---

## Feature overview

### Agent loop
- Streaming completions with tool-call assembly, and live `message_delta` events
- Errors are returned to the model as tool results (bad JSON, unknown tools, denials, exceptions, timeouts)
- Loop guard: three identical failing calls stop the run
- Parallel execution of consecutive read-only tools; mutating tools run in order; results keep call order
- Retries with jittered backoff, ordered model fallback chain, per-model credentials
- Budgets: tokens (shared with subagents), turns, wall-clock time; explicit outcomes (below)
- Interrupts: any number of steering messages, delivered in order at the next turn boundary
- Detached runs: closing a client never cancels a run; explicit cancel; crash recovery on restart
- Anthropic prompt-cache markers and a byte-stable prompt prefix (no timestamps, sorted tools)

### Safety and policy
- Risk tiers **R0-R4**, deny-by-default, argument-aware risk functions, hard blocklist
- Rules: `deny > ask > allow` with argument patterns (`deny:bash(git push --force*)`)
- Taint tracking after untrusted content
- Approval broker: live terminal prompt (in `harness serve` and `harness run` when stdin is a TTY, opt out with `HARNESS_TERMINAL_APPROVALS=off`), REST API and Telegram buttons all active at once, first answer wins, prompts asked one at a time; approver allowlist; timeout → deny
- Workspace confinement (symlink-safe, deny list for `.ssh`, `.aws`, `.kube`, `.env`, `secrets`), engine-source write protection
- SSRF guard on every redirect hop; secret-stripped environments for all child processes
- Shell command classifier (read-only pipelines auto-run, mutations ask, destructive commands are blocked) with optional `bwrap`/Docker sandbox
- Content scanning (prompt-injection phrases, exfiltration, credentials, invisible Unicode) for memory, skills, project instructions and self-written tools
- Fail-closed API authentication, scoped tokens, rate limiting, constant-time comparison

### Sessions, events and receipts
- SQLite (WAL) append-only event log with hash chain (+ optional HMAC)
- Resume, **fork at any event**, session-wide full-text search, tamper check endpoint
- `RunReceipt`: goal, model, every action with its policy decision, approver, argument hash, before/after state, verification, outcome, chain head
- File checkpoints for `write`/`edit` with a `/rewind` endpoint
- Outcomes: `completed | budget_exhausted | turn_limit | time_limit | error | cancelled | loop_guard | crashed`

### Context engineering
- Token-based compaction: prune old tool output first, then summarise; never splits a tool call from its result;
  pins the first user message; deterministic fallback if the summariser fails; memory flush before compaction;
  automatic retry on context-overflow errors
- Large outputs spilled to disk with a head+tail preview and a `read_spill` pager
- `AGENTS.md` project instructions (scanned), frozen curated-memory snapshot, skills index

### Memory, skills and learning
- `memory` tool (add/replace/remove/list) with size limits, duplicate rejection, scanning and provenance
- Full-text search of past sessions (`session_search`)
- Progressive-disclosure skills (`SKILL.md`): index in the prompt, bodies on demand, approval-gated `skill_manage`
- Verified runs can propose a skill; promotion is scanned, approved and validated; a weekly curator prunes poor agent-created skills (never human-authored ones)
- Memory consolidation ("dreams") that supersedes instead of deleting

### Tools
| Capability | Tools |
|---|---|
| `Read` | `read_directory`, `read` (paged), `glob`, `grep`, `read_spill`, `skills_list`, `skill_view`, `session_search` |
| `Write` | `write`, `edit` (exact replace, unique-match) - with checkpoints |
| `Shell` | `bash` - classifier, filtered env, optional sandbox |
| `Web` | `web_fetch`, `web_search` - SSRF-guarded, untrusted |
| `Memory` / `SkillsWrite` | `memory`, `skill_manage` |
| `Advisor` / `Subagents` | `advisor_consultation`, `spawn_agent` |
| `SelfEdit` / `Dynamic` | `write_and_register_tool` and the tools it registers |
| `MCP` | any MCP server's tools as `mcp__<server>__<tool>` |
| `DevOpsRead` / `DevOpsWrite` | kubectl, ArgoCD, GitOps pull requests |

### Orchestration and scheduling
- Subagents: typed profiles, capability intersection (never more than the parent), shared budget, concurrency and time limits, durable child sessions
- Phased workflows with checkpoints and resume; independent verifier agent
- Persistent cron (timezone-aware) and heartbeat runs (`HEARTBEAT.md`) restored on restart

### Operations
- OpenTelemetry traces and metrics (`harness_agent_run_count`, `resolve_policy_decision_count`, tool counts)
- Signed (HMAC-SHA256), retried webhooks; standard `logging` throughout
- Docker: non-root, health-checked, least-privilege Vault token, loopback-only ports
- CI: tests, `ruff`, `gitleaks`

---

## Architecture

```text
                 ┌────────────────────────── frontends ──────────────────────────┐
                 │  REST + SSE API (auth, scopes, rate limit)   CLI   Scheduler    │
                 └──────────────┬───────────────────────────────────┬─────────────┘
                                │ create/run/cancel/fork            │ cron/heartbeat
                        ┌───────▼────────┐                          │
                        │   RunManager   │◄─────────────────────────┘   detached tasks,
                        │  (core/runs)   │                              live buffer, recovery
                        └───────┬────────┘
                                │
   ┌────────────────────────────▼─────────────────────────────┐        ┌──────────────────┐
   │                     AGENT LOOP (core/loop)               │        │   EVENT LOG      │
   │  prompt builder → LLM (stream, retry, failover) →        │◄──────►│  SQLite WAL,     │
   │  tool calls → invoke() → results → compaction → repeat   │ append │  hash-chained    │
   │  interrupts · budgets · loop guard · verification        │        │  (core/eventlog) │
   └───────┬──────────────────────────────────┬───────────────┘        └────────┬─────────┘
           │ every tool call                  │ hooks                            │ projections
   ┌───────▼───────────────────────┐   ┌──────▼───────┐               receipts · SSE · resume
   │        invoke() (core/tools)  │   │   HookBus    │               fork · search · metrics
   │ capability → validate → hooks │   │ pre_tool ... │
   │ → POLICY → APPROVAL → run →   │   └──────────────┘
   │ limit/spill/taint → verify →  │
   │ ActionRecord                  │◄──── ApprovalBroker ◄── Telegram / API / terminal
   └───────┬───────────────────────┘
           │ ToolSpec registry (immutable snapshot per run)
   ┌───────▼─────────────────────────── PluginManager ────────────────────────────┐
   │ fs · web · shell · memory · skills · advisor · subagents · self-edit · devops │
   │ dynamic tools (out-of-process) · MCP servers · your plugins                   │
   │ each plugin: tools + hooks + services + disposers, lifecycle, dependencies    │
   └───────────────────────────────────────────────────────────────────────────────┘
```

**Kernel modules** (`core/`): `loop`, `tools` (registry + `invoke`), `policy`, `approvals`, `hooks`, `eventlog`,
`compaction`, `llm`, `engine`, `runs`, `settings`, `secrets`, `plugins/base`. Everything else - filesystem,
web, shell, DevOps, memory, skills, MCP - is a plugin registered through the same API you use.

### Design principles

| Principle | How it shows up |
|---|---|
| One path for everything | Single `invoke()`; MCP and self-written tools get the same policy as built-ins |
| Log is the truth | Receipts, streams, resume and fork are derived from the event log, never stored separately |
| Deny by default | Unknown tool, unknown capability, unregistered action, missing token → denied |
| Tighten, never loosen | Hooks and taint can only raise a decision; a `deny` can never be overridden |
| Effects have owners | Registrations return disposers; unload, reload and run teardown release them LIFO |
| Immutable per run | Each run takes a registry snapshot, so a reload never changes a run mid-flight |
| Errors are data | Failures are results the model can react to, not crashes |
| Lazy by default | Heavy optional packages load only when a tool that needs them is used |

---

## How a run works

```text
POST /sessions {agent, goal, verification?}  →  session (pending)
POST /sessions/{id}/run                       →  claimed atomically (pending → running), background task
```

1. **Context.** The system prompt is built in a *stable order*: base rules → agent prompt → `AGENTS.md` →
   frozen memory snapshot → skills index. The first user message carries the goal, retrieved memory (with
   provenance) and the session environment.
2. **Turn.** Drain queued interrupts → `before_turn` hooks → compaction check (token-based) → streaming LLM
   call with retry and failover.
3. **Tools.** For each tool call: parse arguments (errors become results) → `invoke()`:
   capability → schema validation → `pre_tool` hooks → argument-aware risk → policy → *(approval)* →
   pre-state snapshot → handler (thread or coroutine, with timeout) → post-state → output limit / spill /
   untrusted wrapping → optional post-condition → `post_tool` hooks → `ActionRecord`.
4. **Persist.** Assistant message, action and tool result are appended to the event log; results are returned
   to the model in call order.
5. **Finish.** No tool calls → `stop` hooks (may force continuation, e.g. "run the checklist") → verification →
   outcome → effect teardown → receipt built from the log → webhook.

### Status semantics

`success` requires **completed** and a verification that did not fail. Budget exhaustion, turn/time limits,
loop-guard stops, cancellation, errors and crashes are all `failure` with an explicit `outcome`, so dashboards,
webhooks and the learning loop never see false successes.

---

## Safety model

### Risk tiers

| Tier | Meaning | Default decision | Examples |
|---|---|---|---|
| R0 | Observe | allow | `read`, `kubectl_get_pods`, `git status` |
| R1 | Reversible local change | allow | `write`/`edit` in the workspace (checkpointed) |
| R2 | Operational | approval | `kubectl_restart_pod`, non-read-only `bash`, GitOps PR, staging sync |
| R3 | High impact | approval, never "always" | production ArgoCD sync, `write_and_register_tool` |
| R4 | Destructive | deny | protected namespaces, `rm -rf /`, `terraform destroy`, force-push to main |

### Decision pipeline (`core/policy.py`)

```text
hard blocklist (non-overridable) → DENY
rules: deny → ask → allow          (first match per class, argument patterns)
tier = tool.risk(args)             (namespace, app, command, path ...)
taint: untrusted content seen?     → mutating tiers +1 (capped at R3)
R0/R1 → ALLOW · R2/R3 → ASK · R4 → DENY
hooks may tighten (never loosen); remembered approvals apply to R2 only
ASK → broker: args-hash bound, approver allowlist, timeout → deny
```

### Prompt-injection and exfiltration defences
- **Untrusted wrapping:** `web_fetch`, `web_search`, `kubectl_logs`, `argocd_app_get`, MCP output and
  self-written tool output are wrapped in `<external ... trust="untrusted">`, stripped of zero-width and bidi
  characters, and taint the run.
- **Taint escalation:** after untrusted content, `write`, `edit`, memory writes and other mutating calls
  need approval (R1→R2, R2→R3).
- **Provenance:** memory written after untrusted content is stored as `external-fetched`.
- **Scanners:** memory writes, skills, `AGENTS.md`, self-written tools and skill candidates are scanned for
  injection phrases, exfiltration commands, credentials and invisible Unicode.
- **Child processes** never inherit `VAULT_*`, `HARNESS_*` or anything that looks like a key/token/secret.

### Filesystem and network
- All file tools resolve symlinks and must stay inside `HARNESS_WORKSPACE`; `.ssh`, `.aws`, `.kube`,
  `.gnupg`, `.docker`, `secrets`, `.env*` are denied; writes to the engine's own sources are refused.
- `web_fetch` allows only `http(s)` without credentials, blocks loopback, private, link-local, multicast,
  reserved, IPv4-mapped and metadata addresses, re-validates every redirect, caps size, converts HTML to text.
- The bash tool has an optional sandbox: `bwrap` (read-only root, workspace bind, no network) or Docker
  (`--network none`, read-only, capabilities dropped). A missing backend fails closed.

### Self-modification
`write_and_register_tool` requires the `SelfEdit` capability and a **R3 approval that shows the full source
and its SHA-256** (a diff when updating). Source is statically validated (import allowlist, no dunder access,
no `exec/eval/open`, only literals and function definitions at module level), must declare its own
`x-risk`, and is executed **out of process** with a filtered environment, CPU/memory/file rlimits and, when
available, a network-isolated `bwrap`. Each tool file is its own plugin; a bad file is quarantined and the rest
keep running. Agents need the `Dynamic` capability to see or call registered tools.

### API and secrets
- No default token: without `HARNESS_API_TOKEN` (or a Vault-stored one) every protected route returns 503.
- Constant-time comparison, per-token scopes (`sessions:write`, `approvals:write`, `admin` ...), sliding-window rate limit.
- Secrets resolve from the environment, then Vault (one shared client, TTL cache); LLM keys are resolved **per
  model**, so a key for one provider is never sent to another.
- Docker: the harness receives a read-only Vault token, never the root token or the raw provider key.

---

## The event log (source of truth)

Every run appends events to one SQLite table (`WAL`, migrated once per process):

```text
events(id, session_id, seq, parent_id, type, payload, prev_hash, hash, created_at)
types: user_msg · assistant_msg · tool_result · action · verification · compaction
       interrupt_queued · run_start · outcome ...
hash = sha256(prev_hash | session | seq | type | payload)      # HMAC if HARNESS_RECEIPT_KEY is set
```

Everything else is derived from it:

| Projection | How |
|---|---|
| Model transcript | Replay message events, apply the latest `compaction` event (summary, pinned message, pruned outputs); interrupted tool calls are repaired |
| Receipt | Actions + verification + outcome + chain head |
| SSE stream | Live buffer with event ids; `Last-Event-ID` resumes; after a restart the durable log is replayed |
| Resume | Append to the leaf and run again |
| Fork | Copy events up to any event id (never splits a tool call from its results), then add a new goal |
| Search | FTS5 over message text (`session_search`) |
| Integrity | `GET /sessions/{id}/verify-chain` recomputes the chain and names the first bad event |

---

## Context, memory and skills

- **Compaction** triggers on tokens (`window - reserve`), not message count. Order: prune large old tool
  outputs to stubs → summarise older history with a structured prompt (goal, constraints, progress, decisions,
  tool calls, files, next steps) → keep ≥ `HARNESS_KEEP_RECENT_TOKENS` of recent history. Cuts land only on
  user/assistant messages, the first user message is pinned, the summary is a user-role message, and a
  deterministic summary is used if the summariser fails. Compaction is logged as an event, so history stays replayable.
  A property test compacts 1,000 random tool-using transcripts and validates each one.
- **Spill:** tool output over the limit (8k characters default) is saved to disk; the model sees a head+tail
  preview and pages the rest with `read_spill`.
- **Memory:** a small, size-limited curated store per domain (`memory` tool) is injected as a *frozen snapshot*
  at session start (cache-friendly); retrieved hits are shown with authorship and provenance. Searching has no
  side effects; use counts are recorded only for entries actually shown.
- **Skills:** `SKILL.md` with frontmatter. Level 0: name and description index in the prompt. Level 1:
  `skill_view`. Level 2: files inside the skill directory. Agents can create/patch/delete their own skills
  (approval-gated and scanned); skill outcomes feed a curator.
- **Learning loop:** a verified run with enough actions can propose a skill; promotion is scanned, approved by a
  human, validated, and written under `data/skills`.

---

## Plugins and extensibility

```python
from core.plugins.base import Plugin
from core.tools import ToolSpec
from core.primitives.policy import RiskTier

class MyPlugin(Plugin):
    name = "mine"
    requires = ("db",)                     # activates only while a plugin provides "db"

    def register(self, ctx):
        ctx.tool(ToolSpec(
            "ping", "Ping a host", {"type": "object", "properties": {"host": {"type": "string"}},
                                    "required": ["host"], "additionalProperties": False},
            handler, capability="Network",
            risk=lambda args, run: RiskTier.R0 if args["host"].endswith(".internal") else RiskTier.R2,
            read_only=True, untrusted=True))
        ctx.hook("pre_tool", my_hook)
        ctx.provide("ping_service", service)      # dependents can require it

await engine.plugins.load(MyPlugin())            # transactional; same name = reload
```

- **Lifecycle:** `UNRESOLVED → INITIALIZING → ACTIVE ⇄ INACTIVE`, `FAILED`. Registrations are staged, validated,
  then committed atomically; disposers run LIFO on unload. A failed reload keeps the previous version running.
- **Reactive dependencies:** a plugin with unmet `requires` stays inactive; providers appearing or disappearing
  activate or deactivate dependents (dependents are disposed *before* their provider). Cycles are detected.
- **Tools are data:** `ToolSpec` declares capability, argument-aware risk, `read_only`/`parallel_safe`,
  output limit, untrusted flag, snapshot pair, post-condition, timeout, and an approval rendering.
- **Hooks:** `session_start`, `before_turn`, `pre_tool` (deny / ask / rewrite arguments), `post_tool`,
  `pre_compact`, `post_compact`, `stop` (force continuation), `session_end`. Shell hooks via `~/.harness/config/hooks.yaml`
  (JSON on stdin, exit code 2 blocks). Each hook has a time budget; a failing hook is skipped.
- **MCP:** `~/.harness/config/mcp.yaml` starts servers over stdio; tools become `mcp__<server>__<tool>`, are untrusted, R2 by
  default, and R0 for names in `read_only_tools`. A server that fails to start is a `FAILED` plugin, not a crash.
- **Subagents:** `spawn_agent` (or `SubagentSpec` in a workflow) runs a child session that can have at most the
  parent's capabilities, shares its token budget, and is bounded by depth, concurrency and time.

---

## How it compares

Comparison is based on each project's public documentation at the time of writing (see
[`docs/Harness_Engine_Audit.md`](docs/Harness_Engine_Audit.md) for sources). Where another agent is ahead, we say so.

| | Harness Engine | Claude Code | OpenClaw | Hermes Agent | Pi | DeepSeek Harness |
|---|---|---|---|---|---|---|
| Primary focus | Verified, audited operations | Interactive coding | Personal assistant / channels | Self-improving assistant | Minimal coding agent | Plugin-based harness |
| Tiered deny-by-default risk (R0-R4) | **Yes, argument-aware** | Rules + modes | Modes + allowlists | Pattern risk | No (containers) | Plugin |
| Approval bound to exact arguments, timeout → deny | **Yes** | Per-prompt | Yes | Yes (timeout) | No | Plugin |
| Verification gate before "done" | **Built in (registry + verifier agent)** | Stop/agent hooks | No | Skill section | No | No |
| Tamper-evident audit trail (hash chain / HMAC) | **Yes** | Transcript | No | No | No | Log |
| Per-action policy record + before/after state | **Yes** | No | No | No | No | No |
| GitOps PR route for changes (worktree) | **Yes** | No | No | No | No | No |
| Taint after untrusted content | **Yes** | Classifier | No | Scanning | No | No |
| Append-only log, resume, fork at any event | Yes | Yes | Yes | Yes | Yes (tree) | Yes |
| Token-based, cut-safe compaction | Yes | Yes | Yes | Yes | Yes | Yes |
| Hooks (rewrite/deny/force-continue) | Yes | **Richest (30+ events)** | Yes | Yes | Yes | Yes |
| MCP client | Yes | Yes | Yes | Yes | Extension | Yes |
| OS-level sandbox | Optional (`bwrap`/Docker) | **Built in** | Docker/SSH | Hardened containers | Container | **Landlock/Seatbelt** |
| Transactional plugin reload with disposers | Yes (no file watcher) | Plugins | Plugins | Skills | `/reload` | **Cordis, everything is a plugin** |
| Chat channels (WhatsApp, Slack ...) | No (Telegram approvals only) | Slack/IDE | **Many** | **20+** | No | Web UI |
| Interactive TUI / IDE integration | No (API + CLI) | **Yes** | Yes | Yes | **Yes** | Yes |
| Kernel size | ~2,500 lines | closed | large | large | very small | plugin-based |

**Where Harness Engine is different, on purpose.** It is an *operations* runtime: the things that make
production automation trustworthy - argument-aware policy, verified completion, audited receipts, GitOps-first
changes, out-of-band approvals - are core features rather than extensions. **Where it is not the right tool:**
if you want an interactive coding terminal, IDE integration, or a multi-channel chat assistant, the projects
above are more mature for that.

---

## Quick start

**One command** (installs the `harness` command in an isolated environment via `uv`, `pipx` or a private venv;
needs Python 3.11+ or `uv`):

```bash
curl -fsSL https://raw.githubusercontent.com/aniketpitre/Custom-Harness-Engine/main/install.sh | sh
harness init        # ~1 minute: provider, model, API key, generates the API token, optional Telegram
harness doctor      # checks the install and prints the exact fix for anything missing
harness serve       # API on 127.0.0.1:8000
harness run "List the files in the workspace"
```

Alternatives: `pipx install "harness-engine[runtime] @ git+https://github.com/aniketpitre/Custom-Harness-Engine.git"`,
`uvx --from git+https://github.com/aniketpitre/Custom-Harness-Engine.git harness doctor`, or Docker (below).
The installer needs no `git` (it installs the GitHub source archive) and accepts `HARNESS_SOURCE` (PyPI name, wheel,
archive/git URL or local path) and `HARNESS_EXTRAS`.

`harness init` writes everything to `~/.harness` (override with `HARNESS_HOME`): a mode-600 `.env` (provider key,
API token, optional Telegram), `config/agents.yaml` (yours to edit) and `data/` (database, checkpoints, skills).
No Vault, Docker or database server is required; Vault is an optional secrets provider. `harness init` keeps secrets in your OS keyring when one is available (`--secret-store auto|keyring|file`), and falls back to the mode-600 `.env` on headless machines; there is deliberately no passphrase-encrypted file, since a key stored next to the file adds no protection.

| Command | Purpose |
|---|---|
| `harness init` | First-run setup; idempotent (keeps your token and edited agents). `-y` with flags for scripts/CI: `--provider --model --api-key-env VAR --telegram-bot-token-env VAR ...` |
| `harness doctor [--online] [--json]` | Checks Python, permissions (`.env` must be 600), token, model key, agents, database, `git`/`gh`/`kubectl`/`argocd`/`bwrap`, optional Python extras, port; `--online` makes a tiny model call. Exit code 1 on failures |
| `harness serve [--host --port]` | Start the API (refuses to start without a token; warns on non-loopback binds) |
| `harness run GOAL [--agent] [--verify-file PATH TEXT]` | One-shot run; prints the receipt JSON; exit code reflects success |
| `harness token` | Print the API token (for `curl`) |
| `harness secret list\|set NAME\|delete NAME` | Manage secrets in the OS keyring (macOS Keychain, Windows Credential Locker, Secret Service/KWallet); values are never printed |
| `harness sessions [ID]` | Recent sessions / one session |
| `harness approvals list|approve|deny ID` | Manage approvals on a running server |
| `harness plugins` | Plugin states and tools |

```bash
curl -s -H "Authorization: Bearer $(harness token)" -X POST localhost:8000/sessions \
     -d '{"agent_id":"devops_agent","goal":"List the files in the workspace","run":true}'
```

Development checkout: `pip install -e ".[dev]"`. Optional extras: `telegram`, `vault`, `devops` (kubernetes, GitPython),
`mcp`, `otel`, `setup`, `runtime` (all integrations).

---

## Configuration

Precedence: real environment variables → `$HARNESS_HOME/.env` → `$HARNESS_HOME/config/settings.yaml` → packaged defaults.
Config files are looked up in `$HARNESS_HOME/config/`, then `./config/` (checkouts), then the defaults shipped in the wheel (`core/defaults/`).

| Variable | Purpose | Default |
|---|---|---|
| `HARNESS_API_TOKEN` / `HARNESS_API_TOKENS` | Admin token / JSON map of scoped tokens | **required** |
| `HARNESS_MODEL`, `HARNESS_FALLBACK_MODELS` | LiteLLM model and failover chain | `groq/openai/gpt-oss-120b` |
| `HARNESS_WORKSPACE` | Only directory file/shell tools may touch | working directory |
| `HARNESS_APPROVERS` | Allowed approvers (`telegram:123,api:*`) | any member of the approval chat |
| `HARNESS_APPROVAL_TIMEOUT` | Seconds until unanswered approvals are denied | `300` |
| `HARNESS_GITOPS_REPOS` | Repos the agent may open PRs against | the workspace |
| `HARNESS_STAGING_APPS` | ArgoCD app globs treated as staging (R2); others are R3 | none |
| `HARNESS_SANDBOX` | `none` / `bwrap` / `docker` for `bash` | `none` |
| `HARNESS_TOKEN_BUDGET`, `HARNESS_MAX_TURNS`, `HARNESS_MAX_SECONDS` | Run limits | `200000` / `30` / `3600` |
| `HARNESS_CONTEXT_WINDOW`, `HARNESS_RESERVE_TOKENS`, `HARNESS_KEEP_RECENT_TOKENS` | Compaction | `128000` / `16384` / `20000` |
| `HARNESS_LLM_TIMEOUT`, `HARNESS_LLM_RETRIES`, `HARNESS_STREAM` | Model calls | `120` / `3` / `true` |
| `HARNESS_MAX_PARALLEL_TOOLS`, `HARNESS_TOOL_TIMEOUT`, `HARNESS_TOOL_OUTPUT_LIMIT` | Tool execution | `6` / `120` / `8000` |
| `HARNESS_RECEIPT_KEY` | HMAC key for the event-log chain | unset |
| `HARNESS_WEBHOOK_ENDPOINTS`, `HARNESS_WEBHOOK_SECRET` | Signed completion webhooks | none |
| `HARNESS_MEMORY_LIMIT_CHARS`, `HARNESS_MEMORY_FLUSH` | Curated memory size, flush before compaction | `2200` / `true` |
| `HARNESS_HOME` | Home for `.env`, config and data | `~/.harness` |
| `HARNESS_DB_PATH`, `HARNESS_DATA_DIR` | SQLite location, data directory | `$HARNESS_HOME/data/memory.db`, `$HARNESS_HOME/data/` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Enable tracing | unset |

Agents are declared in `~/.harness/config/agents.yaml` (created by `harness init`):

```yaml
- id: sre
  domain: devops
  system_prompt: "You are an SRE."
  allowed_tools: [Read, DevOpsRead, DevOpsWrite, Memory]
  max_turns: 20
  token_budget: 100000
  deny_tools: [web_search]
  rules: ["deny:bash(git push --force*)", "ask:web_fetch"]
  verification: {type: argocd_health, app_name: web}
  verify_with_agent: true
```

---

## API

All routes except `/health` need `Authorization: Bearer <token>` and the listed scope.

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/health` | none | Liveness |
| GET | `/agents`, `/agents/{id}` | `agents:read` | Profiles and lifecycle state |
| POST | `/sessions` | `sessions:write` | Create (`run: true` starts it; optional `verification`, `environment`) |
| POST | `/sessions/{id}/run` · `/cancel` · `/interrupt` · `/fork` · `/rewind` | `sessions:write` | Control |
| GET | `/sessions/{id}` · `/events` · `/stream` · `/verify-chain` | `sessions:read` | State, event log, SSE (`Last-Event-ID`), tamper check |
| GET / POST | `/approvals` · `/approvals/{id}` | `approvals:read/write` | Pending approvals / decide |
| GET / POST / DELETE | `/cron` · `/cron/{id}/pause` · `/cron/{id}` · `/heartbeat` | `cron:*` | Persistent schedules |
| POST | `/memory/dream` | `memory:write` | Consolidate memory |
| GET / POST | `/skills` · `/sessions/{id}/skill/promote` | `skills:*` | Skills and promotion |
| GET / POST | `/admin/plugins` · `/admin/reload` | `admin` | Plugin status, reload agents and dynamic tools |

Stream event types: `message_delta`, `message`, `tool_call`, `tool_result`, `interruption_received`, `final_receipt`.

### Verification specs

```json
{"type": "file_content", "path": "out.txt", "expected_content": "ok"}
{"type": "http_probe", "url": "http://svc/health", "expected_status": 200, "contains": "healthy"}
{"type": "command", "command": "test -f out.txt"}
{"type": "k8s_rollout", "namespace": "web", "name": "web"}
{"type": "argocd_health", "app_name": "web"}
```

---

## Docker

`./start.sh` (or `docker compose up --build`) starts a dev Vault, seeds it, mints a **read-only** token for the
harness, and runs the API on `127.0.0.1:8000` as a non-root user with a separate `/workspace` volume. See
[`DOCKER.md`](DOCKER.md). Vault dev mode is not persistent and not for production.

---

## Testing

```bash
pytest                      # 380+ unit + integration tests: no network, no external services
pytest -m live tests/live   # real Vault / cluster / ArgoCD / GitHub (skipped by default)
ruff check .
```

Highlights: a security regression test for each audited finding (path traversal, SSRF incl. redirects,
unauthenticated access, self-edit gating, approval timeout/denial, protected namespaces), the compaction
property test (1,000 random transcripts), hash-chain tamper tests, real-subprocess MCP and dynamic-tool tests,
a real git-worktree GitOps flow against a local bare remote, plugin lifecycle tests, detached-run/SSE-resume API
tests, and a cold-import test proving heavy optional packages are not imported at startup. CI runs the suite,
`ruff` and `gitleaks`.

---

## Project layout

```text
core/                 kernel: loop, tools, policy, approvals, hooks, eventlog, compaction, llm, engine, runs,
                      settings, secrets, prompt, verifiers, receipts, subagents, confine, safety, skills
core/gateway/         api (FastAPI), cli, telegram, channels, webhooks, workflow
core/plugins/         plugin base/manager, memory, skills, advisor, subagents, self-written tools, MCP client
core/memory/          sqlite store, curator, dreamer
core/primitives/      pydantic models: Goal, ContextPacket, Evidence, Policy, ActionRecord, RunReceipt, ...
domains/generic/      fs, web, shell
domains/devops/       kubectl, ArgoCD, GitOps (worktree), snapshots, risk table, skills
core/defaults/        packaged defaults: agents.yaml, settings.yaml, *.example (mcp, hooks)
cli/                  the `harness` command (init, serve, run, doctor, ...)
install.sh            one-command installer (uv / pipx / private venv)
docs/                 design docs, audit, IMPLEMENTATION_STATUS.md, references
tests/                unit, integration and live tests
```

---

## Known limitations

- Shell and self-written-tool sandboxing is only as strong as the backend: without `bwrap` or Docker the process
  keeps the host network. Set `HARNESS_SANDBOX`; `HARNESS_DYNAMIC_SANDBOX=bwrap` fails closed.
- SSRF validation resolves DNS before connecting; DNS-rebinding between check and connect is not pinned.
- Token accounting only (no cost accounting); no multi-channel chat gateway; no TUI/IDE integration.
- No file watcher for plugins (use `POST /admin/reload`); subagents have no worktree isolation.
- The old Vault token that once lived in a test file is still in git history and must be rotated and purged.

## Documentation

- [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) - every audit finding and how it was addressed
- [`docs/Harness_Engine_Audit.md`](docs/Harness_Engine_Audit.md) - the full audit and comparison research
- [`docs/IMPLEMENTATION_PLAN_V3.md`](docs/IMPLEMENTATION_PLAN_V3.md), [`docs/general_purpose_agent_harness_architecture.md`](docs/general_purpose_agent_harness_architecture.md) - architecture background
- [`GUIDE.md`](GUIDE.md) - user guide · [`DOCKER.md`](DOCKER.md) - deployment
