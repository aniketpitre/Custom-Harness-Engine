# Harness Engine User Guide

## 1. Configure

`harness init` writes `~/.harness/.env` (mode 600) and `~/.harness/config/agents.yaml`. Everything is configured
with environment variables (`HARNESS_*`), optionally `~/.harness/config/settings.yaml` (`model.primary`,
`model.fallback`, `otel.endpoint`). Precedence: real environment → `.env` → settings.yaml → packaged defaults.
Secrets come from the environment/`.env` first, then the OS keyring (`harness secret`), then Vault (optional). Run `harness doctor` after any change.

| Variable | Purpose | Default |
|---|---|---|
| `HARNESS_API_TOKEN` | Bearer token for the API. **Required** (no default). Extra scoped tokens: `HARNESS_API_TOKENS='{"tok": ["sessions:read"]}'` | - |
| `HARNESS_MODEL`, `HARNESS_FALLBACK_MODELS` | LiteLLM model and failover chain | `groq/openai/gpt-oss-120b` |
| `HARNESS_WORKSPACE` | The only directory file/shell tools may touch | current directory |
| `HARNESS_APPROVERS` | Allowed approver ids, e.g. `telegram:123,api:*` | any member of the approval chat |
| `HARNESS_APPROVAL_TIMEOUT` | Seconds before an unanswered approval is denied | 300 |
| `HARNESS_GITOPS_REPOS` | Repositories the agent may open PRs against | the workspace |
| `HARNESS_STAGING_APPS` | ArgoCD app globs treated as staging (R2); all others are R3 | none |
| `HARNESS_SANDBOX` | `none` / `bwrap` / `docker` for the bash tool (fails closed if unavailable) | `none` |
| `HARNESS_TOKEN_BUDGET`, `HARNESS_MAX_TURNS`, `HARNESS_MAX_SECONDS` | Run limits | 200000 / 30 / 3600 |
| `HARNESS_MAX_COST_USD` | USD ceiling per run, subagents included (also `max_cost_usd` per agent, `harness run --max-cost`); `0` = no limit | `0` |
| `HARNESS_PRICES` | Price overrides, USD per million tokens: `{"my/model": {"input": 0.5, "output": 1.5}}`. Local models are free; models without a price are reported as *unpriced* | LiteLLM's bundled map |
| `HARNESS_CONTEXT_WINDOW`, `HARNESS_KEEP_RECENT_TOKENS` | Compaction thresholds | 128000 / 20000 |
| `HARNESS_RECEIPT_KEY` | HMAC key for the event-log hash chain | unset (plain SHA-256) |
| `HARNESS_WEBHOOK_ENDPOINTS`, `HARNESS_WEBHOOK_SECRET` | Signed completion webhooks | none |

## 2. Agents (`~/.harness/config/agents.yaml`)

```yaml
- id: sre
  domain: devops
  system_prompt: "You are an SRE."
  allowed_tools: [Read, DevOpsRead, DevOpsWrite, Memory]
  max_turns: 20
  token_budget: 100000
  deny_tools: [web_search]
  rules: ["deny:bash(git push --force*)", "ask:web_fetch"]   # deny > ask > allow, first match wins
  verification: {type: argocd_health, app_name: web}          # default verification for its runs
  verify_with_agent: true                                     # independent read-only verifier
```

Project instructions: put an `AGENTS.md` in the workspace (scanned for injection; loaded into the stable prompt prefix).

## 3. Use it

```bash
curl -s -H "Authorization: Bearer $HARNESS_API_TOKEN" -X POST localhost:8000/sessions \
  -d '{"agent_id":"sre","goal":"Why is checkout returning 502?","run":true}'
curl -N -H "Authorization: Bearer $HARNESS_API_TOKEN" localhost:8000/sessions/<id>/stream
```

Approvals arrive on Telegram (buttons: approve once / approve for session / deny) or via `GET /approvals` and
`POST /approvals/{id}`. Unanswered approvals are denied after the timeout, and the model is told why.

## 4. Extend it

- **MCP servers:** copy `core/defaults/mcp.yaml.example` (in a checkout) to `~/.harness/config/mcp.yaml`. Tools become `mcp__<server>__<tool>`.
- **Hooks:** `~/.harness/config/hooks.yaml` (see `core/defaults/hooks.yaml.example`). A `pre_tool` hook may deny/ask or rewrite arguments (exit code 2 blocks);
  a `stop` hook can force the agent to continue (this is how you enforce a verification step).
- **Plugins:** subclass `core.plugins.base.Plugin`, register tools/hooks/services in `register(ctx)`, load with
  `engine.plugins.load(...)`. Reload and unload are transactional.
- **Skills:** `SKILL.md` files under `domains/*/skills/` or `data/skills/`. The agent sees a name/description
  index and loads bodies with `skill_view`; `skill_manage` writes are approval-gated and scanned.
- **Heartbeat:** `POST /heartbeat` runs an agent every N minutes against the standing instructions in `HEARTBEAT.md`.
