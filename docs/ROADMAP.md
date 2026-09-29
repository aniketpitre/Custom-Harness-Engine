# Roadmap: what is left compared with other agents

Written after Phases A to D, the single-command install, keyring secrets, the terminal approval prompt,
release automation and the DevOps CLI theme. Sources are public web pages found by search in September 2026
(listed at the end); the vendors' own documentation sites could not be fetched from the build environment, so
competitor capabilities below come from search summaries and third-party guides, not from reading their code.
Treat the "others" column as a good-faith snapshot, not a certified comparison.

## 1. Where the harness stands today

| Area | Harness Engine | Industry reference | Verdict |
|---|---|---|---|
| Safety and policy | Argument-aware R0 to R4 tiers, deny > ask > allow rules, taint tracking, args-hash-bound approvals, timeouts deny | Claude Code permission modes and hooks; OWASP Agentic Top 10 | **Ahead** on rigour (see `docs/OWASP_AGENTIC_MAPPING.md`) |
| Audit | Hash-chained event log, optional HMAC, receipts as projections, resume/fork | Transcripts (Claude Code, OpenClaw) | **Ahead** (tamper-evident) |
| Install | One command, `harness init/doctor`, keyring secrets, wheel + installer | Same one-liner style | **On par** |
| Approvals | Terminal, API and Telegram at once, first answer wins | Claude Code: terminal only; OpenClaw: chat channels | **On par**, Slack missing |
| Verification | Verifier registry, independent verifier agent | Rare elsewhere | **Ahead** |
| DevOps depth | kubectl, ArgoCD, GitOps via worktree, protected namespaces | HolmesGPT: 30+ observability toolsets, alert-triggered investigation, runbooks | **Behind** on breadth (observability) |
| Interactive use | `harness chat` (multi-turn, inline approvals, slash commands, resume), `harness run`, API + SSE | Claude Code, Hermes, OpenClaw: full interactive TUI/REPL | **Behind** |
| Channels | Telegram, terminal, API | OpenClaw: 20+ channels; Hermes: messaging platforms | **Behind** (Slack/Teams matter most for DevOps) |
| Cost | Per-call USD in the event log, USD budget, `harness cost`, `GET /usage`, cost in receipts and session lists | Claude Code `/cost` and status line; OpenClaw usage tracking | **On par** |
| MCP | Client, stdio transport only | Remote (HTTP) servers with OAuth; agents that are themselves MCP servers | **Behind** |
| Extension packaging | In-tree plugins, `SKILL.md` skills | Claude Code plugins bundle skills, subagents, hooks, MCP; Agent Skills is now an open format with 46+ adopting products | **Behind** on distribution |
| Web UI | Dashboard at `/ui`: sessions with live timelines, approvals, usage, schedules, agents, plugins | OpenClaw Control UI | **Behind** |
| Observability | OTLP spans | OpenTelemetry GenAI semantic conventions (`gen_ai.*` attributes) | **Partial**: spans exist, standard attribute names not adopted |
| Supply chain | Gitleaks in CI, AST allowlist for dynamic tools | Signed artefacts, SBOM, provenance, dependency updates | **Partial** (this change adds SBOM/provenance and Dependabot) |
| CLI experience | Themed CLI (this change) | Hermes: 10 built-in skins and YAML skins; OpenClaw: lobster identity | **On par** after this change |

## 2. The theme (shipped in this change)

`harness theme list|show|set NAME`, `HARNESS_THEME`, and `~/.harness/skins/NAME.yaml`. The mascot is the ship's
wheel (helm), the DevOps nod to Kubernetes. Six built-in skins: `helm` (default), `harbor`, `ember` (on-call),
`forest`, `midnight`, `mono`. A skin controls colours, glyphs, the risk-tier markers (🟢🟡🟠🔴⛔), the approval
prompt text, the tagline and the spinner verbs ("reconciling", "rolling out", "draining nodes"...). User skins
inherit any key they omit, like Hermes skins. Styling appears only on an interactive terminal: piped output,
`--json` and receipts never contain escape codes. `NO_COLOR`, `HARNESS_ASCII=1` and `HARNESS_PLAIN=1` are honoured.

## 3. Prioritised plan (Phase E onward)

### E1: professional baseline (do next)

| # | Item | Why | Size |
|---|---|---|---|
| E1.1 | **Done.** Cost accounting: per-call, per-session and per-agent USD from LiteLLM's price map, a `max_cost_usd` budget, `harness sessions` shows cost, cost in receipts | Every reference agent shows cost; teams need a spend ceiling | S |
| E1.2 | **Done.** `harness chat` (`cli/chat.py`): interactive REPL on the existing engine (streaming, `/rewind`, `/cost`, `/theme`, `/approve`), themed status line | Biggest usability gap versus Claude Code, Hermes and OpenClaw | M |
| E1.3 | **Done.** Permission modes (`core/modes.py`; `accept-edits` dropped because workspace edits are already R1 and run without asking): `plan` (read-only until the plan is approved), `read-only`, `strict` | Familiar mental model; maps onto the existing tiers, so small | S |
| E1.4 | **Done.** Headless contract (`core/headless.py`, `action.yml`): `--output-format json|stream-json`, `--max-cost`, stable exit codes, a reusable GitHub Action | CI use is a headline use case for DevOps | S |
| E1.5 | OpenTelemetry GenAI conventions: `gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.*`, tool spans | Lets any OTel backend read our traces unchanged | S |

### E2: DevOps differentiators (what makes this the DevOps harness)

| # | Item | Notes |
|---|---|---|
| E2.1 | Alert-to-investigation: Alertmanager, PagerDuty and generic webhooks start a **read-only** investigation session | Webhook plumbing exists (`core/gateway/webhooks.py`); needs alert parsing and an `investigate` agent profile |
| E2.2 | Observability toolsets: Prometheus, Loki, Grafana, Datadog, Terraform plan, Helm, cloud CLIs (all read tier by default) | Ship as plugins or via MCP; HolmesGPT sets the bar at 30+ |
| E2.3 | Runbook ingestion: markdown runbooks and past postmortems as skills | Skills mechanism exists; needs an importer and provenance tags |
| E2.4 | Slack ChatOps: approve/deny buttons, incident thread as the session | Reuses the approval-channel interface used by Telegram |
| E2.5 | Remediation as a reviewed PR with post-merge health verification | GitOps worktree and `argocd_health` verifier already exist; wire into one flow |
| E2.6 | Postmortem export from the event log (markdown) | Falls out of receipts; mostly a template |

### E3: platform and ecosystem

| # | Item | Notes |
|---|---|---|
| E3.1 | MCP: streamable HTTP client with OAuth, per-server allowlist and pinning, `harness mcp serve` (expose the harness as an MCP server) | Also closes the supply-chain gap for MCP servers |
| E3.2 | Installable plugin packages (Python entry points) and a bundle format for skills, hooks, MCP config | Claude Code plugin model; Agent Skills format compatibility check |
| E3.3 | Managed policy file that user config cannot loosen (org-wide deny rules) | Enterprise requirement |
| E3.4 | **Done.** Web dashboard (`core/ui/`, `/ui`) (sessions, approvals, live SSE, receipts) | The API already exposes everything it needs |
| E3.5 | A2A agent card so other agents can call this one | Low priority; A2A v1.0 is stable |

### E4: hardening and hygiene

| # | Item | Notes |
|---|---|---|
| E4.1 | Rotate and purge the old Vault token from git history | **Owner action**; still open since Phase A |
| E4.2 | Network egress allow-list for the shell sandbox | Today the sandbox limits files, not the network, unless configured |
| E4.3 | Subagent worktree isolation, file watcher for plugin reload | Known gaps from Phase C/D |
| E4.4 | Exercise Docker/Compose and the 4 live tests in CI against real services | Never run in the build environment |
| E4.5 | Sign release artefacts (cosign), `pip-audit` in CI, CodeQL | SBOM/provenance and Dependabot ship with this change |

### Deliberately not doing

Voice, a built-in browser and a 20-channel chat gateway: these serve personal assistants (OpenClaw, Hermes), not
a policy-gated DevOps runtime, and each adds attack surface and weight. Browser automation can come through an
MCP server if needed. "Code mode" remains excluded for the same reason (see the audit).

## 4. Suggested order

E1.1 → E1.3 → E1.4 → E1.2 → E1.5, then E2.1 + E2.2 + E2.4 as one "on-call" release, then E3.1, then the rest.
E4.1 is independent and should happen now.

## Sources

- Claude Code features and extension model: https://alexop.dev/posts/understanding-claude-code-full-stack/ , https://www.marktechpost.com/2026/06/14/claude-code-guide-2026-25-features-with-examples-demo/
- Claude Code status line, output styles, permission modes: https://www.claudedirectory.org/blog/claude-code-statusline-guide , https://likeone.ai/blog/claude-code-output-styles-guide-2026/
- OpenClaw (Gateway, channels, Lobster workflows, lobster identity): https://github.com/openclaw/openclaw , https://docs.openclaw.ai/concepts/features
- Hermes Agent (skins, skills, memory, plugins, cron): https://hermes-agent.nousresearch.com/docs/user-guide/features/skins , https://github.com/NousResearch/hermes-agent
- AI SRE agents (HolmesGPT, K8sGPT, Aurora, kagent): https://github.com/HolmesGPT/holmesgpt , https://dev.to/siddharth_singh_409bd5267/open-source-ai-sre-aurora-vs-holmesgpt-vs-k8sgpt-2026-5g26
- OWASP Top 10 for Agentic Applications: https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/
- OpenTelemetry GenAI conventions: https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions
- Protocols (MCP, A2A, Agent Skills, AGENTS.md): https://a2a-protocol.org/latest/ , https://tyk.io/learning-center/agent-protocols-a-complete-guide-to-mcp-a2a-and-acp/
