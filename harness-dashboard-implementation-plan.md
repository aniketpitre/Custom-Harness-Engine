# Harness Engine Dashboard Implementation Plan

This document outlines the detailed phases for implementing the Harness Engine Dashboard, mirroring the Hermes agent dashboard architecture while utilizing Harness-native primitives.

## Phases

| Phase | Description | Status |
| :--- | :--- | :--- |
| **D0** | Dashboard Backend Extensions (FastAPI) | TODO |
| **D1** | Frontend Scaffold (React/Vite) | TODO |
| **D2** | Overview (Landing Page) | TODO |
| **D3** | Live Run Page (SSE + Interruption) | TODO |
| **D4** | Runs Page (FTS Search + Filter) | TODO |
| **D5** | Settings, Secrets & Channels Pages | TODO |
| **D6** | Skills, Tools & Learning Queue Pages | TODO |
| **D7** | Analytics Page | TODO |
| **D8** | Approval Gate, Triggers & Webhooks Pages | TODO |
| **D9** | Orchestration & Verification Pages | TODO |
| **D10** | System Page | TODO |
| **D11** | Hardening & Deployment | TODO |

---

## Detailed Breakdown

### Phase D0: Dashboard Backend Extensions
- Create new API endpoints (`/api/*`) for dashboard data.
- Implement auth middleware (HMAC session cookie, scrypt password hash).
- Create D1 schema migrations for new tables (`approval_queue`, `analytics_daily`).

### Phase D1: Frontend Scaffold
- Initialize React/Vite/Tailwind frontend.
- Implement app shell (nav sidebar, domain switcher, theme toggle).
- Setup API proxy to backend.

### Phase D2: Overview Page
- Dashboard home: throughput stats, gateway health, active runs, recent receipts.

### Phase D3: Live Run Page
- Live SSE stream timeline, interruption form, token budget monitoring.

### Phase D4: Runs Page
- Paginated table of RunReceipts with FTS search, status filtering, and JSON export.

### Phase D5: Settings, Secrets & Channels Pages
- Config forms, secret status inspector (read-only), channel config forms.

### Phase D6: Skills, Tools & Learning Queue Pages
- Skills toggle, Registry risk-tier editor, Learning Queue management.

### Phase D7: Analytics Page
- Usage metrics, pie charts for policy decisions, verification pass-rates over time.

### Phase D8: Approval Gate, Triggers & Webhooks Pages
- Approval management, CRON trigger management, webhook subscriptions.

### Phase D9: Orchestration & Verification Pages
- Multi-agent workflow visualization, drill-down into verification logs.

### Phase D10: System Page
- Health status, Curator trigger, Memory Dream trigger/viewer, Log viewer.

### Phase D11: Hardening & Deployment
- Finalize production Nginx + API proxy setup, verify no secrets in frontend.
EOF
git add harness-dashboard-implementation-plan.md
git commit -m "docs: replace old dashboard implementation plan with detailed architecture-aligned plan" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
