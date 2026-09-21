# Deep Architectural Gap Analysis — Cordis / DeepSeek-AI Paper

## Purpose

Read-only architecture audit prompt for Claude Code.

Compare the current Custom Harness Engine at `/root/Harness-Engine` against:

**A Programming Paradigm for Spatiotemporal Composability**  
Authors: Yifan Shi, Wei Zhang  
Affiliations: Peking University, DeepSeek-AI

The paper introduces **Cordis**, a meta-framework for dynamic composition, and discusses self-evolving agent harnesses as a future application.

> Do NOT implement anything. Do NOT modify the repository. Do NOT install dependencies. Only inspect and report.

---

## 1. Source Paper Identification

The paper is **not** itself a complete "DeepSeek Harness Engine" implementation.

It introduces Cordis and a dynamic composition model based on:

- temporal composability
- spatial composability
- revertible effects
- reactive coeffects
- unified context
- dynamic component lifecycle
- declarative component loading
- configuration reconciliation
- hot module replacement

The paper identifies self-evolving agent harnesses as a future application of these concepts.

The key question for our project is:

> **How ready is our Custom Harness Engine to safely add, remove, replace, reconfigure, and evolve its own components at runtime?**

---

## 2. Temporal Composability

Temporal composability concerns what happens over time.

When a component is removed, replaced, disabled, or reloaded, modifications it made to the shared environment should be completely and safely reversed.

The paper specifically considers:

- resource allocations
- event registrations
- state mutations
- other environmental modifications

Conceptually:

```text
Component starts
      |
      v
Creates resources
Registers events
Mutates context
Starts tasks
      |
      v
Component removed
      |
      v
Reverse owned effects
      |
      v
Runtime restored
```

Audit whether our engine tracks effect/resource ownership and can reverse component changes.

---

## 3. Spatial Composability

Spatial composability concerns dependencies between components.

Components must be able to:

- declare dependencies
- discover dependencies
- resolve dependencies
- verify dependencies
- react when dependencies change

Dynamic behavior should support:

```text
provider appears
      |
      v
dependent activates

provider disappears
      |
      v
dependent deactivates

provider changes
      |
      v
dependent re-resolves
      |
      v
dependent reactivates
```

Do not assume normal dependency injection provides these guarantees. Verify the actual repository behavior.

---

## 4. Why Whole-Process Restart Is Not Enough

Process/container restart is a coarse-grained recovery mechanism.

A restart can destroy:

- caches
- connections
- partial computations
- process-local state
- in-flight tasks
- runtime context

The desired model is:

```text
component failure/change
        |
        v
component isolation
        |
        v
component cleanup
        |
        v
component replacement/reload
        |
        v
dependent reconciliation
        |
        v
harness continues running
```

Investigate whether individual runtime components can be replaced without restarting the entire harness.

---

## 5. Self-Evolving Agent Harness Requirement

The paper discusses future harnesses that may:

- generate components
- deploy components
- replace components
- continuously modify themselves
- continue serving requests while modifying themselves
- potentially operate with limited human oversight

Without temporal composability:

- modifications may require restart
- runtime state is lost
- availability suffers
- in-flight work is disrupted
- faulty modifications can damage recovery

Without spatial composability:

- modules must manually detect dependency changes
- dependency handling becomes ad hoc
- dependents can silently break
- stale references can remain
- circular dependencies can appear during reload

Treat these as architectural benchmarks for our engine.

---

## 6. Revertible Effects

Cordis formalizes **revertible effects**.

Every context transformation performed by a component should have an explicit inverse.

Conceptually:

```text
effect():
    modify shared context
    return inverse/disposer
```

Example:

```text
component starts
      |
      +--> register tool
      +--> open connection
      +--> subscribe event
      +--> modify context
      +--> start background task
      |
      v
store inverse/disposer operations
```

On removal:

```text
component removed
      |
      +--> unsubscribe event
      +--> close connection
      +--> unregister tool
      +--> cancel background task
      +--> restore context
```

Cordis uses `ctx.effect`.

Effects produce inverse/disposer operations and inverses are applied in reverse/LIFO order.

Important limitation:

> The runtime does not automatically prove that an inverse is correct. The component author is responsible for providing a correct inverse.

Therefore interpret this as:

**component effect ownership + explicit reversibility**

not automatic rollback of arbitrary Python side effects.

---

## 7. Unified Context

Cordis uses a unified context model for:

- effects
- dependencies/coeffects
- component state

Conceptually:

```text
                 CONTEXT
                    |
       +------------+------------+
       |            |            |
    Effects      Dependencies   State
       |            |            |
       +------------+------------+
                    |
              Component Runtime
```

Audit:

- Is there a central runtime context?
- Who owns it?
- Which components can mutate it?
- Are mutations tracked?
- Can mutations be reversed?
- Are dependencies resolved through it?
- Is state scoped to component/session/task?
- Can component state be isolated?
- Can the runtime determine what a component changed?

---

## 8. Reactive Coeffects

A component declares what it requires.

Example:

```text
Component A requires:
    database
    model_provider
    tool_registry
```

Runtime behavior should resemble:

```text
requirements satisfied
    -> INACTIVE -> ACTIVE

requirements become unsatisfied
    -> ACTIVE -> INACTIVE

dependency changes
    -> deactivate
    -> re-resolve
    -> reactivate
```

The important property is **reactive dependency management**.

---

## 9. Component Model

Cordis combines effects and coeffects into a component abstraction.

Investigate whether major runtime units can have:

- stable identity
- configuration
- declared dependencies
- provided capabilities
- lifecycle
- activation state
- effect ownership
- cleanup
- health
- replacement
- version
- failure state
- dependency state

Potential candidates include:

- agent runtime
- planner
- executor
- tool registry
- MCP integration
- memory
- context manager
- model provider
- evaluator
- learning subsystem
- policy engine
- sandbox/execution environment
- subagent runtime
- Git integration
- GitOps integration
- observability
- task/session manager

Do not assume all of these should become first-class components.

---

## 10. Component Lifecycle

Investigate whether the current engine has a formal lifecycle equivalent to:

```text
DISCOVERED
    |
    v
REGISTERED
    |
    v
RESOLVING_DEPENDENCIES
    |
    v
READY
    |
    v
ACTIVE
    |
    +----> DEGRADED
    |
    +----> FAILED
    |
    v
DEACTIVATING
    |
    v
INACTIVE
    |
    v
REMOVED
```

Also investigate:

- REPLACING
- RELOADING
- ROLLING_BACK

Determine whether lifecycle state is explicit, implicit, distributed, manually controlled, or framework controlled.

Do not recommend a state machine merely because the paper contains one.

---

## 11. Hot Reload / Self-Modification

Cordis includes:

- declarative component loading
- configuration reconciliation
- hot module replacement
- effect tracking
- dependency resolution

Analyze whether our engine can:

1. Detect component change
2. Validate changed component
3. Determine affected dependencies
4. Preserve unaffected runtime state
5. Deactivate affected components
6. Dispose their effects
7. Reload/recreate the changed component
8. Re-resolve dependencies
9. Reactivate dependents
10. Recover if reload fails

Do not implement this yet.

---

## 12. Transactional Reload

The paper describes a transactional reload approach:

```text
detect stale component
        |
        v
invalidate relevant cache
        |
        v
backup old module/state
        |
        v
dispose old runtime
        |
        v
load new implementation
        |
        v
initialize
        |
        v
resolve dependencies
        |
        v
activate
        |
        v
SUCCESS
        |
        v
commit
```

On failure:

```text
FAILURE
   |
   v
restore previous state/module
   |
   v
restore caches
   |
   v
rebuild old component
   |
   v
restore runtime
```

Key property:

> A failed replacement should not leave the runtime in a half-reloaded state.

---

## 13. Dependency Topology

Build the actual dependency graph of the current engine.

Do not assume this example is correct:

```text
Agent Runtime
    |
    +-- Context
    +-- Planner
    +-- Executor
    +-- Memory
    +-- Model Provider
    +-- Tool Registry

Tool Registry
    |
    +-- MCP
    +-- Built-in Tools
    +-- External Tools

Executor
    |
    +-- Tool Registry
    +-- Policy
    +-- Runtime Context
```

Build the real graph from source.

Identify:

- who imports whom
- who constructs whom
- who owns whom
- who initializes whom
- who calls whom
- runtime service dependencies
- static dependencies
- runtime-resolved dependencies
- dependencies that can change
- dependencies that cannot change

---

## 14. Effect Ownership Analysis

Identify runtime side effects such as:

- filesystem writes
- process execution
- subprocesses
- network connections
- HTTP sessions
- MCP connections
- event subscriptions
- timers
- background tasks
- threads
- asyncio tasks
- queues
- database connections
- model clients
- cache mutations
- registry mutations
- environment modifications
- temporary files
- child processes
- sandbox resources
- Git operations

For every effect determine:

```text
WHO CREATED IT?
WHO OWNS IT?
WHO CAN CLEAN IT UP?
IS CLEANUP GUARANTEED?
IS CLEANUP TRACKED?
CAN IT BE REVERSED IF THE COMPONENT IS REMOVED?
```

---

## 15. Current Failure Model

Analyze what happens if:

A. A tool crashes  
B. An MCP server disappears  
C. A model provider becomes unavailable  
D. A memory backend fails  
E. A component throws during initialization  
F. A component throws during execution  
G. A component changes while the engine is running  
H. A dependency disappears  
I. A dependency is replaced  
J. A generated component is faulty  
K. A task is in-flight when a component is replaced

For each determine:

- What happens?
- Which layer detects it?
- What state remains?
- What gets cleaned up?
- What gets restarted?
- What survives?
- What requires manual intervention?
- Can other work continue?

---

## 16. Security / Sandboxing

Investigate:

- Can generated components execute arbitrary code?
- Where do they execute?
- What privileges do they have?
- Can they access filesystem?
- Can they access network?
- Can they access secrets?
- Can they modify the harness itself?
- Can they modify other components?
- Can they modify runtime context?
- Can they spawn processes?
- Can they modify Git?
- Can they alter policy?
- Is capability access explicit?
- Is capability access auditable?

Do not design the complete security architecture yet. Only identify guarantees and gaps.

---

## 17. Agent-Specific Interpretation

Use this mapping:

| Cordis | Harness Interpretation |
|---|---|
| Component | Harness runtime component |
| Effect | Runtime side effect caused by a component |
| Revertible Effect | Side effect with deterministic cleanup/reversal |
| Coeffect | Dependency/capability required by a component |
| Context | Shared runtime context/service registry/state |
| Reactive Coeffect | Runtime dependency reconciliation |
| Activation | Component becomes operational when requirements exist |
| Deactivation | Component stops when dependencies disappear or it is replaced |
| Hot Reload | Replace a component without restarting the entire agent runtime |
| Transactional Reload | Replacement either succeeds completely or previous component remains operational |
| Spatial Composability | Dynamic dependency management |
| Temporal Composability | Safe lifecycle/effect cleanup |
| Self-Evolution | Harness modifies/replaces its own components while remaining operational |

---

## 18. Critical Architectural Question

Determine whether the Custom Harness Engine is primarily:

### A
Agent orchestration system

### B
Agent orchestration system + runtime component framework

### C
Self-evolving component runtime + agent orchestration layer

Do not choose based on intuition. Use source evidence.

---

## 19. Target Architecture Reference

Use this only as a comparison model:

```text
USER / CLI / API
        |
        v
+-----------------------------+
|       HARNESS API           |
+-----------------------------+
        |
        v
+-----------------------------+
|       AGENT RUNTIME         |
|                             |
| Planner                     |
| Executor                    |
| Context                     |
| Memory                      |
| Learning                    |
| Evaluation                  |
| Policy                      |
| Session                     |
+-----------------------------+
        |
        v
+-----------------------------+
|    COMPONENT RUNTIME        |
|                             |
| Component Registry          |
| Dependency Resolver         |
| Lifecycle Manager           |
| Effect Tracker              |
| Resource Manager            |
| Capability Manager          |
| Provider Registry           |
| Reload Manager              |
| Recovery / Rollback         |
+-----------------------------+
        |
        v
+-----------------------------+
|        COMPONENTS           |
|                             |
| Tools                       |
| MCP                         |
| Models                      |
| Memory                      |
| Executors                   |
| Evaluators                  |
| Policies                    |
| External Services           |
+-----------------------------+
```

Do not implement this blindly.

Determine which pieces already exist.

---

## 20. Required Repository Investigation

Scan:

```text
/root/Harness-Engine
```

Start with:

- README
- pyproject.toml
- source tree
- architecture documentation
- config
- domains
- core/runtime packages
- agent implementation
- tools
- MCP
- memory
- learning
- evaluation
- policy
- execution
- persistence
- tests
- scripts

Trace actual runtime entrypoints.

Find:

1. Application entrypoint
2. Agent entrypoint
3. Task execution path
4. Tool invocation path
5. MCP invocation path
6. Memory path
7. Learning path
8. Evaluation path
9. Policy path
10. Persistence path
11. Configuration loading
12. Plugin/component loading
13. Background workers/tasks
14. Error handling
15. Cleanup/shutdown

Follow actual imports and execution paths rather than relying on directory names.

---

## 21. Architecture Map

Produce an actual architecture map from the repository.

Use:

```text
Component
    |
    v
Dependency
    |
    v
Dependency
    |
    v
Side Effect
```

Also identify ownership.

Only include relationships verified in code.

---

## 22. Gap Classification

For every Cordis-inspired capability classify it as:

- `[IMPLEMENTED]`
- `[PARTIALLY IMPLEMENTED]`
- `[CONCEPTUALLY PRESENT]`
- `[MISSING]`
- `[NOT APPLICABLE]`
- `[POTENTIAL OVERENGINEERING]`

For every finding provide:

- Current implementation
- Evidence from source
- What the paper requires
- Difference
- Risk/impact
- Whether it matters for our intended harness
- Whether it should be addressed now or later

Do not give scores.

Do not rank items.

---

## 23. Most Important Gaps to Investigate

Explicitly investigate:

1. First-class component model
2. Component identity
3. Component lifecycle
4. Effect ownership
5. Revertible effects
6. Central runtime context
7. Runtime dependency declarations
8. Reactive dependency resolution
9. Dependency topology tracking
10. Component activation/deactivation
11. Resource ownership
12. Runtime cleanup guarantees
13. Hot reload
14. Transactional reload
15. Rollback
16. State preservation during replacement
17. Failure isolation
18. Background task ownership
19. MCP lifecycle management
20. Tool lifecycle management
21. Model-provider lifecycle management
22. Memory-provider lifecycle management
23. Sandbox boundaries
24. Capability boundaries
25. Self-modification safety
26. Generated component validation
27. Versioned components
28. Configuration reconciliation
29. Runtime observability
30. Recovery from bad component deployment

---

## 24. Do Not Confuse These Concepts

- A static Python module is not automatically a dynamic component.
- A class is not automatically a component.
- A plugin is not automatically a component.
- A tool is not automatically a component.
- A service registry is not automatically reactive.
- A cleanup function is not automatically temporal composability.
- Dependency injection is not automatically spatial composability.
- Restart is not equivalent to component recovery.
- A health check is not lifecycle management.
- try/except is not rollback.
- A database transaction is not runtime component rollback.
- Configuration reload is not necessarily hot module replacement.

---

## 25. Ponytail / Overengineering Constraint

The repository has already undergone Ponytail architectural cleanup.

Current philosophy:

- reuse existing code
- avoid unnecessary abstraction
- avoid wrapper layers
- avoid single-implementation interfaces
- avoid framework infrastructure without actual need
- preserve security and error handling
- prefer simple implementations

Therefore:

> Do NOT conclude that we need a complete Cordis clone.

Instead ask:

> What minimum architectural primitives would give our harness the important properties of temporal and spatial composability?

The required architecture may be substantially smaller than Cordis.

---

## 26. Important Paper Limitation

The paper does **not** present a complete production-ready self-evolving AI harness.

It presents Cordis as a meta-framework for dynamic composition and identifies self-evolving agent harnesses as a future validation/application direction.

Do not claim:

> "DeepSeek already built this exact self-evolving harness architecture."

Use:

> "The paper proposes a dynamic composition model that is explicitly motivated in part by future self-evolving agent harnesses."

---

# 27. Required Report Structure

Produce:

## 1. Executive Summary

Explain:

- What the paper actually proposes
- What Cordis is
- Why it matters to our harness
- What the paper does not provide

## 2. Current Custom Harness Engine Architecture

Reconstruct the actual architecture.

## 3. Current Runtime Flow

Show the actual flow, for example:

```text
request
→ planning
→ execution
→ tools
→ memory
→ evaluation
→ learning
→ persistence
```

## 4. Component Inventory

For each actual runtime component:

- purpose
- owner
- dependencies
- side effects
- lifecycle
- failure behavior

## 5. Dependency Graph

Build the actual dependency graph.

## 6. Effect / Resource Ownership

Identify runtime side effects and ownership.

## 7. Temporal Composability Analysis

Compare:

- effect tracking
- reversible effects
- cleanup
- resource ownership
- component removal
- replacement
- state preservation
- rollback

## 8. Spatial Composability Analysis

Compare:

- dependency declaration
- dependency discovery
- dependency resolution
- dependency changes
- provider replacement
- provider disappearance
- reactive activation/deactivation

## 9. Component Lifecycle Analysis

Determine whether the engine has a true component lifecycle.

## 10. Hot Reload / Self-Modification Analysis

Determine what happens if a component changes while running.

## 11. Failure and Recovery Analysis

Analyze component failure and recovery.

## 12. Security / Sandbox Analysis

Analyze self-modification and generated components.

## 13. Cordis Concept → Custom Harness Mapping

Use:

| Cordis Concept | Meaning | Current Harness Equivalent | Status | Evidence | Gap |
|---|---|---|---|---|---|

## 14. Missing Architectural Capabilities

Give the meaningful gaps.

Do not rank or score them.

## 15. Existing Architecture We Can Reuse

Identify reusable architecture.

## 16. Minimal Architecture Needed

Describe the smallest extension that provides meaningful temporal + spatial composability.

Do not overengineer.

## 17. Self-Evolving Harness Readiness

Answer:

> What would have to change before the harness could safely modify/replace its own components while continuing to serve requests?

## 18. Dashboard Implications

We are doing this analysis before building the dashboard.

Explain what runtime concepts the dashboard should eventually expose.

Do not build the dashboard.

## 19. Architecture Roadmap

Use only stages justified by the actual repository.

Possible model:

```text
Current
    ↓
Minimal component lifecycle
    ↓
Effect/resource ownership
    ↓
Dependency reconciliation
    ↓
Safe reload/recovery
    ↓
Self-evolution readiness
```

## 20. Final Architectural Conclusion

Answer:

1. What is our harness today?
2. What does the paper introduce?
3. What fundamental capability is missing?
4. Which existing systems can be reused?
5. What is the smallest architectural change that moves us toward dynamic composability?
6. What should NOT be built?
7. What should we understand before starting the dashboard?

---

## 28. Evidence Requirement

For every significant architectural claim provide repository evidence.

Use:

- file path
- class/function
- relevant code behavior
- call path

Example:

```text
src/runtime/executor.py:123

Executor.execute()

Evidence:
Executor directly creates subprocesses and does not register them with a central resource manager.
```

Do not claim that the engine has a component system unless repository evidence proves it.

---

## 29. Read-Only Requirement

Do NOT:

- edit files
- delete files
- install packages
- create abstractions
- refactor
- commit
- push
- change configuration

Only inspect and report.

---

## 30. Final Output Requirement

At the end provide exactly:

## Architectural Bottom Line

```text
Current Harness:
...

Paper/Cordis:
...

Fundamental Difference:
...

Most Important Missing Runtime Capability:
...

Existing Architecture We Can Reuse:
...

Minimum Architectural Extension:
...

What We Should NOT Build:
...

Dashboard Should Wait For:
...
```

Then:

## Confidence / Evidence Notes

List conclusions where repository evidence is incomplete.

Do not hide uncertainty.

---

# Source Material from the Paper

## Abstract

The paper describes dynamic composition as increasingly important for modern software, including self-evolving agent harnesses.

It identifies:

- temporal composability
- spatial composability

It formalizes:

- revertible effects
- reactive coeffects
- unified context
- dynamic component calculus

It implements these concepts in Cordis.

Cordis provides:

- effect tracking
- coeffect resolution
- declarative component loading
- configuration reconciliation
- hot module replacement

---

## Temporal Composability

Temporal composability means:

> When a component is removed, the modifications the component made to the shared environment must be completely and safely reversed.

This requires tracking:

- resource allocations
- event registrations
- state mutations

---

## Spatial Composability

Spatial composability means:

> Components must be able to declare, discover, and resolve their dependencies on one another in a structured and verifiable manner.

This requires:

- dependency topology management
- lifecycle coordination
- response to dependency changes

---

## Self-Evolving Agent Harnesses

Modern agent harnesses may compose:

- tool suites
- execution environments
- permissions
- sandboxing
- session state
- persistence
- context
- memory
- subagents
- multi-agent workflows
- user interfaces
- automation interfaces

The paper proposes that a future harness may generate and deploy modifications to its own components continuously.

---

## Coarse-Grained Restart Model

Operating systems and container orchestrators provide coarse-grained recovery.

Process restart provides temporal recovery at process granularity.

Container orchestration provides composition/recovery at service granularity.

The paper argues for finer-grained component-level composition because coarse restart causes:

- state loss
- restart overhead
- redundant replicas
- network overhead
- inability to express fine-grained dependencies inside a process

---

## Revertible Effects

Cordis formalizes revertible effects.

Every context transformation carries an explicit inverse.

The implementation uses:

```text
ctx.effect
```

The effect callback produces an inverse/disposer.

Inverses compose in reverse/LIFO order.

Correctness remains the component author's responsibility.

---

## Reactive Coeffects

A component declares requirements/coeffects.

Changes to context are evaluated against those requirements.

A change can result in:

- activation
- deactivation
- neutral change

This drives component lifecycle.

---

## Unified Context

The effect context and coeffect context are unified.

Effects and dependencies are mediated through the same context.

---

## Cordis Component Model

Cordis combines effects and coeffects into components.

The component abstraction provides the basis for dynamic composition.

---

## Cordis Implementation

Cordis includes:

- effect tracking
- coeffect resolution
- declarative component loader
- configuration reconciliation
- hot module replacement

---

## Transactional Reload

The reload approach conceptually:

1. Detect stale entries
2. Invalidate caches
3. Backup modules
4. Dispose old fibers/components
5. Import/reload new implementation
6. On failure:
   - restore caches
   - restore old implementation
   - rebuild previous components

Key property:

> A failed replacement should not leave the runtime in a half-reloaded state.

---

## Service / Provider Model

A provider can:

- appear
- disappear
- change

Dependents react to those changes.

A dependent should remain inactive when a required dependency is unavailable and reactivate when it becomes available.

---

## Sandboxing

Untrusted components may require:

- process boundary
- runtime boundary
- container boundary

Capabilities may be attenuated through controlled bridges.

---

# Final Interpretation

The key distinction to investigate is:

## Current Style

```text
Static modules
    +
Agent orchestration
    +
Tool execution
    +
Memory
    +
Learning
    +
Evaluation
```

versus:

## Dynamic Runtime Model

```text
Dynamic runtime components
    +
Explicit lifecycle
    +
Owned effects
    +
Reversible effects
    +
Declared dependencies
    +
Reactive dependency resolution
    +
Safe replacement
    +
Rollback
    +
State preservation
    +
Failure isolation
```

The goal is **not** to copy Cordis.

The goal is to determine:

> **Which of these properties our Custom Harness Engine already has, which it only approximates, and which are actually missing.**

Begin by scanning:

```text
/root/Harness-Engine
```
