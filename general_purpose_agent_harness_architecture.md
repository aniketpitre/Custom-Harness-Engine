# General-Purpose Agent Harness — Architecture & Research Synthesis

**General-purpose agent runtime • DevOps/SRE as the first proving ground**

---

## 1. What We Are Building

We are **NOT** building a DevOps-only agent and we are **NOT** building another OpenClaw, Hermes, Pi, or coding-agent clone.

We are building a **general-purpose agent execution and learning runtime** that can safely turn goals into verified outcomes across domains.

```text
GENERAL-PURPOSE AGENT RUNTIME
          +
      DOMAIN PACKS

DevOps      Coding      Research      Data      Future domains
  Pack        Pack        Pack          Pack
```

DevOps is the first and strongest domain because it is an excellent proving ground: it contains real system state, heterogeneous tools, permissions, risk, observability, verification, rollback, history, and repeatable operational workflows.

---

## 2. Core Principle

> **The domain must be replaceable. The execution semantics must not be.**

```text
GOAL
 ↓
CONTEXT
 ↓
EVIDENCE
 ↓
DECIDE
 ↓
POLICY
 ↓
EXECUTE
 ↓
VERIFY
 ↓
RECEIPT
 ↓
LEARN
 ↓
MEMORY
```

---

## 3. Architecture

```text
                         USER / API / EVENT
                                  │
                                  ▼
                           ┌───────────────┐
                           │     GOAL      │
                           └───────┬───────┘
                                   │
                                   ▼
                      ┌────────────────────────┐
                      │     CONTEXT ENGINE     │
                      │                        │
                      │ Memory                 │
                      │ Evidence               │
                      │ State                  │
                      │ History                │
                      │ Relationships          │
                      └───────────┬────────────┘
                                  │
                                  ▼
                      ┌────────────────────────┐
                      │      AGENT ENGINE      │
                      │  Reason / Plan / Decide│
                      └───────────┬────────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                ▼                 ▼                 ▼
          ┌──────────┐      ┌──────────┐      ┌──────────┐
          │  SKILLS  │      │  POLICY  │      │  MODELS  │
          └──────────┘      └──────────┘      └──────────┘
                │                 │                 │
                └─────────────────┼─────────────────┘
                                  ▼
                         ┌────────────────┐
                         │ TOOL GATEWAY   │
                         │ MCP / Plugins  │
                         │ Native Tools   │
                         └───────┬────────┘
                                 │
                                 ▼
                       ┌──────────────────┐
                       │ EXECUTION PLANE  │
                       │                  │
                       │ Local            │
                       │ Docker           │
                       │ SSH              │
                       │ Browser          │
                       │ Kubernetes       │
                       │ Cloud            │
                       │ APIs             │
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │   VERIFICATION   │
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │   RUN RECEIPT    │
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │    LEARNING      │
                       │ Lesson / Skill   │
                       │ Validation / Ver.│
                       └────────┬─────────┘
                                │
                                ▼
                              MEMORY
```

---

## 4. Universal Core vs Domain Packs

### Universal Core

- Goal
- Context
- Evidence
- Reasoning and planning
- Skills
- Memory
- Policy and risk
- Tools
- Execution
- Verification
- Provenance and run receipts
- Learning
- Human approval
- Model routing
- Sessions and events

### Domain Packs

- DevOps / SRE / platform operations
- Coding
- Research
- Data
- Security
- Business operations
- Personal automation
- Future domains without changing the core runtime

```text
                 UNIVERSAL AGENT RUNTIME
                           │
       ┌───────────────────┼────────────────────┐
       │                   │                    │
       ▼                   ▼                    ▼
    DEVOPS              CODING              RESEARCH
     PACK                PACK                 PACK
       │                   │                    │
       ▼                   ▼                    ▼
 Kubernetes             Git                Web/Papers
 Linux                  Tests              Documents
 Cloud                  Build              Analysis
 Terraform              IDE                Sources
 Grafana                CI                 Citations
```

---

## 5. Why DevOps Is the First Priority

DevOps should be the **first domain, not the architecture**.

It forces the runtime to solve the difficult problems that general-purpose agents face:

```text
Example goal:
"Why is the payment API returning 502?"

Goal
 ↓
Discover system
 ↓
Collect evidence
 ↓
Inspect ingress / service / pods / logs
 ↓
Inspect recent changes
 ↓
Form hypothesis
 ↓
Test hypothesis
 ↓
Take action
 ↓
Observe
 ↓
Verify
 ↓
Record result
 ↓
Learn
```

The same execution semantics can later be applied to coding, research, data, automation, security, etc.

---

## 6. Research Findings From the Current Agent Ecosystem

### OpenClaw

OpenClaw demonstrates strong separation between the agent runtime, model/provider transport, sessions, tools, hooks, and harness concepts.

**Borrow:**
- Runtime/plugin boundaries
- Clean separation of model/provider and runtime
- Extensibility

**Improve:**
- Make goal completion, evidence, verification and learning first-class.

---

### Pi

Pi takes a deliberately minimal and highly extensible approach with extensions, skills, prompt templates and packages.

**Borrow:**
- Small core
- Composability
- Extensions

**Improve:**
- Add first-class execution semantics, policy, verification, receipts and learning.

---

### Hermes Agent

Hermes is especially relevant because it includes:

- Persistent memory
- FTS5 session search
- Skills
- Agent-created/improved skills
- MCP
- Multiple execution backends
- Subagents
- Multiple model providers

**Borrow:**
- Persistent memory
- Procedural skills
- Self-improvement

**Improve:**

```text
Experience
 ↓
Lesson
 ↓
Candidate Skill
 ↓
Validation
 ↓
Version
 ↓
Promotion
 ↓
Measurement
```

A successful experience should not automatically become trusted knowledge.

---

### Agent Skills

Use a portable, modular skill structure rather than inventing a proprietary skill format.

Skills represent **procedural knowledge** and should be loaded progressively.

---

### MCP

MCP should be the primary integration layer.

We should consume existing MCP tools and servers rather than rebuilding every integration.

```text
OUR HARNESS
    │
MCP / Plugin / Native Tool Gateway
    │
    ├── GitHub
    ├── Kubernetes
    ├── AWS / Azure
    ├── Linux / SSH
    ├── Browser
    ├── Databases
    ├── Monitoring
    └── Future tools
```

MCP is an integration protocol, not our policy or verification system.

Our harness adds:

```text
MCP
 ↓
Tool Registry
 ↓
Policy
 ↓
Risk
 ↓
Execution
 ↓
Verification
```

---

### A2A

A2A can be added later for interoperability between agents.

Do **not** make multi-agent behavior the first architectural dependency.

Start with:

```text
ONE AGENT
```

Then:

```text
ONE AGENT
+
SPECIALIST WORKER
```

Then eventually:

```text
AGENT
 ├── Research Worker
 ├── Execution Worker
 └── Verification Worker
```

---

### OpenHands

OpenHands reinforces the value of an execution runtime and sandboxing for agent actions.

We can borrow the execution-provider and sandbox concepts without making software engineering the identity of our harness.

---

### Platform Engineering Direction

Current platform-engineering thinking increasingly treats AI agents as **first-class platform consumers**, with identity, governance, context, resources and relationships becoming important platform concepts.

This supports making context, identity, policy and execution first-class components in our architecture.

---

## 7. The Gaps We Want to Address

### 1. Conversation-first execution

Agents often start from chat and tool calls.

**Our approach:**

Goal + state + evidence are first-class.

### 2. Tool calling ≠ operational execution

A tool returning success does not mean the goal succeeded.

**Our approach:**

Action → Observation → Verification → Outcome.

### 3. Weak verification

Command success is not system success.

**Our approach:**

Verification is mandatory for meaningful actions.

### 4. Immature operational learning

Memory exists, but learning should become validated procedural knowledge.

**Our approach:**

Experience → Lesson → Skill → Validation → Version.

### 5. Fragmented memory

Different agent systems often have separate memory mechanisms.

**Our approach:**

One pluggable memory abstraction.

### 6. Weak self-modification provenance

Learned behavior needs traceability.

**Our approach:**

Every skill has:
- Version
- Validation history
- Usage history
- Provenance
- Success/failure metrics

### 7. Emerging identity and permission models

An agent should not simply have unrestricted tools.

**Our approach:**

```text
Identity
 ↓
Policy
 ↓
Capability
 ↓
Tool
 ↓
Environment
 ↓
Action
```

### 8. General agent vs real-world control plane gap

Agents need context, state, governance and reliable execution semantics.

**Our approach:**

Make those concepts part of the runtime.

---

## 8. Context Engine

Context should be a **first-class subsystem**.

The model should reason over a structured evidence packet rather than a raw transcript plus arbitrary tool outputs.

```text
                    CONTEXT ENGINE
                         │
        ┌────────────────┼─────────────────┐
        ▼                ▼                 ▼
     Current           History          Knowledge
      State
        │                │                 │
        └────────────────┼─────────────────┘
                         ▼
                   EVIDENCE PACKET
                         │
                         ▼
                       MODEL
```

### Evidence Packet

Can contain:

- Goal and constraints
- Current state
- Relevant observations
- Logs / metrics / documents
- Previous attempts
- Relevant memory
- Available skills
- Entities and relationships
- Candidate hypotheses
- Confidence
- Applicable policies
- Risk constraints

---

## 9. Memory Architecture

```text
                         MEMORY
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
        EPISODIC         SEMANTIC       PROCEDURAL
        what happened    what is true   how to do it
            │               │               │
            └───────────────┼───────────────┘
                            ▼
                       RELATIONAL
                        CONTEXT
```

### Episodic Memory

What happened?

```text
Incident X occurred.
Agent tried A.
A failed.
B fixed it.
```

### Semantic Memory

What do we know?

```text
Production API uses Kubernetes.
Service X depends on Kafka.
Database Y is PostgreSQL.
```

### Procedural Memory

How do we do it?

```text
To investigate this failure:
1. inspect ingress
2. inspect service
3. inspect pods
4. inspect logs
5. inspect recent changes
```

### Relational Context

What is connected to what?

```text
Application
    │
    ├── depends_on → PostgreSQL
    ├── exposes → API
    ├── deployed_by → Helm
    └── monitored_by → Grafana
```

A graph database is **not required initially**.

---

## 10. Initial Memory Implementation

Start simple:

```text
Markdown
+
YAML Frontmatter
+
SQLite
+
FTS5 / BM25
+
Structured Metadata Filters
```

Example:

```yaml
---
id: incident-2026-0042
type: incident
domain: devops
environment: production
system: payments
tags:
  - kubernetes
  - ingress
  - nginx
  - 502
status: resolved
confidence: high
---
```

Later:

```text
BM25
   +
Embeddings
   +
Reranking
   +
Graph
   =
Hybrid Memory
```

The memory interface should remain pluggable so the architecture can later support local embedding models, GPU inference, unified memory, graph storage, etc.

---

## 11. Verification as a Core Primitive

### Traditional Agent

```text
Think
 ↓
Tool
 ↓
Result
 ↓
Done
```

### Our Runtime

```text
Goal
 ↓
Plan
 ↓
Action
 ↓
Observation
 ↓
Verification
 ↓
Outcome
```

Verification is domain-neutral.

### Coding

```text
Modify code
 ↓
Run tests
 ↓
Tests pass
```

### Research

```text
Make claim
 ↓
Check sources
 ↓
Claim supported
```

### DevOps

```text
Change infrastructure
 ↓
Health check
 ↓
Metrics
 ↓
Logs
 ↓
Service test
```

### Data

```text
Transform dataset
 ↓
Schema check
 ↓
Quality validation
```

---

## 12. Controlled Self-Learning

```text
RUN
 ↓
OUTCOME
 ↓
LESSON
 ↓
CANDIDATE SKILL
 ↓
VALIDATION TEST
 ├── FAIL → DISCARD
 └── PASS → VERSION
              ↓
        SKILL REGISTRY
              ↓
        FUTURE RUNS
              ↓
          MEASURE
```

The key principle:

> A successful-looking experience does not automatically become trusted knowledge.

Learning must be:

- Validated
- Versioned
- Measurable
- Reversible
- Traceable

---

## 13. Skills Are Universal

```text
skills/
├── devops/
│   ├── investigate-k8s-502/
│   ├── rotate-certificate/
│   └── diagnose-dns/
│
├── coding/
│   ├── fix-regression/
│   └── review-pr/
│
├── research/
│   ├── literature-review/
│   └── source-validation/
│
├── data/
│   └── validate-dataset/
│
└── general/
    ├── summarize/
    ├── compare/
    └── planning/
```

The core runtime should not care which domain a skill belongs to.

---

## 14. Policy and Risk

```text
IDENTITY
   ↓
POLICY
   ↓
CAPABILITY
   ↓
TOOL
   ↓
ENVIRONMENT
   ↓
ACTION
```

### Risk Levels

```text
R0 — Observe
     Read / search / inspect

R1 — Safe Action
     Reversible local changes

R2 — Operational
     Restart / deploy / modify

R3 — High Impact
     Production / sensitive operations

R4 — Destructive
     Irreversible / broad-impact actions
```

### Policy Result

```text
ALLOW
REQUIRE HUMAN APPROVAL
DENY
```

The exact actions assigned to each risk level can be defined by each domain pack.

---

## 15. Run Receipt

Every meaningful run should produce a provenance-rich receipt.

```yaml
run_id: RUN-2026-000042

goal:
  description: "Resolve payment API failure"

agent:
  id: default-agent

model:
  provider: ...
  model: ...

context:
  sources:
    - kubernetes
    - logs
    - memory
    - deployment-history

skills:
  - investigate-api-failure@1.3

actions:
  - tool: kubernetes.get_pods
  - tool: kubernetes.get_logs
  - tool: kubernetes.restart_deployment

policy:
  decisions:
    - action: restart_deployment
      risk: R2
      result: approved

verification:
  expected: "API returns HTTP 200"
  observed: "HTTP 200"
  result: PASS

learning:
  lesson_created: true
  skill_candidate: true

result:
  status: success
```

This answers:

> **Which model, skill version, evidence, actions and policy decisions produced this outcome?**

---

## 16. DevOps Domain Pack

DevOps is a **domain pack**, not the core.

```text
devops/
├── providers/
│   ├── kubernetes
│   ├── linux
│   ├── docker
│   ├── ssh
│   ├── azure
│   ├── aws
│   └── terraform
│
├── observability/
│   ├── prometheus
│   ├── grafana
│   ├── loki
│   └── elastic
│
├── source/
│   ├── github
│   └── gitlab
│
├── skills/
│   ├── investigate-pod-failure
│   ├── diagnose-ingress
│   ├── investigate-5xx
│   ├── certificate-expiry
│   ├── deployment-failure
│   └── disk-pressure
│
└── policies/
    ├── staging.yaml
    └── production.yaml
```

---

## 17. Same Runtime, Different Domains

### Research

```text
GOAL
 ↓
RESEARCH CONTEXT
 ↓
WEB / PAPERS / DOCUMENTS
 ↓
EVIDENCE
 ↓
CLAIMS
 ↓
SOURCE VERIFICATION
 ↓
REPORT
 ↓
LEARNING
```

### Coding

```text
GOAL
 ↓
REPO CONTEXT
 ↓
MEMORY + SKILL
 ↓
EDIT
 ↓
TEST
 ↓
VERIFY
 ↓
RUN RECEIPT
 ↓
LEARN
```

### Personal Automation

```text
GOAL
 ↓
USER CONTEXT
 ↓
MEMORY
 ↓
SKILL
 ↓
TOOLS
 ↓
ACTION
 ↓
VERIFY
 ↓
REMEMBER
```

---

## 18. What We Should NOT Build

Do not build:

- Another chatbot
- Another OpenClaw clone
- Another Hermes clone
- Another Pi clone
- Another coding agent
- Another MCP framework
- Another model router
- Another vector database
- Another messaging platform
- A giant multi-agent framework as the first milestone
- A DevOps-only automation platform

---

## 19. What We Should Build Ourselves

These are our core differentiators:

1. Goal and execution control loop
2. Context and evidence engine
3. Verification engine
4. Policy/risk engine
5. Run receipts and provenance
6. Skill lifecycle
7. Controlled learning engine
8. Pluggable memory abstraction
9. Domain-pack architecture

---

## 20. Ten Core Primitives

```text
1. GOAL
2. CONTEXT
3. EVIDENCE
4. AGENT
5. SKILL
6. POLICY
7. TOOL
8. EXECUTION
9. VERIFICATION
10. LEARNING
```

These primitives should remain domain-neutral.

---

## 21. Recommended Solo-Builder Roadmap

### Phase 0 — Architecture

Define:

- Object model
- Lifecycle
- Interfaces
- Memory contract
- Tool contract
- Skill contract
- Policy contract
- Verification contract
- Run-receipt contract

### Phase 1 — Tiny Runtime

```text
CLI
 ↓
Goal
 ↓
Agent
 ↓
Tool
 ↓
Result
```

No fancy UI.

### Phase 2 — Evidence + Verification

```text
Goal
 ↓
Evidence
 ↓
Action
 ↓
Verification
```

### Phase 3 — Memory

```text
Markdown
+
Frontmatter
+
SQLite
+
FTS5/BM25
```

### Phase 4 — Skills

Build a portable skill system compatible with the Agent Skills direction.

### Phase 5 — Learning

```text
Experience
 ↓
Lesson
 ↓
Candidate Skill
 ↓
Validation
 ↓
Version
```

### Phase 6 — DevOps Pack

Start with:

```text
Linux
SSH
Docker
Kubernetes
Git
Azure
AWS
Terraform
Prometheus
Grafana
```

### Phase 7 — MCP

Connect the existing ecosystem rather than rebuilding integrations.

### Phase 8 — Advanced Memory

```text
BM25
+
Embeddings
+
Reranking
+
Graph
```

### Phase 9 — Multi-Agent / A2A

Add specialist workers and external-agent interoperability only after the single-agent runtime is solid.

---

## 22. Architecture Decisions to Freeze

- **General-purpose core; DevOps is the first domain pack.**
- Core loop:

```text
Goal
→ Context
→ Evidence
→ Decide
→ Policy
→ Execute
→ Verify
→ Receipt
→ Learn
→ Memory
```

- Initial memory:

```text
Markdown
+
YAML Frontmatter
+
SQLite
+
FTS5/BM25
```

- Memory backend remains pluggable for:
  - Embeddings
  - GPU/local models
  - Reranking
  - Graph
  - Hybrid retrieval

- MCP is the primary integration layer.
- A2A is a later interoperability layer.
- Skills should be portable and compatible with the Agent Skills direction.
- Execution providers are modular:

```text
Local
→ Docker
→ SSH
→ Kubernetes
→ Cloud
```

- Safety model:

```text
Identity
→ Policy
→ Risk
→ Approval
→ Execution
```

- Learning model:

```text
Experience
→ Lesson
→ Candidate Skill
→ Validation
→ Version
→ Promotion
```

- Every meaningful run produces a provenance-rich run receipt.
- Multi-agent orchestration is not the first architectural dependency.

---

## 23. Final Positioning

### Category

**General-purpose agent execution runtime**

### Primary Differentiator

**Evidence-driven, verifiable execution**

### Secondary Differentiator

**Controlled self-learning**

### Architecture Philosophy

**Small universal core + pluggable domain packs**

### First Domain

**DevOps / SRE / platform operations**

### Initial Memory

**Markdown + frontmatter + SQLite FTS5/BM25**

### Integration

**MCP first; A2A later**

### Safety

**Identity → Policy → Risk → Approval → Execution**

---

## 24. Final Thesis

> **Most agent harnesses optimize what an agent can do; ours should optimize whether the agent actually accomplished the goal—and whether it learns from the result.**

---

## 25. Research Basis

The architecture was informed by research into:

- OpenClaw runtime architecture
- Pi extensibility model
- Hermes Agent self-learning, skills and memory
- Agent Skills specification
- Model Context Protocol (MCP)
- Agent2Agent Protocol (A2A)
- OpenHands execution/runtime concepts
- CNCF agentic platform-engineering direction
- OWASP agentic security guidance
- Continual-learning research for agents

The important conclusion is not to copy any one project. The opportunity is to combine the strongest existing standards and patterns while making **goal completion, evidence, verification, provenance and controlled learning** the center of the runtime.
