# OWASP Top 10 for Agentic Applications: how Penko Perry responds

Covers the seven risks named in the public OWASP summary (see the source link in `docs/ROADMAP.md`). The
remaining three entries were not visible in the material available when this was written and are not
mapped here rather than guessed. "Gap" means a known hole, not a claim of full coverage.

| Risk | Controls in Penko Perry | Where | Gap |
|---|---|---|---|
| Agent goal hijack | Taint tracking: after untrusted content (web, files, tool output) enters context, mutating tiers are raised; fetched memory carries provenance | `core/policy.py`, `core/tools.py`, `core/plugins/memory_tool.py` | No classifier for injected instructions; relies on policy, not detection |
| Tool misuse | Argument-aware R0 to R4 tiers, deny > ask > allow rules, protected namespaces are R4, shell command classifier, args-hash-bound approvals, loop guard | `core/policy.py`, `core/approvals.py`, `core/loop.py` | Rules are only as good as the operator's config |
| Identity and privilege abuse | Scoped API tokens, constant-time compare, rate limit, no default token, approver allowlist, read-only Vault token in Docker, secrets in the OS keyring or a mode-600 file | `core/gateway/api.py`, `core/approvals.py`, `core/keystore.py` | No per-user identity or SSO; the approver is a string id |
| Agentic supply chain (incl. MCP) | Dynamic tools need R3 approval showing full source and sha256; AST allowlist; out-of-process runner; skills scanned; gitleaks in CI | `core/plugins/dynamic.py`, `core/skills.py` | MCP servers are trusted once configured: no pinning or per-server allowlist yet (roadmap E3.1) |
| Unexpected code execution | Shell sandbox (`bwrap`/docker), env filtering, workspace confinement, engine-source write protection, dynamic tools out of process | `core/confine.py`, `domains/generic/shell.py` | Sandbox is opt-in; network not restricted by default (roadmap E4.2) |
| Memory and context poisoning | Memory limits, content scanning, frozen snapshot per session, provenance tag, curated skills with approval | `core/plugins/memory_tool.py`, `core/skills.py` | Scanning is pattern-based |
| Insecure inter-agent communication | Subagents get an intersection of the parent's capabilities, share the parent's budget, run as child sessions, all events land in the same hash-chained log | `core/plugins/subagents_tool.py`, `core/subagents.py` | No cross-process agent protocol (A2A) yet, so nothing external can spoof a subagent |

Detection and forensics: every decision and result is in the append-only, hash-chained event log (optional HMAC), so
tampering is detectable after the fact.
