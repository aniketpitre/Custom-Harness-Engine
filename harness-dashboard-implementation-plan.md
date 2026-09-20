# Harness Engine Dashboard Implementation Plan (Hermes-Exact)

This document outlines the phases for upgrading the Harness Engine Dashboard to match the Hermes architecture pattern.

## Phases

| Phase | Description | Status |
| :--- | :--- | :--- |
| **D0-D11** | Backend API & Initial UI | ✅ DONE |
| **D12** | Layout Refactor (Router, Layout Components) | TODO |
| **D13** | Terminal Integration (XTerm.js) | TODO |
| **D14** | Fluid UI Motion (motion) | TODO |
| **D15** | Command Palette (Interactions) | TODO |

---

## Detailed Breakdown (Hermes Parity)

### Phase D12: Layout Refactor
- Implement `react-router` for multi-page workspace.
- Refactor to `src/{pages,components,hooks,contexts,lib}` structure.
- Introduce `Layout` component with sidebar-based scope switcher.

### Phase D13: Terminal Integration
- Replace static log views with `xterm.js` and `xterm-addon-fit`.
- Create log hook to manage stream state.

### Phase D14: Fluid UI Motion
- Add `motion` for Hermes-style page transitions and interactivity.

### Phase D15: Command Palette
- Implement keyboard shortcut (`Cmd+K`) action hub.

