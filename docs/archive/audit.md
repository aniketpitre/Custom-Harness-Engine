# Harness Engine — Full Technical Audit & Competitive Gap Analysis

**Subject:** `PenkoPerry-Harness-main` (uploaded 28 Sep 2026)
**Compared against:** Claude Code (v2.1.28x), OpenClaw, Hermes Agent (Nous Research), Pi coding agent, DeepSeek Harness (`dsh`, built on Cordis) and the Cordis paper *A Programming Paradigm for Spatiotemporal Composability*
**Scope:** read-only review. No code in your repository was changed.

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [How this audit was done (and its limits)](#2-how-this-audit-was-done-and-its-limits)
3. [What you built: architecture walkthrough](#3-what-you-built-architecture-walkthrough)
4. [The real runtime flow, step by step](#4-the-real-runtime-flow-step-by-step)
5. [P0 findings: security and correctness](#5-p0-findings-security-and-correctness)
6. [P1 findings: robustness of the agent loop](#6-p1-findings-robustness-of-the-agent-loop)
7. [Performance: why it is slower and costlier than it should be](#7-performance-why-it-is-slower-and-costlier-than-it-should-be)
8. [Built but not wired: dead weight inventory](#8-built-but-not-wired-dead-weight-inventory)
9. [Test suite assessment](#9-test-suite-assessment)
10. [Reference agent deep dives and what to borrow](#10-reference-agent-deep-dives-and-what-to-borrow)
11. [Master gap matrix](#11-master-gap-matrix)
12. [Cordis / DeepSeek paper mapping](#12-cordis--deepseek-paper-mapping)
13. [Where you are genuinely ahead](#13-where-you-are-genuinely-ahead)
14. [Target architecture: smaller core, no lost features](#14-target-architecture-smaller-core-no-lost-features)
15. [Prioritised roadmap with acceptance criteria](#15-prioritised-roadmap-with-acceptance-criteria)
16. [File-by-file notes](#16-file-by-file-notes)
17. [Repository cleanup list](#17-repository-cleanup-list)
18. [Sources](#18-sources)

---

## 1. Executive summary

**Bottom line.** Your design direction is strong, and in two respects it is ahead of every agent you're comparing against:

- the explicit **R0–R4 risk table that denies anything it doesn't recognise**;
- **immutable run receipts** carrying per-action policy decisions and before/after state snapshots, with production changes routed through **GitOps pull requests** instead of direct mutation.

The implementation does not yet deliver the design:

| Area | State |
|---|---|
| Core agent loop | Works for the happy path. Any tool error, denied approval or malformed argument JSON **kills the whole run**. |
| Safety model | The risk table is correct, but it only covers some tools. **Self-written tools, generic file tools and web fetch bypass it.** The API has **no authentication**. |
| Context management | Compaction triggers on **message count (12)**, not tokens. It **splits tool calls from their results** (reproduced) and discards the record of which tools were called. |
| Memory | **Never written during runs.** Retrieved memories are **never put in the prompt**. The domain filter can never match (reproduced). |
| Skills | `SKILL.md` files are **never loaded**. Skill promotion is **never called**. |
| Sessions | Fork and resume **don't work end to end**: receipts are wiped on status updates and history is never saved (reproduced). |
| Orchestration | **Crashes on a real database**: the checkpoint table is never created (reproduced). |
| Composability (Cordis) | The `EffectStack` exists, but **nothing ever pushes onto it**. `LifecycleState` never changes. `reload_registry()` has no caller. |
| Observability | Tracing **never initialises**, because of an import-order bug. The dashboard charts metrics that are never emitted. |
| Performance | No streaming, no prompt caching, sequential tools, blocking I/O on the event loop, an extra LLM call every few turns, a Vault round trip on every secret read. |

**Estimated effort to reach parity on the core** (not counting channels or UI): a focused refactor around a **tool registry, policy engine, append-only session log and hook bus** would *remove* code overall. §14 describes the design and §15 the order.

---

## 2. How this audit was done (and its limits)

- **Read in full:** all 76 Python files, `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, `start.sh`, the `config/*` files, `docker/init-vault.sh`, both `SKILL.md` files, every test file, and all planning documents: `README`, `GUIDE`, the checkpoints, the v2 architecture and plan, the Pi analysis and plan, the Cordis gap-analysis prompt, the general architecture, the full implementation plan and the Managed Agents deep dive (by outline).
- **The paper:** *A Programming Paradigm for Spatiotemporal Composability* (Shi, Zhang, Cui; Peking University and DeepSeek-AI), in particular §1.2.2 (self-evolving agent harnesses), §5.1 (effect tracking, `ctx.effect`) and §5.2.2 (hot module replacement).
- **External research:** the official documentation for each reference agent (sources in §18).
- **Test execution: not possible.** This session's network policy blocks `pypi.org`, so the dependencies could not be installed. Instead:
  - the most important bugs were **reproduced in isolation**, using the standard library and the repository modules that import without third-party packages (`core/memory/store.py`, plus path and slicing logic copied verbatim);
  - every other finding is **static analysis tied to exact file and line**, and was re-read at least twice.
- **Confidence labels used below:**
  - **Reproduced** — demonstrated by running code.
  - **Certain** — deterministic from reading the code.
  - **Likely** — depends on the environment or provider behaviour.

---

## 3. What you built: architecture walkthrough

### 3.1 Layout

```
core/
  agent_engine.py        923 lines — loop, tool schemas, dispatch, compaction, spill, effects
  gateway/api.py         FastAPI control plane (sessions, stream, interrupt, fork, cron, dream)
  gateway/cli.py         one-shot CLI run → prints RunReceipt JSON
  gateway/telegram.py    approval gate (inline buttons, long-poll)
  gateway/webhooks.py    POST receipts to HARNESS_WEBHOOK_ENDPOINTS
  gateway/workflow.py    hard-coded two-phase security audit workflow
  memory/store.py        SQLite: memory_entries + FTS5, sessions, approval_queue, analytics
  memory/dreamer.py      LLM consolidation of agent-created memories
  memory/curator.py      skill success/failure metrics + pruning
  orchestration/executor.py  phased parallel subagents + checkpoints
  plugins/registry.py    dynamic (self-written) tool loader
  primitives/*.py        Pydantic models: Goal, ContextPacket, Evidence, Policy, ActionRecord,
                         RunReceipt, Verification, CandidateSkill, Orchestration, AgentProfile
  registry.py            AgentRegistry + LifecycleState
  secrets.py             HashiCorp Vault KV v2 reader
  snapshots.py           execute_with_snapshot(pre, action, post)
  verification.py        verify_file_content
  background/scheduler.py APScheduler cron → execute_session
domains/
  devops/                kubectl + argocd tools, GitOps PR action, pod snapshots, risk table, skills
  generic/tools.py       grep, glob, edit(overwrite), web_fetch, web_search(DDG scrape)
config/                  agents.yaml, settings.yaml, dashboard.json
```

### 3.2 Concepts, and whether each is live

| Concept | Defined in | Live in the runtime? |
|---|---|---|
| Goal / ContextPacket | `primitives/goal.py`, `context.py` | Yes, but `memory_hits`, `evidence` and `recent_history` are effectively unused |
| Risk tiers R0–R4 + default deny | `primitives/policy.py`, `devops/policy_table.py` | Partly: only kubectl, argocd, gitops and read_directory go through it |
| Human approval | `gateway/telegram.py` | Yes, for R2/R3 DevOps actions and self-written tools |
| ActionRecord / RunReceipt | `primitives/execution.py` | Yes |
| Snapshots before/after | `core/snapshots.py`, `devops/snapshots.py` | Only for `kubectl_restart_pod` |
| Verification | `core/verification.py` | Only when the CLI passes a file-content check; never on the API path |
| Learning (candidate skill) | `primitives/learning.py` | A draft is produced; promotion is never called |
| Memory (FTS5) | `memory/store.py` | Searched but never injected; never written |
| Dreamer / curator | `memory/dreamer.py`, `curator.py` | Dreamer via `POST /memory/dream` (nothing to consolidate); curator never called |
| Just-in-time tool loading | `agent_engine.py` `load_skill` | Yes |
| Self-editing tools | `plugins/registry.py` | Yes (see P0-1 and P0-2) |
| Compaction | `agent_engine._compact_history` | Yes (see P0-9) |
| Fork | `api.py /fork` | Endpoint exists; the end-to-end flow is broken (P0-11) |
| Effects (Cordis) | `EffectStack` / `EffectScope` | Scope is created; nothing is ever pushed |
| Lifecycle (Cordis) | `LifecycleState` | Always ACTIVE; never transitions |
| Hot reload | `main.reload_registry` | No caller, no endpoint |
| Orchestration | `orchestration/executor.py` | Crashes on a real database (P0-8) |
| Scheduling | `background/scheduler.py` | In memory only; lost on restart |
| Tracing | `init_tracing` | Never initialises (P0-7) |

---

## 4. The real runtime flow, step by step

Using `GET /sessions/{id}/stream`, the main path:

1. **`POST /sessions`** inserts a `pending` row. No authentication. `environment` is stored but never used.
2. **`GET /sessions/{id}/stream`:**
   1. Opens SQLite. `init_db()` runs the full `CREATE TABLE`/`TRIGGER` script plus an `ALTER TABLE` on every call.
   2. Checks the status is pending or running. The check and the update are not atomic, so two clients can start two concurrent runs.
   3. `update_session(..., "running")`. This **sets `run_receipt` to NULL** as a side effect (P0-11).
   4. `build_context()` creates a `Goal` with the default domain `general` and calls `search_memory(conn, text, "general")`.
3. **`run_agent_generator`:**
   1. Picks a model: profile, then `HARNESS_MODEL`, then `GROK_MODEL`, then `groq/openai/gpt-oss-120b`.
   2. Reads the API key with `get_secret("groq","api_key")`, which tries the `llm` path first. Each call creates a fresh Vault client and authenticates.
   3. Messages are `[system, user(goal + live_state + evidence)]`. **Memory hits are not included.**
   4. `load_dynamic_tools()` clears the **global** schema and callable lists and re-imports every file in `core/plugins/dynamic/`.
   5. The tools are `load_skill`, `write_and_register_tool` and every dynamic tool, **regardless of the agent profile**.
   6. The system prompt gets a "[JIT Context]" note listing the allowed categories.
   7. The loop runs while `turn_count < 30` and `total_tokens < 200_000`:
      - fetch and clear the interruption from SQLite (a queue of one; later interrupts overwrite earlier ones);
      - make a non-streaming `litellm.acompletion` call;
      - add up `usage.total_tokens`;
      - **if `len(messages) >= 12`, compact** (an extra LLM call);
      - no tool calls → yield the final receipt and stop;
      - otherwise append the assistant message and **run each tool call in turn**:
        - `load_skill` → append schemas to `tools`;
        - anything else → `_dispatch_tool` → **raises on any error**.
   8. After 30 turns it raises `RuntimeError("Grok exceeded the maximum number of tool turns (8)")`. The message is wrong on both counts: it isn't Grok, and the limit is 30.
4. **Back in `stream_session`:** builds a `RunReceipt` (**without `message_history`**) and marks it `success` whenever verification is `None`. Saves it, then fires a webhook task without keeping a reference to it.
5. **If the client disconnects,** `CancelledError` marks the session `failure`. The run is tied to the HTTP connection.

The CLI path (`python -m core.gateway.cli "<goal>"`) is the same, except the tools are hard-coded to `["Read","DevOpsRead","DevOpsWrite"]` and there is no session ID, so interruptions are impossible.

The scheduler path runs `execute_session`, which calls `run_agent` without a session ID. So cron runs can't be interrupted or streamed, and their receipts also lack history.

---

## 5. P0 findings: security and correctness

Each finding gives: **evidence → impact → fix**.

### P0-1: Self-modification tool exposed to every agent; approver approves blind; result runs as R0 forever (Certain)

**Evidence.** `core/agent_engine.py:418-421`:

```python
from core.plugins.registry import load_dynamic_tools, dynamic_tool_schemas
load_dynamic_tools()
tools = [LOAD_SKILL_TOOL, WRITE_AND_REGISTER_TOOL]
tools.extend(dynamic_tool_schemas)
```

This runs unconditionally. There is no `allowed_tools` check for `write_and_register_tool` in `_dispatch_tool` (lines 636-654), nor for dynamic tools (lines 656-669).

The approval text (line 641) only includes the name:

```python
description=f"Self Modify: Write Tool '{arguments.get('tool_name')}'",
```

Dynamic tool execution (line 659):

```python
policy_decision = PolicyDecision(tool="dynamic", action=name, decision="ALLOW", risk_tier=RiskTier.R0, ...)
```

**Impact.**
- `read_only_explorer`, declared read-only in `agents.yaml`, can propose arbitrary Python.
- The human sees only a name and approves without seeing the code.
- After approval, the code runs **inside the engine process**: it can read Vault tokens from the environment and the kubeconfig. It runs **at R0 for every future session and every agent**, because the plugin directory is global and reloaded at every run start.
- This single path turns an R3 gate into permanent arbitrary code execution.

**Fix.**
1. Put self-modification behind an explicit capability (for example `SelfEdit` in `allowed_tools`) and check it at dispatch.
2. The approval must show the **full source**, a **diff against any existing file**, and a hash. Record the hash in the ActionRecord.
3. A registered tool must declare its own risk tier in `TOOL_SCHEMA` (say `x-risk: R1`). Treat undeclared as R4, which means deny. Run it through the same policy engine as everything else.
4. Execute dynamic tools **out of process**: a subprocess with a timeout, no inherited secrets and a working directory limited to the workspace. Never `import` them into the engine.
5. Scope dynamic tools **per agent**, or per session until promoted.

### P0-2: Path traversal in `register_new_tool` (Reproduced)

**Evidence.** `core/plugins/registry.py:39-43`:

```python
filepath = DYNAMIC_PLUGINS_DIR / f"{name}.py"
filepath.write_text(code)
```

Reproduction: `Path("core/plugins/dynamic")/"../../gateway/api.py"` resolves to `core/gateway/api.py`.

**Impact.** A tool name like `../../gateway/api` **overwrites the API server's own source**. Top-level module code then runs on the next `load_dynamic_tools()`, before any validation.

**Fix.** Validate `name` against `^[a-z][a-z0-9_]{1,48}$`. Resolve the path and confirm it stays inside the directory. Refuse to overwrite existing files unless it is an explicit, approved update. Parse the source with `ast` first, and reject top-level statements other than imports, the schema and the `execute` definition.

### P0-3: Generic tools bypass the sandbox you built for `read_directory` (Certain)

**Evidence.**
- `_read_directory` (`agent_engine.py:902-923`) blocks `.ssh`, `.aws`, `.kube` and `secrets`, and anything outside the working directory.
- `domains/generic/tools.py` has none of that:
  - `tool_grep(pattern, path)` runs `grep -rnI <pattern> <path>` with any `path`, for example `/root/.ssh`. A `pattern` starting with `-` is read as a grep option.
  - `tool_glob(pattern)` accepts `/**/*` and lists the whole filesystem.
  - `tool_edit(path, content)` writes **any path**, including `~/.bashrc`, the engine's own source, or the dynamic plugin directory (another way into P0-1 that needs no approval).
  - `tool_web_fetch(url)` fetches any URL: `http://169.254.169.254/latest/meta-data/` (cloud metadata), `http://127.0.0.1:8200/v1/...` (your Vault), or Kubernetes API internals.
- All of them are dispatched at **R1 ALLOW** with no approval (`agent_engine.py:813-816`).

**Impact.** Any agent with `Generic` can read secrets, change code and reach internal services, and nothing records a policy decision above R1.

**Fix.**
1. One shared `resolve_workspace_path(p)` used by *every* file tool: resolve symlinks, require the path to stay inside the workspace roots, and apply a deny list (credential directories and the engine's own directories).
2. `grep`: pass `--` before the pattern, confine the path, and prefer `rg --json` with a result cap.
3. `web_fetch`: resolve DNS and reject private, loopback, link-local and metadata ranges (RFC 1918, 127/8, 169.254/16, ::1, fc00::/7). Allow http/https only. Cap the response size. Convert HTML to text (Markdown) instead of returning up to 100k characters of raw HTML. Label the result as untrusted external content (see P1-8).
4. `edit`: make it an R2 action by default, or R1 inside the workspace and R3 outside.

### P0-4: Control-plane API has no authentication and listens on every interface (Certain)

**Evidence.**
- `core/gateway/api.py` has no dependency injection for authentication on any route.
- `main.py`: `uvicorn.run(app, host="0.0.0.0", port=8000)`.
- `docker-compose.yml` uses `network_mode: host`.

**Impact.** Anyone who can reach port 8000 can:
- create sessions for `devops_agent` and trigger DevOps writes (which request Telegram approval, causing approval fatigue and spam);
- schedule cron jobs (`POST /cron`), which also run without authentication;
- inject instructions into running sessions (`/interrupt`) — prompt injection by design;
- read every session's receipts, including raw tool outputs (`GET /sessions/{id}`);
- trigger an LLM spend (`/memory/dream`).

**Fix.** Bind to `127.0.0.1` by default. Require a bearer token (or mTLS) as a FastAPI dependency on every route. Add per-token scopes (`sessions:write`, `cron:write`, `admin`). Rate-limit. OpenClaw's gateway is the model here: it binds to loopback by default, requires an authenticated WebSocket handshake with a declared role, and requires device pairing for non-local clients.

### P0-5: The Telegram approval gate is weak in four ways (Certain)

**Evidence.** `core/gateway/telegram.py:12-56`.
1. **No approver check.** `callback_query.from_user.id` is recorded but never compared with an allowlist. Anyone in the approval chat (or a group it's added to) can approve an R3 production sync.
2. **No timeout.** `while True:` long-polls forever. The run, and the HTTP stream, hang indefinitely.
3. **Concurrent approvals conflict.** Each call fast-forwards `offset` past all pending updates (lines 17-18), and advances it past non-matching callbacks (line 43). Two simultaneous approvals will consume each other's button presses, so one waits forever.
4. **It's polling, not a webhook,** and it creates a new `Bot` and makes two Vault reads per request.

**Impact.** The central safety promise, "R2/R3 require human approval", can be satisfied by the wrong human, or can deadlock.

**Fix.**
- One long-lived Telegram consumer (webhook, or one polling task) that sends callbacks to futures keyed by action ID. Your `_pending_approvals` dict is already declared at line 8 but unused.
- An `approvers` allowlist per risk tier.
- A timeout (Hermes uses 300 s) with **deny as the fallback**.
- Scopes: *once*, *this session*, *always* (saved as a rule).
- Record approver identity **and** the exact arguments hash in the ActionRecord.
- Also expose approvals through the API (`GET /approvals`, `POST /approvals/{id}`) so Telegram isn't a single point of failure. Your unused `approval_queue` table is the right storage for this.

### P0-6: The kube-system protection runs after the damage (Certain)

**Evidence.** `agent_engine.py:734-749`. `execute_with_snapshot(kubectl_restart_pod, ...)` runs first and deletes the pod. Only afterwards:

```python
if arguments.get("namespace") == "kube-system":
    ... rollback_pod_restart(...)   # this only *waits* for the controller
    raise PermissionError("Rollback triggered automatically ...")
```

`rollback_pod_restart` does not undo anything. It waits up to 120 s for the controller to recreate the pod, and that wait blocks the event loop (P1-4).

**Impact.** A restart in `kube-system` (coredns, kube-proxy and so on) is executed, **and the run crashes afterwards**. The receipt then reports a "rollback" that never happened.

**Fix.** Make protected namespaces a **policy** input: `risk(tool, args)` returns R4 for `kube-system`, so the call is denied before it runs. In general, risk must be computed from **arguments**, not just `(tool, action)`.

### P0-7: Tracing never turns on; a clean install fails to import (Certain)

**Evidence.** `agent_engine.py`:

```python
44 from opentelemetry.instrumentation.litellm import LiteLLMInstrumentor
46 def init_tracing():
47     try:
48         otlp_endpoint = get_secret("otel", "endpoint")   # get_secret not yet imported
...
57     except Exception:
58         pass
61 tracer = init_tracing()
63 from core.secrets import get_secret
```

- `get_secret` is referenced before it is imported. The `NameError` is swallowed, so a no-op tracer is **always** returned and `LiteLLMInstrumentor().instrument()` never runs.
- `opentelemetry-instrumentation-litellm` is imported at module level but **isn't in `pyproject.toml`**. The Dockerfile does `pip install .`, so importing `core.agent_engine` raises `ModuleNotFoundError` unless that package was installed by hand. That breaks the API, the CLI and the Docker image.
- `config/settings.yaml` already contains `otel.endpoint`, but it's never read. The engine looks in Vault for it instead.

**Fix.** Move the import above, or better, read `OTEL_EXPORTER_OTLP_ENDPOINT` from the environment (the standard). Add the instrumentation package to the dependencies, or make that import optional with a `try`. Emit the metrics your `dashboard.json` expects (`harness_agent_run_count`, `resolve_policy_decision_count`); today nothing emits them.

### P0-8: Orchestration crashes on a real database (Reproduced)

**Evidence.** `store.py:180-205` reads and writes `workflow_checkpoints`, but `init_db()` never creates it. Reproduction: `OperationalError: no such table: workflow_checkpoints`.

`tests/domains/devops/test_orchestration.py` creates the table by hand in its fixture, so the test passes while production fails.

**Fix.** Add the table to `init_db()`. Rule for the future: **fixtures must use `init_db(tmp_path)`, never hand-written DDL.**

Other orchestration issues:
- Subagents are called with no `AgentProfile`, so they get the generic system prompt.
- There is no session ID, no shared token budget and no concurrency cap.
- `context.live_state` is **mutated** across phases.
- Earlier results are passed as a Python `repr` blob.

### P0-9: Compaction corrupts the conversation (Reproduced)

**Evidence.** `_compact_history` (`agent_engine.py:369-396`) keeps `messages[-3:]` as the tail. Reproduction with a typical tool-using transcript: the kept tail was

```
[('tool','a2'), ('tool','b2'), ('assistant' with tool_calls)]
```

That is, **tool results without the assistant message that issued them, and an assistant tool call without its results.** OpenAI-compatible APIs and Anthropic reject both shapes (orphaned `tool_call_id`, or `tool_use` without a matching `tool_result`). Some gateways silently drop or reorder messages instead.

More problems:
- The summariser input is `f"{role}: {content}"`. For assistant tool-call messages `content` is often `None`, so **which tools were called, and with what arguments, never reaches the summary**, even though the prompt says "preserve all tool calls".
- The summary is inserted as a second `system` message mid-conversation. Some providers reject this, and LiteLLM merges it differently per provider.
- Trigger: `len(messages) >= 12` (`agent_engine.py:460`). After compaction there are 5 messages, so it fires again 2–4 tool turns later. See §7.1 for the cost.
- The plan document (Phase 21) specified a 50,000-token threshold. The implementation doesn't follow it.

**Fix: compaction done properly (what Pi, OpenClaw and Hermes all do):**
1. **Trigger on tokens:** when estimated context exceeds `window − reserve` (Pi: reserve 16,384). Hermes compacts at 50% of the window, OpenClaw near the limit and also on a context-overflow error followed by a retry.
2. **Cut point:** walk backwards, keeping about 20k tokens of recent history (Pi and OpenClaw default: `keepRecentTokens = 20000`). **Only cut at a user message or at an assistant message without pending tool calls.** Never between a call and its result.
3. **Prune tool outputs first:** replace old tool results with a stub such as `[output of kubectl_logs pruned; 18,203 chars; spill: path]`. It costs no LLM call and often frees most of the space.
4. **Structured summary:** goal, constraints, decisions with reasons, done / in progress / blocked, files and resources touched, **tool calls with key arguments**, next steps. Pi's format is a good template.
5. **Pin the first user message** (Hermes pins the first three non-system messages).
6. Put the summary in a **user-role** message, `"<summary>…</summary>"`, not a second system message.
7. **Before compacting, ask the agent to write durable facts to memory** (OpenClaw's memory flush).
8. Save a `compaction` event in the session log (§14.3) so the full history is still replayable.

### P0-10: Any tool error kills the run (Certain)

**Evidence.** `agent_engine.py:500-543`. `json.loads(tool_call.function.arguments)` has no `try`. `_dispatch_tool` raises `PermissionError` for denials, "not allowed", "approval denied" and the kube-system case, and lets tool exceptions through (for example `KeyError` on a missing argument, or Kubernetes `ApiException`). Nothing in the loop catches them.

**Impact.** The model never gets the chance to adapt ("approval denied — propose a PR instead"). One bad argument or a flaky kubectl call ends the session as a failure. Every reference agent returns errors to the model as tool results.

**Fix.**

```python
try:
    args = json.loads(tc.function.arguments or "{}")
    result, record = await registry.invoke(tc.id, tc.function.name, args, ctx)
    is_error = False
except PolicyDenied as e:
    result, record, is_error = f"DENIED by policy: {e.reason}", e.record, True
except ApprovalRejected as e:
    result, record, is_error = f"Human rejected this action: {e.note or 'no reason given'}", e.record, True
except json.JSONDecodeError as e:
    result, record, is_error = f"Invalid JSON arguments: {e}", None, True
except Exception as e:
    result, record, is_error = f"Tool error ({type(e).__name__}): {e}", None, True
messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
```

Also add a **consecutive-error breaker**: for example, stop after 3 identical failures in a row, as a loop guard.

### P0-11: Fork and resume don't work end to end (Reproduced)

**Evidence.**
1. `update_session(conn, id, status)` with no receipt writes `run_receipt = NULL` (`store.py:235-245`). Reproduced: after `update_session(..., "running")` the stored receipt is `None`. `stream_session` calls exactly that before running, so a forked session's copied history is **wiped from the database** before the run, and only survives in a local variable.
2. `RunReceipt` has a `message_history` field, but neither `api.py` path nor `cli.py` fills it. Every saved receipt has `message_history: null`, so forking a real completed session copies no conversation.
3. When `initial_history` is present, `run_agent_generator` uses it as-is and **never appends the new goal** (`agent_engine.py:408-417`). The fork's `goal_override` is therefore ignored by the model.
4. The fork copies the *whole* receipt. There's no "fork at turn N", so it isn't a tree the way the plan describes.
5. `test_phase22_fork.py` passes only because it writes `message_history` into the database by hand.

**Fix.** Replace receipts-as-history with an **append-only event log** (§14.3). Resume means rebuilding messages from events. Fork means a new session whose `parent_event_id` is any event ID. The receipt becomes a *projection* of the log, not the source of truth. This is exactly what Pi's JSONL tree (`id`/`parentId`) and DeepSeek Harness's append-only log do.

### P0-12: Wrong success status (Certain)

**Evidence.** `api.py:100` and `:272`: `status="success" if getattr(verification, "passed", True) else "failure"`. With `verification=None` this is always `success`, including when the run ended with `final_text="Execution blocked: Token budget exceeded"`.

**Impact.** Webhooks, dashboards and the learning loop all see false successes.

**Fix.** Use an explicit `outcome` enum, set by the loop: `completed | budget_exhausted | turn_limit | error | cancelled | awaiting_approval`. Separately, `verified: true | false | null`. Status `success` only when completed **and** (verified or no verification requested). The learning loop should only draft skills from `completed && verified`.

### P0-13: Credential committed to the repository (Certain)

**Evidence.** `tests/phase7/test_otel_init.py` sets `os.environ["VAULT_TOKEN"] = "c6869775…6803f4"` (a 64-hex token) and hard-codes the path `/workspaces/PenkoPerry-Harness`.

**Fix.** **Rotate that Vault token now**, remove it from git history (`git filter-repo`), and add a secret scanner such as `gitleaks` as a pre-commit hook and in CI.

---

## 6. P1 findings: robustness of the agent loop

### P1-1: No retries, backoff or model fallback

`litellm.acompletion` is called once per turn. A 429, 5xx or timeout from Groq kills the run. `settings.yaml` defines `model.fallback: groq/compound`, but nothing reads that file.

**Fix.** Wrap the model call: exponential backoff with jitter on 429, 5xx and timeouts (3 attempts), then fail over to the fallback chain (OpenClaw and Hermes both do automatic failover). On a context-overflow error, compact and retry once (OpenClaw's behaviour).

### P1-2: API key is hard-wired to the "groq" secret path

`api_key = get_secret("groq", "api_key")` is used for **every** provider: the main loop, the advisor, compaction and the dreamer. It works only because `secrets.py` quietly redirects `groq/api_key` to the `llm` path. If you use two providers (say an Anthropic main model and a Groq compaction model), the wrong key is sent to one of them. `fix_engine_secret.py` shows you noticed this, but the fix was never applied.

**Fix.** Resolve credentials **per model**: `provider = model.split("/")[0]`, then `secret(f"llm/{provider}")`. Or leave it to LiteLLM's standard environment variables. Cache secrets (P1-6).

### P1-3: Tool calls run one after another

Models routinely return 3–6 parallel read calls (for example `kubectl_get_pods` for several namespaces). They run strictly in order.

**Fix.** Split the batch into read-only, concurrency-safe calls (R0 and flagged) and the rest. `asyncio.gather` the first group with a limit (a semaphore of 4–8). Run the mutating ones in order, in the model's order. Append results **in the original call order** so the transcript is deterministic.

### P1-4: Blocking I/O freezes the whole server

Every domain tool is synchronous and is called straight from async code:
- Kubernetes client calls;
- `subprocess.run(["argocd", ...], timeout=30)`;
- GitPython plus `gh pr create` (60 s timeout);
- `urllib` for fetch and search (10 s);
- `grep` (10 s);
- `pod_snapshot_after_restart`, which loops `time.sleep(2)` for **up to 120 s**.

While any of these runs, **every other session, SSE stream and API request on the server stalls**.

**Fix.** Wrap synchronous handlers in `await asyncio.to_thread(fn, *args)` in the registry, so each tool doesn't have to. Replace `time.sleep` with `await asyncio.sleep`. Use `httpx.AsyncClient` for web tools.

### P1-5: The run is tied to the HTTP connection

`stream_session` runs the agent *inside* the SSE generator. If the client disconnects (a browser tab closes or a proxy times out while a Telegram approval is pending), the run is **cancelled and marked failure**. Opening `/stream` twice starts **two concurrent runs** of the same session.

**Fix.** Separate execution from observation, as Claude Managed Agents, OpenClaw and dsh all do:
- `POST /sessions/{id}/run` starts a background task (tracked in a registry keyed by session, protected by a lock or compare-and-set on status);
- the task writes events to the session log;
- `GET /stream` just tails the log (with `Last-Event-ID` for resuming);
- `POST /sessions/{id}/cancel` cancels the task.

### P1-6: Vault is contacted on every read

`get_vault_client()` builds a new `hvac.Client` and calls `is_authenticated()` (a network round trip) on every `get_secret`. Per run that's at least the model key; per approval, the bot token and chat ID; plus the advisor, dreamer and kubeconfig. There's also **no fallback to environment variables**, so without Vault nothing runs at all. That's hostile to local development and to Pi-style simplicity.

**Fix.** One client, created lazily. A TTL cache (5–15 minutes) per `(path, key)`. A pluggable `SecretProvider` chain: `env → .env file (0600) → Vault → cloud secret managers`. Renew Vault tokens.

### P1-7: Interruptions are a queue of one

`set_session_interruption` overwrites `interruption_payload`, so two quick steering messages lose the first. It's also only checked at the top of each turn, so steering can't reach a long tool call or a pending approval.

**Fix.** An `interrupts` event type in the session log, all delivered in order at the next turn boundary. Plus a separate `cancel` that aborts in-flight tools through an `asyncio` cancellation token passed to handlers.

### P1-8: No handling of untrusted content (prompt injection)

`web_fetch`, `web_search`, `kubectl_logs` and argocd output are appended as raw tool results. Your `EvidenceItem.provenance` model (`external-fetched`, `tool-observed`) is exactly the right idea, but it's never used.

**Fix.**
- Wrap external content in explicit delimiters with a provenance label (`<external source="url" trust="untrusted">…</external>`).
- Strip invisible Unicode and hidden HTML comments (Hermes scans for these).
- **After any untrusted content enters the context, raise the risk tier of subsequent mutating actions by one level for that turn** — for example, R1 edits become R2 approvals. This "taint" is cheap and uses your tier system well.

### P1-9: Background tasks without references

`asyncio.create_task(dispatch_webhook(...))` results are never stored. Python's documentation warns such tasks can be garbage-collected before they finish. Webhooks also have no retry and no signing.

**Fix.** Keep a `set()` of background tasks and use `task.add_done_callback(set.discard)`. Sign webhook payloads with HMAC-SHA256 (`X-Harness-Signature`). Retry with backoff.

### P1-10: The scheduler isn't persistent or manageable

APScheduler uses an in-memory job store. **Every restart loses every cron job.** There's no `GET /cron` or `DELETE /cron/{id}`, no timezone setting, and the jobs run as `execute_session`, with no session ID or interruption support.

**Fix.** A persistent job store (APScheduler's SQLAlchemy store over your SQLite, or your own `schedules` table), plus list, delete and pause endpoints and timezone-aware cron. Also consider a **heartbeat**: OpenClaw runs a periodic "check `HEARTBEAT.md` and act" turn, which fits DevOps well (a drift check every 30 minutes).

### P1-11: GitOps action changes the user's working repository

`create_change_pr` checks out a new branch in the given repo, commits, pushes, then in `finally` checks out *"the first other head"*, **not the branch that was originally checked out**. If the user was on a feature branch, they end up on `main` (or whichever head sorts first). It also refuses to run if the working tree is dirty, which is right, but only because it works in place.

**Fix.** Use `git worktree add <tmp> -b <branch>`, do the change in the worktree, push, open the PR, then `git worktree remove`. The user's checkout is never touched. Claude Code's `EnterWorktree` and subagent `isolation: "worktree"` follow the same principle.

### P1-12: Token budget accounting

`total_tokens += usage.total_tokens` counts the full prompt again on every turn. As a *spend* meter that's defensible, but at 200k it will stop long but legitimate runs early, and it doesn't account for cached tokens (which cost roughly 10% on Anthropic). Budgets should be tracked separately:
- **context tokens** (for compaction decisions);
- **billable tokens / cost** (for spend limits, with cache-read and cache-write discounts);
- **wall-clock time**.

---

## 7. Performance: why it is slower and costlier than it should be

### 7.1 Compaction is the biggest cost driver

With the 12-message trigger, a typical DevOps investigation (say 10 tool turns, about 22 messages) triggers **3–5 extra summarisation calls**. Each one:
- adds a full model round trip of latency (often 2–10 s on large models);
- sends up to 5,000 characters per message to the summariser;
- **invalidates the prompt cache**, because the message prefix changes.

**Expected gain from the §5 P0-9 fix:** most runs never compact at all, because 20–60k tokens fits comfortably in current context windows. Long runs compact once or twice, not every few turns.

### 7.2 Just-in-time `load_skill` costs more than it saves

- Each category load costs **one extra model round trip** (the model has to call `load_skill` and then act on the next turn).
- Your whole tool catalogue is about 15 schemas, roughly 1.5–2.5k tokens. Sending it on every call costs less than one extra round trip.
- Adding tools mid-conversation **changes the request prefix**. On providers that cache tools as the first cache segment (Anthropic's ordering is tools, then system, then messages), each load **invalidates the whole cache**.

**Recommendation.**
- Up to about 40 tools: send them all, fixed and sorted, for a stable prefix.
- Beyond that: list deferred tools **by name and one-line description** in the system prompt, and provide a `tool_search` tool that returns schemas. Claude Code's ToolSearch uses this deferred-tool pattern. Skill *instructions* (long Markdown) are a different matter: *those* should load on demand (§10.3).

### 7.3 No prompt caching

The system prompt, tool list and early messages are sent unchanged on every turn but never marked for caching.

**Fix.** For Anthropic models through LiteLLM, add `cache_control: {"type": "ephemeral"}` on the system prompt block and on the last message. Other providers (OpenAI, DeepSeek, Gemini) cache stable prefixes automatically, **provided the prefix really is stable**: no timestamps in the system prompt, no reordered tools, no mid-conversation tool changes. Hermes deliberately freezes its memory snapshot at session start "to enable prefix caching".

### 7.4 No token streaming

`stream=True` is never used. The SSE endpoint only emits after each full completion, so users see nothing for 5–30 s per turn. Streaming is also what makes mid-generation interruptions possible.

### 7.5 Import-time weight and cold start

Importing `core.agent_engine` pulls in LiteLLM (a heavy import, several hundred milliseconds or more), the Kubernetes client, python-telegram-bot, the OTel gRPC exporter and GitPython, **even for a generic, non-DevOps run**.

**Fix.** Import domain packs lazily through the registry (a pack registers its tools when enabled). Import LiteLLM once, at startup of the server process, not at CLI parse time. For the CLI, consider calling providers directly with `httpx`, as Pi does, for a fast cold start.

### 7.6 SQLite overhead

`init_db()`, which runs 3 `CREATE`s, 3 triggers and an `ALTER`, is called **for every request and every run**. There's no WAL mode, so readers block writers.

**Fix.** Run the migration once at startup (a `schema_version` table). Use `PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000`. Use a single connection per process with `check_same_thread=False` behind an `asyncio.Lock`, or `aiosqlite`. Hermes uses SQLite in WAL mode for sessions.

### 7.7 Output spilling thresholds are far too high

`_spill_if_needed` only spills above **100,000 characters** (about 25k tokens) and then keeps a **50,000-character** head. One `kubectl describe` or log dump can fill a quarter of the context window.

Reference points:
- Hermes: terminal output capped at 50k characters (first 40% and last 60%); file reads paginated at 2,000 lines; lines capped at 2,000 characters.
- Pi: truncates tool results to 2,000 characters **when serialising for compaction**.
- Claude Code: `Read` returns up to 2,000 lines by default, and large outputs are persisted to a file with a preview.

**Fix.** Use per-tool limits (logs: head 2k + tail 6k characters; `describe`: parse to relevant fields; JSON: select keys) with the spill path given in the result. Add a `read_spill(path, offset, limit)` tool so the model can page through when it needs to.

### 7.8 Global mutable state across concurrent runs

`dynamic_tool_schemas` and `dynamic_tool_callables` are module-level lists that are **`.clear()`ed and rebuilt at the start of every run**. Two concurrent API sessions can interleave: run A iterates the list while run B clears it, so A sends an empty or partial toolset, or looks up a callable that has just vanished. This is a correctness *and* performance issue (the plugin directory is re-imported per run).

**Fix.** Load once. Reload on file change (a watcher) or through an explicit admin call. Each run takes an **immutable snapshot** of the registry at start.

### 7.9 Summary table

| Change | Latency | Cost | Effort |
|---|---|---|---|
| Token-based, cut-safe compaction | **High** (removes most extra calls) | **High** | M |
| Send the stable full tool list, no JIT for ≤40 tools | Medium (−1 round trip per category) | Medium (cache stays warm) | S |
| Prompt caching with a stable prefix | Medium (faster time to first token) | **High** (cached input around 90% cheaper on Anthropic) | S |
| Token streaming | Perceived: **high** | — | S |
| Parallel read-only tools | Medium to high on multi-call turns | — | S |
| `to_thread` for synchronous tools | **High** under concurrency | — | S |
| Secret cache | Low to medium | — | S |
| SQLite migrate once + WAL | Low to medium | — | S |
| Tighter output limits | Medium | Medium to high | S |
| Lazy domain imports | Cold start | — | S |

---

## 8. Built but not wired: dead weight inventory

| Item | Where | Status | Recommendation |
|---|---|---|---|
| Memory writes | `store.add_memory` | Never called outside tests | Add a `memory` tool (add/replace/remove) with size limits (§10.3) |
| Memory in prompt | `ContextPacket.memory_hits` | Retrieved, never rendered in `_build_prompt` | Render as a frozen block at session start |
| Memory domain filter | `build_context` (domain defaults to `general`) | Searches `general`, memories are `devops` (reproduced: `[]`) | Take the domain from the agent profile, or search across domains with a boost |
| Search side effect | `search_memory` | Increments `use_count` on every search, so noise inflates "usage" | Count usage when the agent *cites* or *uses* a memory, not on retrieval |
| `SKILL.md` loading | `domains/devops/skills/*` | Never read by any code | Progressive disclosure (§10.3) |
| Skill promotion | `promote_candidate_skill` | Never called | Wire it to a `POST /skills/{id}/promote` action plus an approval |
| Skill drafting quality | `draft_skill_if_warranted` | Produces "Inspect `x.y` evidence" × N | Have the model write the skill from the transcript (Hermes `skill_manage`) |
| Verification on the API path | `_run_requested_verification` | `live_state` is always `{}` from the API, so never runs | Add verification specs to the session request and to agent profiles |
| Curator | `memory/curator.py` | Never called, and `record_skill_outcome` is never called | Record an outcome per skill use; schedule curation |
| Dreamer | `memory/dreamer.py` | Runs, but there's nothing to consolidate; it deletes originals unconditionally; its prompt size is unbounded | Keep originals (mark as `superseded_by`); chunk the input; OpenClaw-style daily notes → MEMORY.md |
| Effects | `EffectStack` / `EffectScope` | Nothing ever pushes | See §12 |
| Lifecycle | `LifecycleState` | Never transitions | See §12 |
| Hot reload | `main.reload_registry` | No caller or endpoint; it replaces private dicts | `POST /admin/reload` + file watcher + validation |
| `approval_queue` table | `store.py` | Unused | Use for API-based approvals (P0-5) |
| `analytics_daily` table | `store.py` | Unused | Derive from the event log instead, then drop it |
| `settings.yaml` | `config/` | Never read | One `Settings` model (pydantic-settings) with environment overrides |
| `dashboard.json` | `config/` | Charts metrics nobody emits | Emit via OTel metrics, or delete |
| `Session` model | `primitives/agent.py` | Unused (the store uses dicts) | Use it, or delete it |
| `teardown_tasks` | `RunReceipt` | Never filled | Fill it from the effect scope, or drop it |
| `claude-agent-sdk` dependency | `pyproject.toml` | Never imported | Remove |
| `mcp` dependency | `_mcp.py`, tool modules | Only used for decorators; the engine calls functions directly | Either run them as real MCP servers **and** add an MCP client, or remove |
| `pytest`, `pytest-asyncio` in runtime deps | `pyproject.toml` | Test-only | Move to `[project.optional-dependencies].dev` |
| `questionary` | `cli/setup.py` | Used, **not declared** | Declare it, or merge setup into `start.sh` |
| `GROK_MODEL` env var | 2 places | Legacy naming | Remove |
| Workflow script | `gateway/workflow.py` | Hard-coded plan, `datetime.utcnow()` (deprecated) | Make plans data (YAML) run by the executor |

---

## 9. Test suite assessment

**Strengths.** There is a test per phase. Policy table tests are clear. Mocks avoid network calls. The fork, compaction, self-edit and hardening scenarios are represented.

**Problems.**

1. **Tests hide production bugs.**
   - The orchestration test creates the missing table.
   - The fork test injects `message_history` by hand.
   - The dreamer test builds its own schema instead of using `init_db`.
   - The compaction test mocks `_compact_history` entirely, so the tool-pair split is never exercised.
2. **Tests assert the insecure behaviour.**
   - `test_phase24_self_edit` confirms a self-written tool runs, but never checks that it was scoped, sandboxed or risk-rated.
   - `test_generic_tool_dispatches` asserts R1 for `edit`.
3. **Environment coupling.**
   - `test_phase15_events` sets `VAULT_ADDR`/`VAULT_TOKEN` at import time.
   - `phase7/test_otel_init` hard-codes a path and a token.
   - `test_phase10_gitops_live` and `test_phase6_r3_live` are live tests mixed in with unit tests, with no marker to skip them.
4. **Tests write to real directories.**
   - `test_phase24` writes into `core/plugins/dynamic/` in the repository.
   - Several tests use the default `data/memory.db`.
5. **Missing tests.** There are none for:
   - approval timeout or denial paths;
   - tool error recovery;
   - concurrent sessions;
   - authentication;
   - SSRF and path confinement;
   - compaction message validity;
   - resume or fork through the real receipt path;
   - scheduler persistence.

**Recommendations.**
- Use `pytest` markers `unit` / `integration` / `live`; only `unit` runs by default.
- A single `conftest.py` fixture: `db = init_db(tmp_path/"t.db")`, patched everywhere through **one** settings object rather than per-module monkeypatches.
- A **transcript validator** used in every loop test: every assistant `tool_calls` ID has exactly one following `tool` message, and no `tool` message is orphaned. Run it after compaction too.
- **Security regression tests**, one per P0 item (path traversal, SSRF, unauthenticated request → 401, a read-only agent can't self-edit, and so on).
- A property-style test for compaction: generate random tool transcripts, compact, validate.

---

## 10. Reference agent deep dives and what to borrow

### 10.1 Claude Code

**What it is.** Anthropic's agentic coding tool (terminal, IDE, desktop, web). The engine is closed-source and compiled. The public repo holds plugins, examples, and since the 2.1.2xx releases, the source of built-in "mods" plus a 13k-line TypeScript contract of its in-process **function-hook** API.

**Key mechanisms.**
- **Permission system.**
  - Rules `allow` / `ask` / `deny` with specifiers such as `Bash(git commit:*)`, `Read(./secrets/**)`, `WebFetch(domain:example.com)`, `mcp__server__*`.
  - **Evaluated deny, then ask, then allow; first match wins.**
  - Modes: `default`, `acceptEdits`, `plan`, `auto` (a classifier reviews actions), `dontAsk` (auto-deny anything that would prompt), `bypassPermissions`.
  - Managed (organisation) settings that users can't override, such as `disableBypassPermissionsMode`.
  - **Hook decisions can't loosen deny or ask rules.**
- **Hooks.**
  - About 33 lifecycle events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`, `UserPromptSubmit`, `Stop`, `SubagentStart`/`SubagentStop`, `PreCompact`/`PostCompact`, `SessionStart`/`SessionEnd`, `FileChanged`, `WorktreeCreate`, `PreModelSwitch`, and others.
  - Five hook types: `command`, `http`, `mcp_tool`, `prompt` (a small LLM judge), `agent` (a verifying subagent).
  - `PreToolUse` can return `updatedInput` (rewrite arguments) or `additionalContext`.
  - Async hooks and `asyncRewake` (a background check that wakes the agent with findings).
  - The newer **function hooks**: `($, e, next)` middleware, a chain with 5 tiers (`prepend > user > append > builtin > core`), a 10 s per-hook budget, and a failing hook is skipped.
- **Sandbox.** An OS-level Bash sandbox (Seatbelt on macOS, bubblewrap on Linux) with a filesystem allowlist and **network egress through a proxy with a domain allowlist**. It can **mask credentials**: commands see a sentinel value, and the proxy injects the real secret only for allowed hosts.
- **Context.** Auto-compaction near the limit, guided `/compact <instructions>`, pruning of old tool results, prompt caching, deferred tools with ToolSearch, CLAUDE.md hierarchy (managed, user, project, local), `.claude/rules`.
- **Checkpoints.** Every user turn snapshots the files edited by its edit tools. `/rewind` restores code and/or conversation, or summarises from or up to a point. Session branching with `/branch` and `--fork-session`.
- **Subagents.** `Agent` tool with typed agents (Explore on a small model, Plan, custom Markdown agents with their own `tools` and `model`), background by default, `isolation: worktree | remote`, `SendMessage` to a named agent.
- **Extensibility.** Plugins (commands, agents, skills, hooks, MCP servers), marketplaces, MCP client (stdio, SSE, HTTP, OAuth).
- **Other.** Skills (progressive disclosure), scheduled tasks, output styles, a headless SDK, a GitHub Action, OpenTelemetry.

**What you are missing relative to Claude Code.**
1. Argument-aware permission rules (not just a tier per tool), checked deny first.
2. A hook bus. Your Telegram gate, spill, verification and learning should all be hooks.
3. An OS or container sandbox and network egress control.
4. A shell tool, a paged file read, and **exact-string edit** (`old_string` → `new_string`, which fails if not unique). Your `edit` overwrites whole files, which is token-expensive and destructive.
5. Checkpoints and rewind for file edits.
6. Correct compaction, caching and deferred tools.
7. Subagents with typed profiles and isolation.
8. Project instruction files.
9. An MCP client.

**Borrow first.** The deny-first rule engine, `PreToolUse`/`PostToolUse`/`Stop` hooks, exact-replace edit, and background subagents with worktree isolation.

### 10.2 OpenClaw

**What it is.** An open-source personal and team assistant built around a **single long-lived Gateway daemon** that owns model-provider connections and many chat channels (WhatsApp, Telegram, Slack, Discord, Signal, iMessage and more), with device "nodes" (macOS, iOS, Android).

**Key mechanisms.**
- **Gateway security.** Binds to `127.0.0.1:18789` by default. A typed WebSocket API with a **mandatory authenticated handshake declaring a role**. Device tokens and **pairing approval for non-local clients**.
- **Three separate security layers.**
  1. **Sandbox** (where tools run): `sandbox.mode = off | non-main | all`, `workspaceAccess = none | ro | rw`, backends Docker, Podman, SSH or OpenShell. An operator role can make the sandbox *required* and fail closed.
  2. **Tool policy** (which tools exist): profiles, then global/per-agent/per-provider allow and deny, then sandbox-specific policy. **"Deny always wins"**, and if an allow list exists, everything else is unavailable.
  3. **Elevated**: an explicit exec-only escape hatch to the host, which can't override required sandboxing.
- **Exec approvals.**
  - Modes `deny | allowlist | ask | auto | full`.
  - `ask = always | on-miss`.
  - An **ask fallback (deny) when nobody answers or the approval UI is unavailable**.
  - Allowlists with `argPattern`, which **bind the executable path and file operands at approval time and re-check them before running** (preventing substitution).
  - Chat-native buttons (allow once / allow always / deny), `/approve`.
  - Effective policy is the *stricter* of global and local.
- **Sessions and subagents.**
  - Session visibility scopes `self | tree | agent | all`.
  - `agentToAgent` allow list.
  - `sessions_spawn` with attachment limits.
  - Subagent defaults: `maxConcurrent` (8), `runTimeoutSeconds`, `archiveAfterMinutes`, `allowAgents`.
- **Compaction.**
  - Automatic near the window limit **and on a provider context-overflow error, followed by a retry**.
  - `/compact <focus>`.
  - **Memory flush before compaction** (the agent is prompted to save durable notes).
  - **Keeps tool calls paired with their results.**
  - `keepRecentTokens` (20k), an optional separate summary model, and a `safeguard` mode.
- **Memory.**
  - File-based and transparent: `USER.md`, `MEMORY.md`, daily `memory/YYYY-MM-DD.md` (today and yesterday load automatically), `DREAMS.md`.
  - Tools `memory_search` (hybrid **vector + keyword**), `memory_get`, and `intent` (event-conditioned standing reminders).
  - "Dreaming" distils daily notes into MEMORY.md. There's also "Active memory" automatic recall, and pluggable engines such as Honcho.
- **Automation.** Cron with webhook triggers, Gmail Pub/Sub, and **heartbeat**, a periodic background turn.
- **Multi-agent routing, agent bindings, and automatic model failover.**
- **Plugins.** Feature, tool, channel and provider plugins via a manifest and hooks. A skill workshop with self-learning and approval.

**What you are missing relative to OpenClaw.**
1. An authenticated gateway with pairing (P0-4).
2. Approval fallback, timeout, and "allow always" saved as a rule (P0-5).
3. **Binding the approval to exact arguments and re-checking before running.** Your approval covers a *description string*, not the arguments that end up executing.
4. Sandbox, tool policy and elevated as separate, composable concepts.
5. Memory flush before compaction; compaction on overflow errors.
6. Transparent file-based memory plus hybrid search; daily notes; dreaming *into* a curated file rather than deleting rows.
7. Heartbeat; persistent cron.
8. Subagent concurrency and timeout limits; session visibility scopes.
9. Model failover.
10. Multi-channel gateway (Telegram exists only as an approval channel, not as a conversation channel).

**Borrow first.** Argument-bound approvals with deny as the fallback, the three-layer security model, memory flush before compaction, and heartbeat for DevOps drift checks.

### 10.3 Hermes Agent (Nous Research)

**What it is.** A self-improving open-source agent with a "closed learning loop": it curates memory, creates and improves skills while it works, and runs from a CLI or a gateway covering 20+ messaging platforms. Tooling is large (60+ tools), with 7 terminal backends.

**Key mechanisms.**
- **Memory.**
  - Two small curated files: `MEMORY.md` (**2,200-character limit**) and `USER.md` (**1,375-character limit**), injected as a **frozen snapshot at session start** so prefix caching works.
  - A `memory` tool with `add | replace | remove` (substring-based).
  - **No automatic compaction of memory**: when a write would exceed the limit the tool returns an error, and the agent must consolidate.
  - Writes are **scanned for injection and exfiltration patterns and invisible Unicode**; duplicates are rejected.
  - **Session search**: FTS5 over all past conversations in `state.db`, about 20 ms per query.
  - Optional external providers (Honcho, Mem0, Supermemory and others).
- **Skills.**
  - Progressive disclosure: **level 0** `skills_list()` (names and descriptions, about 3k tokens), **level 1** `skill_view(name)`, **level 2** `skill_view(name, path)` for reference files.
  - `SKILL.md` frontmatter: `platforms`, `requires_toolsets`, `fallback_for_toolsets`, config keys, and body sections *When to Use / Procedure / Pitfalls / Verification*.
  - **`skill_manage`** (`create | patch | delete | write_file | remove_file`), used when the agent solves a multi-step workflow, recovers from an error, or is corrected by the user. `skills.write_approval: true` stages writes for review.
  - A skills hub with **security scanning** (exfiltration, injection, destructive commands, supply chain) and trust levels.
- **Security.**
  - Dangerous-command approval modes `smart` (an auxiliary LLM auto-approves low risk), `manual`, `off`, with **30+ patterns** (rm -r, mkfs, chmod 777, DROP TABLE, curl|sh…).
  - A **hard blocklist that can't be overridden**, even in YOLO mode.
  - User deny globs.
  - **300 s timeout, then deny.**
  - Approve once, for the session, or always.
  - Gateway user authorisation hierarchy that denies by default. **DM pairing codes** (8 characters, 1-hour expiry, rate-limited, lockout).
  - Hardened containers (drop capabilities, no-new-privileges, process limits, noexec tmp).
  - **Environment filtering**: variables matching `KEY|TOKEN|SECRET|PASSWORD…` are withheld from child processes; MCP subprocesses get a minimal environment.
  - Secret redaction in errors.
  - Write blocks on `~/.ssh`, `~/.aws`, `~/.kube`, `/etc/sudoers`, plus an optional write-safe root.
  - Context files scanned for injection.
  - SSRF protection (RFC 1918, loopback, link-local, metadata).
  - A website blocklist and pre-execution command scanning.
- **Context compression.**
  - Triggers at **50%** of the window (cap 256k).
  - Protects the **last 20 messages** and **pins the first 3 non-system messages**.
  - Summary model configurable separately.
  - Timeouts with deterministic fallback (summarising without an LLM).
- **Output limits.** Terminal 50k characters (first 40%, last 60%); read pagination 2,000 lines; 2,000 characters per line; scaled down for small-context models.
- **Sessions.** SQLite in WAL mode; the ID stays the same across compressions; an idle reaper; the gateway serialises turns per session with a lease.
- **Other.** Provider fallback chains, subagents, `execute_code` (programmatic tool calling), cron, `SOUL.md` personality, MCP, trajectory export and RL integration.

**What you are missing relative to Hermes.**
1. **The learning loop that actually runs:** a memory tool with size limits and scanning; `skill_manage` with approval staging; level 0/1/2 skill loading. You have the *schemas* for all of this, but not the tools.
2. Session search across past runs. Your FTS5 table exists but indexes nothing useful; index session events instead.
3. A command risk classifier with a hard blocklist. This fits your R-tiers well: classify commands, not just `(tool, action)` pairs.
4. Environment filtering for subprocesses. Your `subprocess.run` calls pass the full environment, which includes `VAULT_TOKEN`.
5. SSRF protection and write-path protection (P0-3).
6. Compaction pinning and protection rules; deterministic fallback.
7. DM pairing instead of a hard-coded chat ID.
8. Idle reaper and turn serialisation per session (P1-5).

**Borrow first.** Frozen memory snapshot with size limits and a `memory` tool, `skill_manage` with write approval, the hard blocklist plus risk classifier, and environment filtering.

### 10.4 Pi (pi.dev, `@mariozechner/pi-coding-agent`)

**What it is.** A deliberately minimal, extensible terminal coding agent: *"primitives, not features."* It ships four core tools (read, write, edit, bash), supports 15+ providers, and runs in four modes (interactive TUI, print/JSON, RPC over stdin/stdout, SDK). It **intentionally omits** MCP, subagents, permission popups, plan mode, todos and background bash. Those are built as extensions, or handled by running Pi in a container.

**Key mechanisms.**
- **Sessions are a JSONL tree.** Each entry has `id`/`parentId`. Entry types: `message`, `compaction`, `branch_summary`, `model_change`, `thinking_level_change`, `custom`, `custom_message`, `label`, `usage`, and more. `/tree` jumps to any earlier point and branches, generating a **summary of the abandoned branch** that is injected into the new one. Sessions can be exported to HTML or a gist.
- **Compaction.**
  - Triggers when `contextTokens > contextWindow − reserveTokens` (default reserve 16,384), checked after tool results, before prompts and after runs.
  - Walks back to keep `keepRecentTokens` (20,000).
  - **Never cuts at tool results.**
  - Structured Markdown summary (goal, constraints, done / in progress / blocked, decisions with reasons, next steps, files read and modified).
  - Tool results truncated to 2,000 characters when serialised.
  - **File operations are accumulated across compactions.**
  - Extension hooks `session_before_compact` and `session_before_tree`.
- **Extensions.**
  - TypeScript factories receiving an `ExtensionAPI`. Events: `before_agent_start`, `agent_end`, `tool_call` (**change the input or block**), `tool_result`, `message_end`, `context` / `context_with_system` (transform what the model sees), `session_start` / `session_shutdown`, `provider_stream_event`, `user_bash`, `cache_warming_decision`.
  - Registration: `registerTool`, `registerCommand`, `registerShortcut`, `registerFlag`, `registerProvider`, `sendUserMessage`, `appendEntry`.
  - Handlers compose in order.
  - `/reload` replaces the extension runtime (hot reload).
- **Context engineering.** A minimal system prompt, `AGENTS.md`, `SYSTEM.md` overrides, skills loaded on demand, prompt templates.

**What you are missing relative to Pi.** This is about *qualities*, not features:
1. **A thin, auditable core loop** with everything else as extensions. Your 923-line engine mixes loop, schemas, dispatch, policy, DevOps logic, compaction and tracing.
2. **A tree-structured append-only session log** as the single source of truth (P0-11).
3. **Correct compaction** (P0-9).
4. **An extension event model** with argument rewriting and blocking on `tool_call`, plus context transforms. That's your hook bus.
5. **Multiple run modes from one core.** You have API and CLI as separate code paths with duplicated receipt logic; Pi has one core with print, JSON, RPC and SDK front ends.
6. **Fast cold start and minimal dependencies.**
7. **Model and thinking-level changes as session events** (switching models mid-session).

**Borrow first.** The JSONL-tree session format (store it in SQLite if you like), the compaction algorithm as written, and the `tool_call` / `context` extension events.

**Important contrast.** Pi leaves safety to containers and extensions. Your R-tier gate is a real advantage **if** it is enforced uniformly. The goal is Pi's *core shape* with your *safety extension* on top.

### 10.5 DeepSeek Harness (`dsh`) and the Cordis paper

**Clarification.** Your repo's "DeepSeek harness" is the **paper** (*A Programming Paradigm for Spatiotemporal Composability*, Peking University and DeepSeek-AI). It formalises composability and names self-evolving harnesses as a *future application*. **In August 2026 DeepSeek open-sourced an actual harness, `deepseek-ai/deepseek-harness` (`dsh`), built on Cordis.** It's a developer preview that explicitly warns of breaking changes, and its public docs are still thin, so parts of this section are less certain than the others.

**What `dsh` is (from its README, site and press coverage).**
- **"Everything is a plugin":** model adapters, tool registry, skills, sessions, sandboxes, storage, **the loop itself**, scheduling and UI are all Cordis plugins, loaded, unloaded and replaced through the Cordis kernel. There's no privileged core.
- **An append-only session log**, where "anything that reaches a model request has to be reconstructable from that log". Resume, fork, replay, transcripts and telemetry are all built on it (a "Trajectory" view).
- **OS sandboxing:** Landlock on Linux, Seatbelt on macOS, restricted-token ACLs on Windows.
- **Presets:** `Standard` (file tools, shell, web search, subagents, plan mode), `Code` (a TypeScript SDK the model scripts against to batch many tool round trips), `Minimal` (bash + `str_replace_editor`), `Creator` (plugin authoring and inspection).
- Providers: Anthropic, OpenAI, Bedrock, Azure, Gemini. Can use Claude Code or Codex as subagents. MCP client. Agent Client Protocol.
- A web UI (`npx @deepseek-ai/dsh web`).

**What the paper actually requires** (the parts your v2 architecture tries to adopt):
- **Revertible effects.** *Every* change to shared context goes through one primitive, `ctx.effect(callback)`. The callback returns its inverse (a dispose function). Disposers are composed into the parent context's accumulated `ctx.dispose`, so unloading a component reverts **everything** it did: registered tools, listeners, timers, connections, provided services.
- **Reactive coeffects.** Components declare dependencies (`inject`) and what they provide (`provide`). When a dependency appears or disappears, dependents are activated or deactivated automatically.
- **Fibers.** Each component instance is a fiber with a lifecycle state (`LOADING`, `ACTIVE`, `UNLOADING`, `FAILED` with the error attached), a parent, and a disposer.
- **Hot module replacement.** Changed files are classified (accepted or declined, with a fixed point over the import graph); stale entries are found; old fibers are disposed and new fibers created. No manual accept boundaries are needed, because fibers already bound all effects.

**How you compare.** See §12 for the detailed mapping. In short: you have the *vocabulary* (EffectStack, LifecycleState, reload) but none of the *discipline*. Nothing is registered through an effect API, so there is nothing to undo.

**Borrow first.**
- The **single mutation primitive with its inverse**. Make every registration (tool, hook, cron job, listener, approval subscription) return a disposer tracked by its owning plugin.
- **Plugins as the unit of reload**: DevOps pack, Telegram, dreamer, learning.
- **The log as the only source of truth.**
- The **Minimal preset** idea: a one-flag benchmark configuration to measure what your extra layers cost.
- Consider the **"Code" preset idea** for DevOps: let the model write one short script against a typed, policy-checked SDK instead of 10 round trips. Your policy engine must still wrap every SDK call.

---

## 11. Master gap matrix

Legend: ✅ has it · ⚠️ partial or broken · ❌ missing · ext = by extension or plugin · — not applicable or not documented.
*dsh column: developer preview, thin docs, lower confidence.*

### 11.1 Agent loop and tools

| Capability | Yours | Claude Code | OpenClaw | Hermes | Pi | dsh |
|---|---|---|---|---|---|---|
| Shell / bash tool | ❌ | ✅ | ✅ exec | ✅ 7 backends | ✅ | ✅ |
| Paged file read | ❌ (directory listing only) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Exact-replace edit | ❌ (overwrite only) | ✅ | ✅ | ✅ | ✅ | ✅ `str_replace_editor` |
| Grep / glob confined to workspace | ⚠️ unconfined | ✅ | ✅ | ✅ | via bash | ✅ |
| Web fetch with SSRF guard | ⚠️ no guard | ✅ domain rules | ✅ | ✅ | ext | — |
| Errors returned to model | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Token streaming | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Parallel tool execution | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Retries, backoff, failover | ❌ | ✅ | ✅ failover | ✅ fallback chains | ✅ | ✅ |
| Interrupt / steer mid-run | ⚠️ queue of one, turn boundary only | ✅ queued messages | ✅ | ✅ | ✅ | ✅ |
| Cancel in-flight tool | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Todo / plan tools | ❌ | ✅ plan mode | ✅ | ✅ | ext | ✅ plan mode |
| Programmatic tool calling | ❌ | ✅ workflows | — | ✅ `execute_code` | ext | ✅ Code preset |
| Multiple run modes (TUI / print / JSON / RPC / SDK) | ⚠️ API + CLI | ✅ | ✅ | ✅ | ✅ | ✅ |

### 11.2 Context and memory

| Capability | Yours | Claude Code | OpenClaw | Hermes | Pi | dsh |
|---|---|---|---|---|---|---|
| Token-based compaction | ❌ (count of 12) | ✅ | ✅ | ✅ 50% | ✅ window − reserve | ✅ |
| Never splits tool call and result | ❌ (reproduced) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Guided manual compaction | ❌ | ✅ | ✅ | ✅ | ✅ | — |
| Memory flush before compaction | ❌ | ✅ | ✅ | ✅ | ext | — |
| Tool-output limits and pruning | ⚠️ 100k threshold | ✅ | ✅ | ✅ 50k head/tail | ✅ | ✅ |
| Prompt caching / stable prefix | ❌ | ✅ | ✅ | ✅ frozen snapshot | ✅ | — |
| Deferred tools / tool search | ⚠️ JIT via extra round trip | ✅ ToolSearch | — | ✅ toolsets | ext | — |
| Project instructions file | ❌ | ✅ CLAUDE.md (AGENTS.md via mod) | ✅ AGENTS.md, SOUL.md… | ✅ scanned for injection | ✅ AGENTS.md / SYSTEM.md | ✅ |
| Memory the agent writes | ❌ | ✅ auto-memory | ✅ files + tools | ✅ `memory` tool | ext | plugin |
| Memory size limits and scanning | ❌ | — | — | ✅ | — | — |
| Search across past sessions | ⚠️ FTS exists, indexes nothing | ✅ | ✅ hybrid | ✅ FTS5 | ✅ | ✅ log |
| Consolidation / dreaming | ⚠️ deletes rows | ✅ | ✅ dreaming | ✅ nudges | — | — |

### 11.3 Safety

| Capability | Yours | Claude Code | OpenClaw | Hermes | Pi | dsh |
|---|---|---|---|---|---|---|
| Deny by default for unknown actions | ✅ (for tools routed through it) | ✅ | ✅ | ✅ | — | — |
| Argument-aware rules | ❌ | ✅ | ✅ `argPattern` | ✅ patterns | ext | plugin |
| Risk tiers | ✅ R0–R4 | modes + classifier | modes | smart / manual / off | — | — |
| Hard blocklist that can't be overridden | ⚠️ R4 only for listed pairs | ✅ protected paths, managed deny | ✅ operator sandbox required | ✅ | — | — |
| Approval timeout + deny fallback | ❌ | ✅ | ✅ | ✅ 300 s | — | — |
| Approval scopes (once / session / always) | ❌ | ✅ | ✅ | ✅ | — | — |
| Approval bound to exact arguments | ❌ | ✅ | ✅ re-checked before run | ✅ | — | — |
| Approver authorisation | ❌ | ✅ local user | ✅ pairing | ✅ allowlist + pairing | — | — |
| OS / container sandbox | ❌ | ✅ | ✅ | ✅ | container | ✅ Landlock/Seatbelt |
| Network egress control / SSRF | ❌ | ✅ proxy allowlist | ✅ | ✅ | — | ✅ |
| Environment / secret filtering for subprocesses | ❌ | ✅ credential masking | ✅ | ✅ | — | — |
| Prompt-injection handling | ❌ (model exists, unused) | ✅ | ✅ | ✅ scanning | — | — |
| Control-plane authentication | ❌ | local | ✅ handshake + pairing | ✅ | local | local |
| Managed / organisation policy | ❌ | ✅ | ✅ operator roles | ✅ config | — | config |

### 11.4 Sessions, orchestration, extensibility, ops

| Capability | Yours | Claude Code | OpenClaw | Hermes | Pi | dsh |
|---|---|---|---|---|---|---|
| Append-only event log | ❌ (receipt blob) | ✅ transcript JSONL | ✅ | ✅ SQLite | ✅ JSONL tree | ✅ |
| Resume | ⚠️ broken | ✅ | ✅ | ✅ | ✅ | ✅ |
| Fork at any point / tree | ⚠️ whole-receipt copy, broken | ✅ `/branch` | ✅ | ✅ | ✅ `/tree` | ✅ |
| Replay | ❌ | ⚠️ | — | trajectories | ✅ | ✅ |
| File checkpoints / rewind | ❌ | ✅ | — | — | — | via log |
| Run detached from the client | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Subagents | ⚠️ phase fan-out | ✅ typed, background, worktree | ✅ limits | ✅ | ext | ✅ |
| Subagent concurrency and time limits | ❌ | ✅ | ✅ 8 / timeout | ✅ | — | — |
| Hooks / event bus | ❌ | ✅ 33 events + function hooks | ✅ | ✅ | ✅ | ✅ everything |
| Plugins / packages | ⚠️ dynamic tools only | ✅ marketplaces | ✅ 4 kinds | ✅ skills hub | ✅ npm/git packages | ✅ |
| MCP client | ❌ | ✅ | ✅ | ✅ | ext | ✅ |
| Hot reload with disposal | ⚠️ no disposal | ✅ plugin reload | ✅ | ✅ | ✅ `/reload` | ✅ Cordis |
| Persistent scheduling | ❌ | ✅ | ✅ + heartbeat | ✅ | — | ✅ |
| Channels (chat platforms) | ⚠️ Telegram for approvals only | Slack, GitHub, IDE, mobile | ✅ ~10+ | ✅ 20+ | — | web UI |
| Tracing / metrics | ⚠️ never initialises | ✅ OTel | ✅ | ✅ | ext | ✅ telemetry from log |
| Run receipts with policy + snapshots | **✅ unique** | ⚠️ transcript | ⚠️ | ⚠️ | ❌ | ⚠️ log |
| Verification gate before "done" | ⚠️ file check only | ✅ Stop hooks, agent hooks | — | skill *Verification* section | ext | — |
| GitOps PR routing for changes | **✅ unique** | ❌ | ❌ | ❌ | ❌ | ❌ |

---

## 12. Cordis / DeepSeek paper mapping

| Paper concept | What it requires | Your implementation | Gap | Minimal fix |
|---|---|---|---|---|
| **Revertible effect** (`ctx.effect`) | Every change returns an inverse; the runtime holds it | `EffectStack.push(invoker, disposer)` exists; **nothing ever calls `push`** | Total | Registry API: `register_tool(...) -> Disposer`, `register_hook(...) -> Disposer`, `schedule(...) -> Disposer`. Disposers are stored on the owning plugin. |
| Effect composition to parent | A child's disposer becomes an effect on the parent | The scope is per run only; there's no parent/child | Total | `Plugin.dispose()` runs its own disposers in reverse, then its children's |
| **Revertible external effects** | Out of the paper's formal scope (it's about the in-process context), but your domain needs it | Before/after snapshot for pod restart only; "rollback" only waits | Large | Per tool: an optional `compensate(args, pre_state)` in the registry; GitOps revert PR as the compensation for PR-based changes |
| **Reactive coeffect** | Declared `inject` dependencies; automatic activation and deactivation | None. DevOps tools call Vault and Kubernetes directly and fail at call time | Total | `requires=["secrets","k8s"]` on a plugin. The registry only exposes its tools while the dependencies are healthy. A health probe updates the state. |
| **Unified context** | One context object mediates all effects and coeffects | Globals: module-level lists, `_approvers`, the scheduler, the registry | Large | A single `Engine`/`Context` object passed to plugins, with no module globals |
| **Fiber / component** | Instance, lifecycle state, parent, disposer | `LifecycleState` enum only, always ACTIVE, and only for agent profiles | Large | `Plugin` with `state`, `error`, `dispose`, `children` |
| **Lifecycle transitions** | `LOADING → ACTIVE → UNLOADING`; `FAILED` with error | Never transitions | Total | Set by the loader; `FAILED` removes the plugin's tools from the snapshot |
| **Transactional reload** | Build new, swap, dispose old; roll back on failure | `reload_registry` swaps dicts with rollback, but **has no caller**, and doesn't cover tools or plugins | Large | Build the new plugin set, validate (import, schema, dependency check), then atomically swap the registry snapshot, then dispose the old plugins. Runs in flight keep their snapshot. |
| **HMR** | Import-graph classification; dispose stale fibers | `importlib.reload` for dynamic tools after clearing global lists; old module side effects survive | Large | A file watcher on plugin directories: reload only changed plugins through the transactional path. Python caveat: `importlib.reload` doesn't free old objects. Load plugins with `importlib.util.spec_from_file_location` under a fresh module name, and rely on `dispose()` for cleanup. |
| **Confinement / isolation** | A component can't disturb others | Dynamic tools run in-process with full privileges | Critical | Out-of-process execution for untrusted and self-written code (§5 P0-1) |
| **Self-evolving harness** (paper §1.2.2) | Changes happen continuously and safely; a bad change must not disable recovery | A bad dynamic tool file can break `load_dynamic_tools()` for **every** run (an import error propagates) | Critical | Load each plugin in a `try`; a failure marks that plugin `FAILED` and the rest keep running; a quarantine directory; the engine never imports untrusted code |

**Readiness verdict:** *not ready* for safe self-modification. The fixes above are small, around 200–300 lines for the plugin and registry core, and they **replace** the current `EffectStack`, `LifecycleState`, `reload_registry` and `plugins/registry.py`, so total code goes down.

---

## 13. Where you are genuinely ahead

Keep and strengthen these. No reference agent has all of them.

1. **Deny-by-default risk table with named tiers (R0–R4).** Claude Code has modes and rules, and Hermes has pattern risk, but a *declared tier per operational action with default R4* is clean, auditable and fits DevOps well. **Upgrade:** compute the tier from `(tool, action, args, context)` (namespace, environment, taint), not just `(tool, action)`.
2. **RunReceipt with a per-action `PolicyDecision`, `approved_by`, and before/after snapshots.** This is a compliance-grade audit trail. **Upgrade:** make receipts a projection of the event log; sign them (hash chain) for tamper evidence.
3. **GitOps routing for changes.** Proposing a PR instead of mutating the cluster is the right default for production. **Upgrade:** a worktree-based implementation (P1-11); link the PR to the receipt; verify after merge (ArgoCD synced and healthy) as the verification step.
4. **Verification as a primitive.** The concept, "don't mark done until the outcome is observed", goes further than the others' defaults. **Upgrade:** a pluggable `Verifier` registry (file check, HTTP probe, Kubernetes rollout status, ArgoCD health, test command), declared per goal or per skill (Hermes skills have a *Verification* section; reuse that format), plus an optional verifier agent that hasn't seen the work.
5. **Provenance model (`EvidenceItem.provenance`, memory `authorship`).** This is the right foundation for injection defence and memory trust. **Upgrade:** actually use it (P1-8).
6. **An approval channel out of band.** A phone approval is great for operations work. **Upgrade:** P0-5.

---

## 14. Target architecture: smaller core, no lost features

### 14.1 Shape

```
engine/
  core/loop.py          ~250 LOC  stream, parallel reads, errors-as-results, retries/failover, budgets
  core/registry.py      ~150 LOC  Tool/Hook/Plugin registry, immutable snapshots, disposers (Cordis-lite)
  core/policy.py        ~200 LOC  rules (deny>ask>allow) + tier(args) + taint + approval broker
  core/log.py           ~150 LOC  append-only events (SQLite WAL), resume/fork/replay projections
  core/context.py       ~200 LOC  prompt builder, AGENTS.md, frozen memory, skills index, compaction
  core/settings.py      ~60 LOC   one pydantic-settings object (env > file > defaults)
  core/secrets.py       ~60 LOC   provider chain + TTL cache
plugins/                (each: plugin.py with register(ctx) returning disposers)
  fs/        read(paged), write, edit(exact-replace), grep, glob — workspace-confined
  shell/     bash with sandbox backend (docker|bwrap|none) + env filtering + command classifier
  web/       fetch (SSRF-guarded, html→md), search (pluggable backend)
  memory/    memory tool (add/replace/remove, limits, scanning), session_search (FTS5 over log)
  skills/    skills_list / skill_view / skill_manage (+ approval staging)
  subagents/ spawn (typed profiles, limits, worktree isolation)
  approvals/ telegram, api (broker adapters)
  devops/    kubectl, argocd, gitops (worktree), snapshots, verifiers, risk rules
  mcp/       MCP client (stdio/http), tools namespaced mcp__server__tool
  learning/  draft→stage→approve skills from verified runs; curator
  scheduler/ persistent cron + heartbeat
  telemetry/ OTel spans/metrics derived from log events
frontends/
  api.py (auth, detached runs, SSE tails log) · cli.py (print/json) · rpc.py (stdin/stdout, optional)
```

The core stays around 1,000 lines. Everything domain-specific becomes a plugin that can be reloaded.

### 14.2 Tool registry: replaces the long `if` chain

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: dict                      # JSON schema for parameters
    description: str
    handler: Callable[[dict, RunCtx], Awaitable[str]]   # sync handlers auto-wrapped in to_thread
    risk: Callable[[dict, RunCtx], RiskTier]            # computed from args (namespace, path, env)
    read_only: bool = False
    parallel_safe: bool = False
    output_limit: int = 8_000
    capability: str = "Generic"        # matched against AgentProfile.allowed_tools
    verify: Callable | None = None     # optional post-condition
    compensate: Callable | None = None # optional undo using pre-state

class Registry:
    def register_tool(self, owner: "Plugin", spec: ToolSpec) -> Disposer: ...
    def snapshot(self) -> "RegistrySnapshot": ...   # immutable, taken at run start
```

A single `invoke()` handles: capability check → risk → rules → hooks (`pre_tool`) → approval → pre-state → handler (timeout, cancellation) → output limit and spill → post-state → verify → hooks (`post_tool`) → log event → ActionRecord. **One path, applied to every tool, including MCP and dynamic tools.**

### 14.3 Event log: the single source of truth

```sql
CREATE TABLE events(
  id TEXT PRIMARY KEY, session_id TEXT, parent_id TEXT, seq INTEGER,
  type TEXT,            -- user_msg|assistant_msg|tool_call|tool_result|approval_req|approval_res|
                        -- compaction|branch_summary|model_change|interrupt|verification|outcome|custom
  payload JSON, created_at TEXT);
CREATE INDEX ev_session ON events(session_id, seq);
CREATE VIRTUAL TABLE events_fts USING fts5(text, content='events', content_rowid='rowid');
```

- **Messages for the model** are rebuilt from the active branch (from the leaf, following `parent_id`), honouring the latest `compaction` event.
- **Fork** is a new leaf from any event ID. **Resume** is appending to the leaf.
- **Receipts, SSE, webhooks, metrics and session search** are all *projections* or tails of this table.
- This alone fixes P0-11 and P0-12, P1-5, P1-7, the dreamer's input problem and the dashboard, and it lets you delete `analytics_daily`, `approval_queue` (becomes events), receipt JSON blobs and interruption columns.

### 14.4 Policy engine

```
decision = policy.decide(tool, args, ctx):
  1. hard blocklist (non-overridable)                       → DENY
  2. rules: deny → ask → allow (specifier match on args)    → first match
  3. tier = spec.risk(args, ctx) (+1 if ctx.tainted and not read_only)
     R0/R1 → ALLOW · R2/R3 → ASK · R4 → DENY
  4. hooks may tighten (ALLOW→ASK/DENY), never loosen a DENY
ASK → approval broker: request {action_id, tool, args_hash, rendered_args, diff/code, tier}
      → first authorised approver response, else timeout → fallback (DENY)
      → scope: once | session | always(persist as allow rule bound to args pattern)
      → re-check args_hash before execution
```

### 14.5 Context builder and compaction

Build the prompt in a **stable prefix order**:
1. fixed system prompt;
2. tools (sorted);
3. AGENTS.md / project instructions (scanned);
4. frozen memory snapshot (MEMORY.md ≤ 2.2k characters, USER.md ≤ 1.4k);
5. skills index (names and one-liners);
6. conversation.

Compaction as in §5 P0-9: prune tool outputs first, then an LLM summary at the cut point; save a `compaction` event; flush memory first.

### 14.6 Hook bus

Events: `session_start`, `before_turn`, `pre_tool` (can rewrite, block or ask), `post_tool`, `pre_compact`, `post_compact`, `stop` (can force continuation, which is how verification works as a hook), `session_end`. Handlers run in order with a per-hook budget (Claude Code uses 10 s); a failing hook is skipped and logged. Classic shell hooks can be supported through one adapter plugin (JSON on stdin, exit code 2 blocks).

### 14.7 Code budget effect

| Removed or replaced | Approx. LOC |
|---|---|
| Long `if` dispatch chain + duplicated approval blocks (5×) | −300 |
| Hard-coded schemas in the engine (moved into plugins) | −250 (moved) |
| Duplicated receipt building in api.py / cli.py | −60 |
| `EffectStack`, `LifecycleState`, `reload_registry`, `plugins/registry.py` | −110 → replaced by ~150 registry |
| Unused tables, curator/dreamer rewrites, fix scripts | −150 |
| **New core (loop, registry, policy, log, context, settings, secrets)** | +1,070 |

Net: roughly the same size as today's core, with **every** feature and all P0/P1 fixes in place, and domain code moved into reloadable plugins.

---

## 15. Prioritised roadmap with acceptance criteria

### Phase A (P0, security and correctness), about 1 week

| # | Task | Done when |
|---|---|---|
| A1 | Rotate the leaked Vault token; purge history; add gitleaks | The scan is clean in CI |
| A2 | API authentication + bind to 127.0.0.1 by default | An unauthenticated request returns 401 (test) |
| A3 | Gate `write_and_register_tool` behind `SelfEdit`; approval shows the code and hash; name validation; out-of-process execution | A read-only agent can't see the tool; traversal names are rejected (tests) |
| A4 | Workspace confinement for all file tools; SSRF guard for fetch | Tests: `/etc/passwd`, `../`, `169.254.169.254`, `127.0.0.1` are all refused |
| A5 | Approval broker: approver allowlist, timeout → deny, one consumer, argument hash | Concurrent approvals test; timeout test |
| A6 | Argument-aware risk (kube-system → R4, evaluated *before* running) | A restart in kube-system is denied without any API call (test) |
| A7 | Errors as tool results + loop guard | A denied approval or bad JSON produces a tool message and the run continues (test) |
| A8 | Fix the tracing import order; declare dependencies; `workflow_checkpoints` table | Clean `pip install .` then import works; orchestration test uses `init_db` |
| A9 | Outcome enum; correct success semantics | A budget-exhausted run is not `success` |

### Phase B (P1, loop, context and performance), 1–2 weeks

| # | Task | Done when |
|---|---|---|
| B1 | Event log + projections; resume and fork from any event | Fork at event N reproduces messages 1..N; the transcript validator passes |
| B2 | Token-based, cut-safe compaction with pruning, pinning, memory flush | Property test: 1,000 random transcripts still valid after compaction |
| B3 | Streaming + detached runs + cancel | Client disconnect doesn't cancel the run; `Last-Event-ID` resume works |
| B4 | Parallel read-only tools; `to_thread` for synchronous handlers | 5 parallel `get_pods` take about as long as one; another session stays responsive during a restart |
| B5 | Retries, backoff, failover from settings; per-model credentials | Simulated 429 recovers; the fallback model is used |
| B6 | Prompt caching with a stable prefix; drop JIT for small catalogues | Cache-read tokens > 0 from turn 2 (Anthropic) |
| B7 | Secret provider chain + cache; settings object; SQLite migrate once + WAL | Runs without Vault using environment variables; no DDL per request |
| B8 | Output limits per tool + `read_spill` | `kubectl_logs` result ≤ 8k characters with a spill path |

### Phase C (P2, feature parity), 2–3 weeks

| # | Task | Done when |
|---|---|---|
| C1 | Tools: bash (sandboxed, env-filtered, classifier), paged read, exact-replace edit | Coding-style tasks succeed without overwriting files |
| C2 | Memory tool (limits, scanning, frozen snapshot) + `session_search` over the log | The agent recalls a fact from a previous session |
| C3 | Skills: list / view / manage + approval staging + scanning; load existing SKILL.md | argocd-status-check is used when relevant; a new skill is staged, approved and listed |
| C4 | Hook bus + classic hook adapter | A PreToolUse script can block; a Stop hook can force verification |
| C5 | MCP client | An external MCP server's tools appear as `mcp__x__y` under policy |
| C6 | Subagents: typed profiles, limits, worktree isolation, shared budget | Orchestration uses profiles; `maxConcurrent` is enforced |
| C7 | Persistent cron + heartbeat + list/delete | Jobs survive a restart |
| C8 | AGENTS.md / project instructions (scanned) | Loaded in a stable position |

### Phase D (P3, your differentiators and Cordis), ongoing

| # | Task | Done when |
|---|---|---|
| D1 | Plugin fibers: disposers, lifecycle, dependencies, transactional reload, watcher | Unloading the DevOps plugin removes all its tools, jobs and listeners (test counts effects) |
| D2 | Verifier registry (Kubernetes rollout, ArgoCD health, HTTP, tests) + independent verifier agent | Runs that claim success without verification are marked `unverified` |
| D3 | Receipts as a signed projection (hash chain) | Tamper detection test |
| D4 | GitOps via worktree + post-merge verification | The user's checkout is never modified |
| D5 | Taint tracking from untrusted content → tier +1 | After `web_fetch`, an R1 edit requires approval |
| D6 | Optional "Code" mode: a typed, policy-wrapped SDK the model scripts against | A multi-namespace audit finishes in 1–2 model calls |

---

## 16. File-by-file notes

**`core/agent_engine.py`**
- L9-35 `EffectStack`/`EffectScope`: never populated; `print` used instead of logging.
- L37-61: OTel import-order bug (P0-7); `LiteLLMInstrumentor` dependency undeclared.
- L82-344: hard-coded schemas (move into plugins).
- L272-288 advisor: re-imports inside the function; uses the groq key path; no budget, and no caching of repeated advice.
- L353-367 spill: thresholds too high (§7.7); the file name uses a timestamp with second resolution, so collisions are possible within a second.
- L369-396 compaction: P0-9.
- L398-551 loop: P0-10, P1-1, P1-3, P1-7; `messages: list[...]` annotation inside `else` only; the arguments JSON is parsed twice (L501-502); the `max turns` error text is wrong (L546).
- L420: P0-1.
- L423: categories hard-coded; profile values like `Generic` / `Advisor` must be listed here to work.
- L460: count-based trigger.
- L628-837 `_dispatch_tool`: the long chain, with the approval block copied 4 times.
- L743: P0-6.
- L798-817: generic tools at R1 (P0-3); `result` could be unbound if the name set and branches ever diverge.
- L902-923 `_read_directory`: the only confined tool; good pattern, generalise it.

**`core/gateway/api.py`**
- No authentication (P0-4).
- `@app.on_event("startup")` is deprecated in favour of lifespan.
- `execute_session` is used only by the scheduler.
- Two receipt builders duplicated with cli.py.
- Not-atomic status check (P1-5); tasks without references (P1-9).
- `build_context` hard-codes `TriggerSource.cli` for API runs.

**`core/gateway/cli.py`** — Default tools include `DevOpsWrite`; there's no flag to choose a profile or tools; no `--json` stream mode.

**`core/gateway/telegram.py`** — P0-5; `_pending_approvals` is declared but unused.

**`core/gateway/webhooks.py`** — No signing or retry; a new client per call is acceptable.

**`core/gateway/workflow.py`** — Hard-coded plan; `datetime.utcnow()` is deprecated; a "resume" flag with a fixed ID.

**`core/memory/store.py`**
- `init_db` does DDL on every call (§7.6).
- Missing `workflow_checkpoints` (P0-8).
- `update_session` wipes the receipt (P0-11).
- `search_memory` side-effects `use_count`.
- `import json` in the middle of the file.

**`core/memory/dreamer.py`** — Unbounded prompt; deletes originals; no human-authored consolidation; groq key path.

**`core/memory/curator.py`** — Never called; `record_skill_outcome` is never called; runs `init_skill_metrics` on every call.

**`core/orchestration/executor.py`** — P0-8; no profiles, budget, concurrency cap or session ID; mutates the shared context; passes `repr` of results.

**`core/plugins/registry.py`** — P0-2; global mutable lists (§7.8); a failing plugin file breaks every run; `.rej` leftover shows a patch that half-applied.

**`core/primitives/*`** — Good Pydantic models with `extra="forbid"`. `policy.py` creates a tracer in a pointless `try`. `learning.py` validation-test synthesis only supports string equality, so it's too narrow for real skills.

**`core/registry.py`** — `list_agents` uses `__import__("typing").Any`; tidy that. `LifecycleState` never changes.

**`core/secrets.py`** — P1-6; hidden groq→llm redirect.

**`core/snapshots.py`** — Fine, but synchronous callables inside async code block the loop.

**`domains/devops/git_actions.py`** — P1-11. `GITOPS_MANAGED_ACTIONS` duplicates `TOOL_RISK_TABLE`; keep one source.

**`domains/devops/tools/*.py`** — `FastMCP` servers are defined but never run by the engine. Kubernetes client initialisation depends on Vault. `kubectl_describe_pod` returns the whole pod object as JSON, which is large: select fields.

**`domains/devops/snapshots.py`** — `time.sleep` polling (P1-4). "Rollback" is observation only.

**`domains/generic/tools.py`** — P0-3; `urllib.parse` is imported at the bottom of the file, which works but is fragile; DuckDuckGo HTML scraping will be rate-limited or blocked; returns raw HTML.

**`domains/devops/skills/use-the-read-directory-tool/SKILL.md`** — An example of the low-quality auto-draft. Delete it.

**`cli/setup.py`** — `questionary` undeclared; writes to the Vault mount without checking.

**`start.sh`** — Stale default models (`gpt-4o`, `claude-3-5-sonnet-20240620`, `llama-3.1-70b`). API keys are echoed into `.env` without `chmod 600`. `docker-compose` v1 syntax.

**`Dockerfile`** — `python:3.14-slim` while `pyproject` says ≥3.12 (fine). It runs a fixed goal; it doesn't run the API server. No non-root user.

**`docker-compose.yml`** — Dev-mode Vault (documented as such). `network_mode: host` exposes the unauthenticated API on the host network.

**`config/settings.yaml`** — Never read. `cnpg` Postgres settings suggest a planned Postgres move; the event log design in §14.3 ports cleanly.

---

## 17. Repository cleanup list

Delete or move out of the repository root:
- `fix_dreamer_secret.py`, `fix_engine_secret.py`, `fix_globals.py`, `fix_registry.py`, `fix_registry.patch`, `fix_registry_2.patch`, `fix_secrets.patch`
- `patch_jit4.py`, `patch_jit5.py`, `test_type.py`, `current_diff.patch` (empty), `core/plugins/registry.py.rej`
- `domains/devops/skills/use-the-read-directory-tool/` (auto-generated noise)
- `Deepseek-harness-paper.pdf` (2.4 MB) → `docs/refs/` or link to it instead
- Planning documents → `docs/` (keep README, GUIDE and DOCKER at the root)

Dependency hygiene (`pyproject.toml`):
- **Remove:** `claude-agent-sdk`; `mcp` (unless C5 is done).
- **Move to `dev` extras:** `pytest`, `pytest-asyncio`, `pytest-httpx`.
- **Add:** `questionary` (or drop it), the OTel LiteLLM instrumentation (or make it optional).
- **Split extras:** `[devops]` (kubernetes, GitPython, hvac), `[telegram]`, `[otel]`, so a generic install is light.

---

## 18. Sources

**Claude Code**
- [Permissions](https://code.claude.com/docs/en/permissions)
- [Hooks reference](https://code.claude.com/docs/en/hooks)
- [Sandboxing](https://code.claude.com/docs/en/sandboxing)
- [Checkpointing](https://code.claude.com/docs/en/checkpointing)
- The public `anthropics/claude-code` repository (mods, function-hook type contract), reviewed earlier in this session

**OpenClaw**
- [Gateway architecture](https://docs.openclaw.ai/concepts/architecture)
- [Sessions and subagents config](https://docs.openclaw.ai/gateway/config-tools/sessions-and-subagents)
- [Exec approvals](https://docs.openclaw.ai/tools/exec-approvals)
- [Sandbox vs tool policy vs elevated](https://docs.openclaw.ai/gateway/sandbox-vs-tool-policy-vs-elevated)
- [Compaction](https://docs.openclaw.ai/concepts/compaction)
- [Memory](https://docs.openclaw.ai/concepts/memory)

**Hermes Agent**
- [Documentation home](https://hermes-agent.nousresearch.com/docs/)
- [Persistent memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)
- [Skills system](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills)
- [Security](https://hermes-agent.nousresearch.com/docs/user-guide/security)
- [Configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)

**Pi**
- [pi.dev](https://pi.dev/)
- [Compaction](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/compaction.md)
- [Extensions](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md)
- [Session format](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/session-format.md)

**DeepSeek Harness and Cordis**
- [deepseek-ai/deepseek-harness (GitHub)](https://github.com/deepseek-ai/deepseek-harness)
- [DeepSeek Harness site](https://deepseek.com/harness/en/)
- [The New Stack coverage](https://thenewstack.io/deepseek-harness-open-source-plugins/)
- [InfoQ coverage](https://www.infoq.com/news/2026/08/deep-seek-harness/)
- Shi, Zhang, Cui, *A Programming Paradigm for Spatiotemporal Composability* (PDF in your repository): §1.2.2, §5.1.1, §5.2.2

**Other**
- [opentelemetry-instrumentation-litellm on piwheels](https://www.piwheels.org/project/opentelemetry-instrumentation-litellm/)
