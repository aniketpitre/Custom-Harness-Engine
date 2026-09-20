# Harness Engine Dashboard Implementation Plan

This document outlines the phases for implementing the Harness Engine Dashboard frontend.

## Phases

| Phase | Description | Status |
| :--- | :--- | :--- |
| **18** | Frontend Scaffolding & Setup (React/Vite) | TODO |
| **19** | Session Registry UI (List/Filter active runs) | TODO |
| **20** | Live Event Streaming (SSE consumer) | TODO |
| **21** | Security & Budgeting Visualization Panels | TODO |
| **22** | Agent Steering & Interruption Interface | TODO |
| **23** | Memory Consolidation & Receipt Inspector View | TODO |
| **24** | Dashboard Hardening & Deployment | TODO |

---

## Detailed Breakdown

### Phase 18: Frontend Scaffolding
- Initialize `frontend/` directory.
- Setup React with Vite and Tailwind CSS.
- Configure proxy/API handlers for `localhost:8000`.

### Phase 19: Session Registry UI
- Hook into `GET /sessions` and `GET /agents`.
- Render a data table for session state ("pending", "running", "success", "failure").

### Phase 20: Live Event Streaming
- Connect to `GET /sessions/{session_id}/stream`.
- Implement visual state processor for SSE dict events (messages, tool calls, tool results).

### Phase 21: Security & Budgeting Visualization
- Add icons for R0-R4 Risk Tiers in the event feed.
- Add real-time Token Usage gauge (derived from event receipts).

### Phase 22: Steering Interface
- Implement "Interrupt Agent" button.
- Build form to feed messages to `POST /sessions/{session_id}/interrupt`.

### Phase 23: Advanced Panels
- Memory Dream visualizer (`GET /memory/dream`).
- Final receipt "Deep Inspection" component.

### Phase 24: Hardening
- Dashboard-specific API security (Session token headers if required).
- Finalize production Dockerfile for the dashboard.
