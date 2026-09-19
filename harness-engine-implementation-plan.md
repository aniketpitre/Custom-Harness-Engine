# Harness Engine — Full Implementation Guide (Step 0 → Production)

**How to use this document:** This is a sequential build guide. Each phase has numbered steps. Each step states an objective, the exact files to create or modify, the code/schema/commands involved, and an acceptance criterion — a concrete way to know the step actually worked before moving to the next one. Do not skip acceptance criteria; every later phase assumes earlier ones are genuinely working, not just written.

**Companion document:** This guide implements the architecture specified in `harness-engine-master-architecture.md`. Read that document first — this one assumes its primitives, risk model, and technology choices as given and does not re-justify them.

**Two additions folded in that were missing from the master architecture:** Vault-based secrets management (Phase 5) and checkpoint/rollback for non-GitOps actions (Phase 8) — both identified as real gaps before implementation began, both integrated at the point in the sequence where skipping them would be expensive to retrofit later.

---

## Phase 0 — Environment and project setup

### Step 0.1 — Prerequisites check
Objective: confirm the build environment has everything the rest of the guide assumes.

```bash
python3 --version        # need 3.12+
node --version            # useful for MCP inspector tooling
git --version
docker --version           # needed from Phase 7 onward for sandboxing tests
```

Acceptance: all four commands return a version, no errors.

### Step 0.2 — Repository scaffold

```bash
mkdir -p harness-engine && cd harness-engine
git init
python3 -m venv .venv
source .venv/bin/activate
```

Create the directory structure exactly as specified in the master architecture, Section 10:

```bash
mkdir -p core/primitives core/orchestration core/memory core/gateway
mkdir -p domains/devops/tools domains/devops/skills domains/devops/verifiers
mkdir -p receipts tests/core tests/domains/devops config secrets data
touch core/__init__.py core/primitives/__init__.py core/orchestration/__init__.py
touch core/memory/__init__.py core/gateway/__init__.py
touch domains/__init__.py domains/devops/__init__.py domains/devops/tools/__init__.py
touch receipts/__init__.py main.py
```

Acceptance: `tree harness-engine -L 3` shows the structure matching Section 10 of the master document.

### Step 0.3 — Dependency manifest

Create `pyproject.toml`:

```toml
[project]
name = "harness-engine"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.6",
    "claude-agent-sdk",
    "mcp",
    "litellm",
    "python-telegram-bot>=21.0",
    "kubernetes",
    "docker",
    "paramiko",
    "GitPython",
    "psycopg[binary]>=3.1",
    "hvac",
    "opentelemetry-sdk",
    "opentelemetry-exporter-otlp",
    "pytest",
    "pytest-asyncio",
    "pyyaml",
]
```

```bash
pip install -e .
```

Acceptance: `pip list` shows all packages installed with no version conflicts.

### Step 0.4 — Base configuration files

Create `config/settings.yaml`:

```yaml
environment: development
domain_default: devops
cnpg:
  host: localhost
  port: 5432
  database: harness_receipts
vault:
  address: http://localhost:8200
  mount_point: harness-secrets
telegram:
  approval_chat_id: null   # fill in Phase 6
model:
  primary: claude-sonnet-4-6
  fallback: openrouter/anthropic/claude-sonnet-4-6
otel:
  endpoint: http://localhost:4317
```

Create `config/risk_defaults.yaml` (empty scaffold, populated in Phase 6):

```yaml
devops: {}
```

Acceptance: both files parse with `yaml.safe_load` without error.

### Step 0.5 — Version control hygiene

Create `.gitignore`:

```
.venv/
__pycache__/
*.pyc
.env
data/
secrets/*.local
config/settings.local.yaml
```

**Critical, given documented history of leaked tokens:** never commit `config/settings.local.yaml` or anything under `secrets/`. Confirm this file is in `.gitignore` before the first commit, not after.

Acceptance: `git status` after creating a dummy file under `secrets/` shows it as ignored.

---

## Phase 1 — Core primitives (schemas only, no execution)

### Step 1.1 — Goal primitive
Create `core/primitives/goal.py` with `Goal` and `TriggerSource` exactly as specified in master architecture Section 3.1.

### Step 1.2 — Context and Evidence primitives
Create `core/primitives/context.py` and `core/primitives/evidence.py` implementing `ContextPacket`, `EvidenceItem`, and a `Provenance` enum (`user-input`, `tool-observed`, `external-fetched`, `human-reviewed`) per Sections 3.2, 3.3, and 8.

### Step 1.3 — Policy primitive
Create `core/primitives/policy.py` implementing `RiskTier` (R0–R4) and `PolicyDecision` per Section 3.6. Leave `TOOL_RISK_TABLE` empty — populated in Phase 6.

### Step 1.4 — Execution and Run Receipt primitives
Create `core/primitives/execution.py` implementing `ActionRecord` and `RunReceipt` per Section 3.8. Add checkpoint fields now, even though Phase 8 implements the logic — cheaper to add an unused field early than to retrofit later:

```python
class ActionRecord(BaseModel):
    tool: str
    action: str
    policy_decision: "PolicyDecision"
    approved_by: str | None
    started_at: datetime
    finished_at: datetime
    raw_result: str
    pre_state_snapshot: dict | None = None   # Phase 8
    post_state_snapshot: dict | None = None  # Phase 8
    rollback_available: bool = False          # Phase 8
```

### Step 1.5 — Verification primitive
Create `core/primitives/verification.py` implementing `VerificationResult` per Section 3.9.

### Step 1.6 — Learning primitive
Create `core/primitives/learning.py` implementing `CandidateSkill` per Section 3.10, including the `status` state machine (`pending_approval` → `validated`/`rejected` → `active`) and `version` field.

### Step 1.7 — Unit tests for every primitive
Create `tests/core/test_primitives.py`. For each primitive, write a test constructing a valid instance (asserts it validates) and one constructing an invalid instance (asserts Pydantic raises).

```bash
pytest tests/core/test_primitives.py -v
```

Acceptance: all tests pass. This phase is schema-only — nothing talks to a real tool, database, or model, and that's correct.

---

## Phase 2 — Minimal end-to-end loop

### Step 2.1 — Claude Agent SDK wrapper
Create `core/agent_engine.py`:

```python
from claude_agent_sdk import query, ClaudeAgentOptions
from core.primitives.context import ContextPacket

async def run_agent(context: ContextPacket, allowed_tools: list[str]) -> dict:
    options = ClaudeAgentOptions(
        allowed_tools=allowed_tools,
        permission_mode="acceptEdits",
    )
    events = []
    async for message in query(prompt=_build_prompt(context), options=options):
        events.append(message)
    return {"events": events, "final_text": _extract_final_text(events)}

def _build_prompt(context: ContextPacket) -> str:
    return f"Goal: {context.goal.raw_input}\n\nRelevant context:\n{context.live_state}"

def _extract_final_text(events: list) -> str:
    # pull the last text block from the SDK's event stream
    ...
```

### Step 2.2 — First trigger: CLI
Create `core/gateway/cli.py`:

```python
import asyncio, uuid
from datetime import datetime
from core.primitives.goal import Goal, TriggerSource
from core.primitives.context import ContextPacket
from core.agent_engine import run_agent

async def handle_cli_input(raw_text: str):
    goal = Goal(id=str(uuid.uuid4()), source=TriggerSource.cli,
                raw_input=raw_text, created_at=datetime.utcnow())
    context = ContextPacket(goal=goal, memory_hits=[], live_state={},
                             recent_history=[], tool_catalog=[])
    result = await run_agent(context, allowed_tools=["Read"])
    print(result["final_text"])

if __name__ == "__main__":
    import sys
    asyncio.run(handle_cli_input(" ".join(sys.argv[1:])))
```

### Step 2.3 — Smoke test

```bash
python -m core.gateway.cli "List the files in the current directory"
```

Acceptance: Claude responds with an actual directory listing, proving the trigger → Goal → Context → Agent Engine → tool call → response path works end to end with real tool use.

### Step 2.4 — Wire a trivial Run Receipt (not persisted yet)
Extend `handle_cli_input` to construct a `RunReceipt` from the run (no evidence/verification yet — those arrive later) and print it as JSON instead of just the text.

Acceptance: a well-formed `RunReceipt` JSON object prints, containing at minimum `goal`, `model_used`, and an empty `actions` list.

---

## Phase 3 — Verification, for real

### Step 3.1 — Choose the test action
Use a deliberately simple, checkable action: create a file with specific content, then verify the file exists with that content. This isolates the verification mechanism from domain complexity.

### Step 3.2 — Implement the verifier

```python
def verify_file_content(path: str, expected_content: str) -> "VerificationResult":
    from pathlib import Path
    from datetime import datetime
    observed = Path(path).read_text() if Path(path).exists() else "<missing>"
    return VerificationResult(
        expected=expected_content, observed=observed,
        passed=(observed.strip() == expected_content.strip()),
        method="file_check", checked_at=datetime.utcnow(),
    )
```

### Step 3.3 — Prove it catches a real failure
Write two tests: one where the action succeeds and verification passes, one where you deliberately corrupt the expected value and confirm verification correctly reports `passed=False`.

```bash
pytest tests/core/test_verification.py -v
```

Acceptance: both cases behave correctly — proof Verification is a real gate, not a rubber stamp.

---

## Phase 4 — Memory (SQLite FTS5) with provenance

### Step 4.1 — Database schema
Create `core/memory/store.py` with the schema from master document Section 8 (`memory_entries` + `memory_fts`), including `provenance` and `authorship` columns:

```python
import sqlite3
from pathlib import Path

DB_PATH = Path("data/memory.db")

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS memory_entries (
        id TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        authorship TEXT NOT NULL CHECK (authorship IN ('human-authored','agent-created')),
        provenance TEXT NOT NULL CHECK (provenance IN ('user-input','tool-observed','external-fetched','human-reviewed')),
        domain TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        use_count INTEGER DEFAULT 0
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
        content, content='memory_entries', content_rowid='rowid'
    );
    """)
    conn.commit()
    return conn
```

### Step 4.2 — Write and search functions

```python
def add_memory(conn, id_: str, content: str, authorship: str, provenance: str, domain: str):
    from datetime import datetime
    conn.execute(
        "INSERT INTO memory_entries (id, content, authorship, provenance, domain, created_at) VALUES (?,?,?,?,?,?)",
        (id_, content, authorship, provenance, domain, datetime.utcnow().isoformat()),
    )
    conn.commit()

def search_memory(conn, query: str, domain: str, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        """SELECT e.id, e.content, e.authorship, e.provenance
           FROM memory_fts f JOIN memory_entries e ON f.rowid = e.rowid
           WHERE memory_fts MATCH ? AND e.domain = ?
           ORDER BY rank LIMIT ?""",
        (query, domain, limit),
    ).fetchall()
    return [{"id": r[0], "content": r[1], "authorship": r[2], "provenance": r[3]} for r in rows]
```

### Step 4.3 — Seed test data and prove retrieval works

```bash
python -c "
from core.memory.store import init_db, add_memory, search_memory
conn = init_db()
add_memory(conn, 'note-1', 'ArgoCD sync failures are usually caused by webhook drift', 'human-authored', 'human-reviewed', 'devops')
print(search_memory(conn, 'ArgoCD sync', 'devops'))
"
```

Acceptance: the search returns `note-1` with correct authorship/provenance tags.

### Step 4.4 — Wire Context assembly to Memory
Modify `handle_cli_input` so `ContextPacket.memory_hits` is populated by a real `search_memory` call using the Goal's `raw_input` as the query.

Acceptance: rerun the Phase 2.3 smoke test after seeding a relevant memory entry — confirm the entry appears in the `ContextPacket` passed to the Agent Engine (temporary print statement to verify, then remove it).

---

## Phase 5 — Secrets management (Vault)

*Inserted here because Phase 6's Telegram bot token and Phase 7's cluster credentials both need a real secrets path — retrofitting after those phases exist means migrating already-deployed secrets.*

### Step 5.1 — Vault connectivity
Assumes HashiCorp Vault is already running in your homelab. Create `core/secrets.py`:

```python
import hvac, os

def get_vault_client() -> hvac.Client:
    client = hvac.Client(
        url=os.environ["VAULT_ADDR"],
        token=os.environ["VAULT_TOKEN"],   # never hardcode; injected via environment only
    )
    if not client.is_authenticated():
        raise RuntimeError("Vault authentication failed")
    return client

def get_secret(path: str, key: str) -> str:
    client = get_vault_client()
    resp = client.secrets.kv.v2.read_secret_version(path=path, mount_point="harness-secrets")
    return resp["data"]["data"][key]
```

### Step 5.2 — Seed the first secrets

```bash
vault kv put harness-secrets/telegram bot_token="<your-real-token-here>"
vault kv put harness-secrets/kubernetes kubeconfig_path="/home/claude/.kube/config"
```

**Critical:** run this from your terminal directly. Never paste a real token into a chat session, a committed file, or a script argument that ends up in shell history without `HISTIGNORE` set.

### Step 5.3 — Retrofit the environment loader
Every later phase that needs a credential calls `get_secret(...)`, never `os.environ` directly for anything sensitive, and never a hardcoded value.

Acceptance: `python -c "from core.secrets import get_secret; print(get_secret('telegram','bot_token'))"` prints the real token, and grepping the entire repo for that token string returns zero matches outside this one runtime call.

---

## Phase 6 — Policy Engine and Approval Gate

### Step 6.1 — Populate the real risk table
Create `domains/devops/policy_table.py`:

```python
from core.primitives.policy import RiskTier

TOOL_RISK_TABLE = {
    ("kubectl", "get"): RiskTier.R0,
    ("kubectl", "describe"): RiskTier.R0,
    ("kubectl", "logs"): RiskTier.R0,
    ("argocd", "app_list"): RiskTier.R0,
    ("argocd", "app_get"): RiskTier.R0,
    ("kubectl", "restart_pod"): RiskTier.R2,
    ("argocd", "app_sync_staging"): RiskTier.R2,
    ("argocd", "app_sync_production"): RiskTier.R3,
    ("kubectl", "delete_namespace"): RiskTier.R4,
    ("terraform", "destroy"): RiskTier.R4,
}
```

### Step 6.2 — Policy resolution function
Add to `core/primitives/policy.py` the `resolve_policy` function per master document Section 3.6's `policy_engine_hook`, generalized to accept any domain's risk table.

### Step 6.3 — Telegram Approval Gate
Create `core/gateway/telegram.py`:

```python
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler
from core.secrets import get_secret
import asyncio

_pending_approvals: dict[str, asyncio.Future] = {}

async def request_approval(action_id: str, description: str, risk_tier: str) -> bool:
    bot = Bot(token=get_secret("telegram", "bot_token"))
    chat_id = get_secret("telegram", "approval_chat_id")
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{action_id}"),
        InlineKeyboardButton("❌ Deny", callback_data=f"deny:{action_id}"),
    ]])
    await bot.send_message(chat_id=chat_id,
        text=f"Risk tier {risk_tier}\n{description}\n\nApprove this action?",
        reply_markup=keyboard)
    future = asyncio.get_event_loop().create_future()
    _pending_approvals[action_id] = future
    return await future

async def handle_callback(update, context):
    decision, action_id = update.callback_query.data.split(":")
    if action_id in _pending_approvals:
        _pending_approvals[action_id].set_result(decision == "approve")
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        f"{'Approved' if decision == 'approve' else 'Denied'}."
    )
```

### Step 6.4 — Wire the PreToolUse hook
In `core/agent_engine.py`, connect the Agent SDK's `PreToolUse` hook to `resolve_policy`, and for `REQUIRE_APPROVAL` outcomes, to `request_approval` (Step 6.3), blocking tool execution until it resolves.

### Step 6.5 — End-to-end approval test
Manually trigger an action mapped to R3 (use a fake/test tool, not a real production action yet) and confirm:
1. A Telegram message with Approve/Deny buttons arrives.
2. Tapping Deny genuinely blocks execution — the tool call never runs.
3. Tapping Approve lets it proceed, and the resulting `ActionRecord.approved_by` is populated with your Telegram user id.

Acceptance: all three behaviors confirmed manually, at least once each.

---

## Phase 7 — DevOps domain pack v1 (read-only)

### Step 7.1 — MCP server for kubectl (R0 only)
Create `domains/devops/tools/kubectl_tools.py`:

```python
from mcp.server.fastmcp import FastMCP
from kubernetes import client, config

mcp = FastMCP("devops-kubectl")
config.load_kube_config()  # path resolved via Vault secret from Phase 5, not hardcoded
v1 = client.CoreV1Api()

@mcp.tool(risk_tier="R0")
def kubectl_get_pods(namespace: str) -> str:
    """Read-only: list pods and their status in a namespace."""
    pods = v1.list_namespaced_pod(namespace)
    return "\n".join(f"{p.metadata.name}: {p.status.phase}" for p in pods.items)

@mcp.tool(risk_tier="R0")
def kubectl_describe_pod(namespace: str, pod_name: str) -> str:
    """Read-only: full description of a single pod."""
    pod = v1.read_namespaced_pod(pod_name, namespace)
    return str(pod.status)
```

### Step 7.2 — MCP server for ArgoCD (R0 only)
Create `domains/devops/tools/argocd_tools.py` with `argocd_app_list` and `argocd_app_get`, both R0, wrapping the `argocd` CLI via subprocess (or the ArgoCD REST API for cleaner error handling).

### Step 7.3 — Register the MCP servers with the Agent Engine
Update the tool catalog assembly in `core/agent_engine.py` to include both MCP servers, restricted to R0 tools only at this phase.

### Step 7.4 — First real skill
Create `domains/devops/skills/argocd-status-check/SKILL.md` exactly as specified in master document Section 3.5.

### Step 7.5 — End-to-end real-cluster test

```bash
python -m core.gateway.cli "Is everything in sync in the homelab cluster right now?"
```

Acceptance: Claude calls `argocd_app_list` (a real R0 tool against your real k3s homelab), gets real data back, and produces an accurate summary — and the skill from Step 7.4 visibly influences its approach.

---

## Phase 8 — Checkpointing and rollback (non-GitOps actions)

*Inserted before write actions exist in Phase 9/10, so the rollback mechanism is proven before anything genuinely mutating is allowed to run.*

### Step 8.1 — PreState/PostState snapshot concept

```python
async def execute_with_snapshot(tool_fn, pre_state_fn, post_state_fn, *args, **kwargs):
    pre_state = pre_state_fn(*args, **kwargs)
    result = await tool_fn(*args, **kwargs)
    post_state = post_state_fn(*args, **kwargs)
    return result, pre_state, post_state
```

### Step 8.2 — Domain-specific snapshot functions
Create `domains/devops/snapshots.py`:

```python
def pod_snapshot(namespace: str, pod_name: str) -> dict:
    pod = v1.read_namespaced_pod(pod_name, namespace)
    return {"replicas": pod.spec.containers[0].resources, "status": pod.status.phase}

def rollback_pod_restart(namespace: str, pod_name: str, pre_state: dict):
    # if the pod is now unhealthy and wasn't before, restore from
    # the last known-good ReplicaSet
    ...
```

### Step 8.3 — Wire snapshot capture into R2 actions
Modify the `PostToolUse` hook so any R2-tagged action automatically captures pre/post snapshots and sets `ActionRecord.rollback_available = True` when a rollback function exists.

### Step 8.4 — Prove rollback works on a real, safe R2 action
Test against a genuinely reversible action in your homelab (e.g. restart a non-critical pod in a test namespace). Confirm: pre-state captured, action executes, post-state captured, and a manual rollback call restores the pre-state condition.

Acceptance: a real restart-and-rollback cycle completes correctly against your k3s homelab, not a mock.

---

## Phase 9 — Learning loop

### Step 9.1 — Skill drafting trigger
Implement `draft_skill_if_warranted` (master document Section 3.10) exactly, wired to fire after any `RunReceipt` with ≥5 actions and `verification.passed == True`.

### Step 9.2 — Validation test synthesis
Add `synthesize_validation_test(receipt)` to `core/primitives/learning.py` — generates a `pytest`-style assertion from the receipt's verification logic (start simple: reuse the same expected/observed check that passed during the run, parameterized).

### Step 9.3 — Approval-gated promotion flow

```python
async def promote_candidate_skill(candidate: CandidateSkill):
    approved = await request_approval(
        action_id=candidate.derived_from_run,
        description=f"New skill proposed:\n{candidate.proposed_body[:300]}",
        risk_tier="SKILL_PROMOTION",
    )
    if not approved:
        candidate.status = "rejected"
        return candidate
    test_passed = run_validation_test(candidate.validation_test)
    if not test_passed:
        candidate.status = "rejected"
        return candidate
    candidate.status = "validated"
    write_skill_to_registry(candidate, authorship="agent-created")
    return candidate
```

### Step 9.4 — End-to-end learning test
Run a real multi-step task (≥5 tool calls) against your homelab, approve the resulting skill draft via Telegram, confirm the validation test runs and passes, and confirm the skill file appears in the registry tagged `agent-created`.

Acceptance: a real learned skill reaches `validated` status and is retrievable in a later, separate run.

### Step 9.5 — Weekly Curator job
Create `core/memory/curator.py`:

```python
def prune_agent_created_skills(conn, min_success_rate: float = 0.5, min_uses: int = 3):
    candidates = conn.execute(
        "SELECT id, use_count FROM memory_entries WHERE authorship='agent-created'"
    ).fetchall()
    for id_, use_count in candidates:
        if use_count >= min_uses and _success_rate(id_) < min_success_rate:
            conn.execute("DELETE FROM memory_entries WHERE id=?", (id_,))
    conn.commit()
    # human-authored entries are never touched -- no query above selects them
```

Schedule via cron (`0 3 * * 0` — weekly). Acceptance: manually insert a low-performing agent-created entry and a human-authored entry with the same low score, run the curator, confirm only the agent-created one is removed.

---

## Phase 10 — Write actions and GitOps path

### Step 10.1 — Git-based action wrapper
Create `domains/devops/git_actions.py` using `GitPython`: create a branch, write the manifest change, commit, push, open a PR via GitHub's API or CLI.

### Step 10.2 — Route R2+ actions through the GitOps path by default
Any action above R1 with a GitOps-manageable equivalent goes through Step 10.1's path, never a direct cluster call — the slow path never mutates the cluster directly.

### Step 10.3 — ArgoCD sync as the actual mutation point
Confirm ArgoCD, not the harness, performs the actual cluster write once a PR merges — the harness's role ends at "PR opened and merged."

### Step 10.4 — End-to-end write test
Trigger a real, low-risk R2 change (e.g. a resource limit adjustment on a test deployment), approve it via Telegram, confirm a real PR appears in GitHub, merge it manually, confirm ArgoCD syncs the change.

Acceptance: the full loop — proposal → approval → PR → merge → ArgoCD sync → Verification confirms new state — completes against real homelab infrastructure.

---

## Phase 11 — Observability

### Step 11.1 — OpenTelemetry instrumentation
Wrap `run_agent`, the Policy Engine, and the Execution layer with OTel spans. Export to your existing Prometheus/Grafana via the OTLP endpoint in `config/settings.yaml`.

### Step 11.2 — Grafana dashboard
Build a dashboard showing: runs per hour, policy decisions by outcome (ALLOW/REQUIRE_APPROVAL/DENY), verification pass rate, skill promotion rate over time.

Acceptance: a real run appears as a real trace in Grafana within seconds of completing.

---

## Phase 12 — Orchestration layer (dynamic multi-agent workflows)

### Step 12.1 — Orchestration primitives
Implement `OrchestrationPlan`, `Phase`, `SubagentSpec` exactly per master document Section 4.

### Step 12.2 — Fan-out executor

```python
import asyncio

async def execute_phase(phase: "Phase", context: ContextPacket) -> list[dict]:
    tasks = [
        run_agent(context, allowed_tools=spec.tool_scope)
        for spec in phase.subagent_specs
    ]
    return await asyncio.gather(*tasks)
```

### Step 12.3 — Adversarial cross-check phase
Implement a second `execute_phase` call whose `subagent_specs` are scoped to re-verify the first phase's findings against an independent source (e.g. Git manifest vs. live cluster state).

### Step 12.4 — Convergence loop and checkpoint table

```sql
CREATE TABLE workflow_checkpoints (
    workflow_id TEXT,
    phase_index INTEGER,
    status TEXT,
    result_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (workflow_id, phase_index)
);
```

Write resume logic: on restart, query the last completed `phase_index` for a `workflow_id` and continue from there instead of restarting.

### Step 12.5 — The real test case
Implement and run the full example from master document Section 4: audit every namespace across AKS/EKS/k3s for `privileged: true` pods or missing resource limits, cross-check each finding against Git, report only confirmed issues.

Acceptance: the workflow completes, produces one consolidated `RunReceipt`, findings that don't survive the adversarial cross-check are correctly dropped, and interrupting the process mid-run and restarting resumes rather than re-scanning from zero.

---

## Phase 13 — Hardening

### Step 13.1 — Sandbox configuration
Configure the Agent SDK's filesystem/network sandbox settings per master document Section 9, explicit deny-lists for `~/.ssh`, `~/.aws`, Vault tokens, kubeconfig files outside the harness's own read path.

### Step 13.2 — Durable, independently-queryable child runs
Extend the checkpoint table (Step 12.4) so a child run's status can be queried independently of whether its parent workflow is still active.

### Step 13.3 — Automated rollback on detected violation
Wire a `PostToolUse` anomaly check (start simple: did this action touch a path/resource outside its declared scope) that, if triggered, calls the Step 8.2-style rollback function automatically and immediately, without waiting for a human.

### Step 13.4 — Static analysis on candidate skills
Before Step 9.3's promotion flow runs the validation test, add a static content scan on `candidate.proposed_body` for suspicious patterns (embedded credentials, instructions to disable other checks, unexpected external URLs) — reject automatically if found, before a human even sees the approval request.

Acceptance for the whole phase: deliberately attempt an out-of-scope action in a test environment and confirm automated rollback fires without manual intervention; deliberately craft a malicious-looking candidate skill and confirm it's rejected before reaching the Telegram approval step.

---


## Phase 14 — Unified Control Plane & API Constructs

*This phase evolves the Harness from a localized data-plane script into an independent, API-driven backend.*

### Step 14.1 — Declarative Agent Registry
Implement YAML-based Agent Definitions (e.g., `agents/sre-agent.yaml`) that decouple agent profiles from the engine. This replaces hardcoded `DEVOPS_READ_TOOLS` with dynamic tool/model configurations.

### Step 14.2 — Durable Session Management
Refactor `RunReceipt` logic into a long-lived `Session` entity stored in the database. A session binds an Agent, an Environment, and a Task, persisting across HTTP requests.

### Step 14.3 — REST API Gateway
Build a FastAPI layer with explicit endpoints to create sessions, list agents, and post initial events, replacing the CLI entry point as the primary interface.

---

## Phase 15 — Event Streaming & Iterative Interactivity

### Step 15.1 — Server-Sent Events (SSE)
Refactor the `for _ in range(8):` blocking loop in `agent_engine.py` into an async generator. Yield `agent.message`, `agent.tool_use`, and `session.status_idle` dynamically to the client over an SSE connection.

### Step 15.2 — Mid-Task Steering (Interruptions)
Implement a listener thread or DB flag allowing a `user.interrupt` or `user.message` HTTP call to inject steering text directly into an active, running session's context, or gracefully halt it mid-tool.

---

## Phase 16 — Context & Execution Hardening

### Step 16.1 — Large Output Spilling
Implement an automatic truncation boundary (e.g., 100,000 characters). When a tool like `kubectl logs` exceeds this, automatically write the output to a safe sandbox file and return only a truncated preview + filepath back to the LLM context.

### Step 16.2 — Token & Cost Budgets
Replace the static 8-turn counter with a hard budget model. Track token usage limits per `Session` via LiteLLM token counting, forcefully returning `budget_reached` upon constraint breach.

### Step 16.3 — Standard Generic Toolset 
Build capabilities native to pure file and web interaction independent of DevOps: `grep`, `glob`, `edit`, `web_search`, and `web_fetch`.

---

## Phase 17 — Background Infrastructure Support

### Step 17.1 — Scheduled Agents
Introduce a background scheduler (e.g., APScheduler) allowing users to register declarative cron jobs that automatically instantiate specific Agents and goals against target Environments.

### Step 17.2 — Memory Consolidation ("Dreams")
Implement an async background task that scans SQLite FTS5 memories across sessions to consolidate duplicates, prune stale configuration knowledge, and summarize themes (going beyond simple use-count deletion).

### Step 17.3 — Advisor Sub-Inference
Add an `advisor` tool parameter that allows a Primary Agent to pause its execution, hand its current transcript state to a cheaper/faster model (or specialized security model), and receive strategic guidance before proceeding.

### Step 17.4 — Webhooks
Develop a webhook dispatcher that fires outbound HTTP payloads to registered endpoints (CI/CD pipelines, internal ticketing systems) on session completion or failure.

---

## Final acceptance — the system is "done" for v1 (Phases 0-13) when

- A real DevOps goal, given via Telegram, flows through Goal → Context → Agent → Policy → (approval if needed) → Execution → Verification → Receipt → Learning check, against real k3s/AKS/EKS infrastructure.
- At least one skill has been learned, approved, validated, and reused.
- At least one R2 action has been executed and, separately, rolled back successfully.
- At least one write action has gone through the full GitOps PR path and been verified post-merge.
- The multi-agent orchestration test case (Phase 12.5) has completed successfully at least once, including a resume-after-interruption test.
- Secrets are confirmed to exist only in Vault, never in source, config, or shell history.
- A Grafana dashboard shows real traces from real runs.

At that point, the core framework is genuinely operational, transitioning from an interactive CLI engine to an asynchronous, robust backend platform ready for Phase 14-17 (Control Plane).
