# Claude Managed Agents --- Deep Technical Architecture & How It Works

> **Research date:** 19 September 2026\
> **Primary documentation:** Anthropic Claude Platform Managed Agents
> documentation\
> **Beta:** `managed-agents-2026-04-01`\
> **Status:** Public beta
>
> This document explains the architecture, lifecycle, runtime, tool
> execution model, state, events, permissions, self-hosting, MCP,
> skills, memory, multi-agent orchestration, scheduled execution,
> versioning, and how to build a system around Claude Managed Agents.
>
> **Important:** Anthropic's current documentation was used as the
> primary technical source. The supplied YouTube page was also
> inspected, but the accessible page did not expose a transcript in the
> browsing interface, so this document does not invent or attribute
> video-specific implementation details that could not be verified.

------------------------------------------------------------------------

## 1. Executive summary

Claude Managed Agents is Anthropic's managed **agent harness**.

The important distinction is:

-   **Messages API:** Anthropic gives you model inference and tool-use
    primitives; you build the agent loop, state management, runtime,
    tool execution, retries, streaming orchestration, and surrounding
    infrastructure.
-   **Managed Agents:** Anthropic gives you a pre-built agent
    runtime/harness. You define an agent, define where it should
    execute, start a session, send events, and Claude can autonomously
    decide when to use tools and continue working.

The high-level architecture is:

``` text
                         YOUR APPLICATION
                               |
                               | API / SDK
                               v
                    +-----------------------+
                    | Anthropic Control     |
                    | Plane / Managed API   |
                    +-----------+-----------+
                                |
                 +--------------+--------------+
                 |                             |
                 v                             v
          Agent Definition               Session
          - Model                         - State
          - System prompt                 - Transcript
          - Tools                         - Events
          - MCP                           - Status
          - Skills                        - Outputs
                 |                             |
                 +--------------+--------------+
                                |
                                v
                       Agent Harness / Loop
                                |
                    Claude reasons about task
                                |
              +----------------+----------------+
              |                |                |
              v                v                v
           Files             Bash             Web/MCP
              |                |                |
              +----------------+----------------+
                                |
                                v
                         Sandbox Environment
```

The most important idea is that **the model is not the entire agent**.

A managed agent is a system composed of:

1.  a model,
2.  a system prompt,
3.  tools,
4.  permissions,
5.  MCP servers,
6.  skills,
7.  an execution environment,
8.  a persistent session,
9.  an event stream,
10. optional memory,
11. optional multi-agent delegation,
12. optional scheduled deployment.

Anthropic operates the orchestration layer. In a normal cloud
environment, Anthropic also operates the sandbox. With a self-hosted
environment, Anthropic continues to operate the orchestration/model side
while your infrastructure executes tools and code.

------------------------------------------------------------------------

# 2. Managed Agents vs Messages API

## 2.1 Messages API

With the Messages API, your application effectively owns the loop:

``` text
Application
    |
    +--> Send prompt to Claude
    |
    +<-- Claude response
    |
    +--> Inspect tool call
    |
    +--> Execute tool yourself
    |
    +--> Send tool result back
    |
    +<-- Claude decides next step
    |
    +--> Execute next tool
    |
    +--> ...
```

You need to build or operate:

-   agent loop
-   tool dispatch
-   sandbox/runtime
-   filesystem
-   state persistence
-   retry behavior
-   interruption
-   streaming
-   long-running execution
-   session recovery
-   scheduling
-   permission handling
-   observability
-   potentially compaction/context management

This is powerful because you have maximum control.

## 2.2 Managed Agents

Managed Agents moves much of that infrastructure behind the API:

``` text
Your application
       |
       v
Managed Agent API
       |
       v
Session
       |
       v
Managed Agent Harness
       |
       +---- Claude
       |
       +---- Tool selection
       |
       +---- Tool execution
       |
       +---- Context/state
       |
       +---- Event streaming
       |
       v
Sandbox
```

Your application becomes more like a **controller/client** than the
agent runtime itself.

You tell the system:

> Here is the agent definition, here is the environment, and here is the
> task.

The managed harness handles the repeated cycle of:

``` text
Observe
   ↓
Reason
   ↓
Select tool
   ↓
Execute tool
   ↓
Observe result
   ↓
Reason again
   ↓
Select another tool
   ↓
...
   ↓
Finish / idle
```

Anthropic describes this as a pre-built, configurable agent harness
intended particularly for long-running and asynchronous work.

------------------------------------------------------------------------

# 3. The four core objects

Managed Agents is easiest to understand as four major objects.

## 3.1 Agent

An **Agent** is a reusable configuration.

It contains or can contain:

``` text
Agent
├── name
├── model
├── system prompt
├── tools
├── MCP servers
├── skills
├── multiagent configuration
├── description
└── metadata
```

The agent is not the running process.

Think of it as:

> **Agent = blueprint / executable specification**

It is versioned and can be reused by many sessions.

Anthropic's documentation states that the agent bundles the model,
system prompt, tools, MCP servers, and skills.

------------------------------------------------------------------------

## 3.2 Environment

An **Environment** describes where the agent executes.

There are two major modes:

``` text
Environment
├── Cloud
│   └── Anthropic-managed sandbox
│
└── Self-hosted
    └── Your infrastructure
```

Think:

> **Environment = execution boundary**

The environment determines where shell commands, file operations,
processes, and network activity happen.

------------------------------------------------------------------------

## 3.3 Session

A **Session** is a running instance of an agent inside an environment.

Conceptually:

``` text
Agent definition
       +
Environment
       +
Task
       =
Session
```

A session owns the ongoing execution and conversation history.

It can:

-   receive user events,
-   run tools,
-   produce agent events,
-   remain active,
-   become idle,
-   be resumed,
-   be interrupted,
-   maintain state across interactions.

Think:

> **Session = actual running job/thread**

------------------------------------------------------------------------

## 3.4 Events

Events are the protocol used to communicate with the session.

Examples include:

``` text
user.message
user.interrupt
user.custom_tool_result
user.tool_confirmation
user.define_outcome
user.tool_result

agent.message
agent.tool_use
...
session.status_idle
```

The event stream is effectively the session's event log.

Think:

> **Events = appendable communication/state protocol**

------------------------------------------------------------------------

# 4. Agent definition in detail

An agent is a reusable, versioned configuration.

Example:

``` yaml
name: Coding Assistant

model:
  id: claude-opus-5
  effort: high

tools:
  - type: agent_toolset_20260401

system: |
  You are a production coding agent.
  Inspect the repository before changing it.
  Write tests for important changes.
  Do not expose secrets.
```

The exact supported model IDs and options should always be checked
against the current Anthropic model documentation.

------------------------------------------------------------------------

# 5. Model configuration

The model is the reasoning engine.

The configuration can include:

``` yaml
model:
  id: claude-opus-5
  effort: high
  speed: standard
  inference_geo: us
```

Depending on the model and current platform capabilities, model
configuration can include:

-   model ID
-   effort
-   speed
-   inference geography

### Effort

Effort controls how much reasoning effort the model applies.

Anthropic documents levels such as:

``` text
low
medium
high
xhigh
max
```

Availability depends on the model.

### Inference geography

The agent can optionally pin inference geography where supported.

Anthropic currently documents:

``` text
us
global
```

If configured, the inference geography is validated against workspace
policy.

This is important for organizations with data residency requirements.

------------------------------------------------------------------------

# 6. System prompt

The system prompt defines the agent's behavioral contract.

Example:

``` yaml
system: |
  You are a senior DevOps engineer.

  Goals:
  - diagnose production incidents
  - inspect Kubernetes resources
  - analyze logs
  - propose safe remediation

  Rules:
  - never expose credentials
  - do not delete production resources without approval
  - verify assumptions before changing infrastructure
```

A useful separation is:

``` text
System prompt
    = HOW the agent behaves

User event
    = WHAT the agent should do
```

For example:

``` text
SYSTEM:
You are a Kubernetes SRE.

USER:
Investigate why checkout-api has elevated Redis connection errors.
```

This distinction lets one agent configuration handle thousands of
different tasks.

------------------------------------------------------------------------

# 7. Tools

Tools are what turn a model into an agent.

The built-in agent toolset includes tools such as:

``` text
bash
read
write
edit
glob
grep
web_fetch
web_search
```

These provide the basic capabilities needed for coding, investigation,
research, and automation.

## 7.1 Bash

``` text
bash
```

Allows the agent to execute shell commands.

Examples:

``` bash
ls -lah
git status
python script.py
pytest
kubectl get pods
grep -R "ERROR" .
```

The command executes inside the configured environment.

This is extremely important:

> Claude does not magically execute commands on your laptop merely
> because it generated a Bash call.

The command executes wherever the session's environment is configured to
execute.

------------------------------------------------------------------------

# 8. Filesystem tools

The toolset includes:

### Read

``` text
read
```

Reads a file.

### Write

``` text
write
```

Creates/writes a file.

### Edit

``` text
edit
```

Performs string replacement/edit operations.

### Glob

``` text
glob
```

Finds files using patterns.

Example:

``` text
**/*.py
```

### Grep

``` text
grep
```

Searches text using patterns/regular expressions.

Together:

``` text
glob -> discover files
read -> inspect
grep -> search
edit -> modify
write -> create
bash -> execute/test
```

This is essentially the filesystem/tooling layer required for autonomous
coding.

------------------------------------------------------------------------

# 9. Web tools

Managed Agents can have:

``` text
web_search
web_fetch
```

This gives an agent the ability to:

``` text
search web
   ↓
find documentation
   ↓
fetch page
   ↓
extract relevant information
   ↓
continue task
```

Web access can be restricted through domain configuration.

This is useful for:

-   documentation research
-   troubleshooting
-   checking current APIs
-   researching dependencies
-   retrieving public technical references

------------------------------------------------------------------------

# 10. MCP

MCP provides standardized external tools.

Conceptually:

``` text
Claude Agent
     |
     v
MCP Toolset
     |
     +---- GitHub
     +---- Database
     +---- Jira
     +---- Slack
     +---- Internal API
     +---- Cloud platform
     +---- Custom enterprise system
```

MCP is different from the built-in filesystem/bash tools.

The built-in tools operate directly through the agent environment.

MCP provides standardized external capabilities.

------------------------------------------------------------------------

# 11. Custom tools

Managed Agents also supports application-defined custom tools.

The important architectural difference is:

``` text
Built-in tool:
Claude
  -> Anthropic-managed harness
  -> tool execution

Custom tool:
Claude
  -> tool request
  -> YOUR APPLICATION
  -> YOUR TOOL EXECUTION
  -> result
  -> Claude
```

This lets you keep sensitive business logic in your own application.

For example:

``` text
Agent
  |
  | call: get_customer_balance
  v
Your API
  |
  | query database
  v
PostgreSQL
  |
  v
Your API
  |
  | result
  v
Agent
```

Custom tools are controlled by your application rather than Managed
Agent permission policies.

------------------------------------------------------------------------

# 12. Permission policies

Permissions control whether tool calls can execute.

Anthropic currently documents:

``` text
always_allow
always_ask
auto
```

## 12.1 always_allow

The tool runs automatically.

``` text
Claude -> tool call -> execute
```

No approval is required.

The built-in agent toolset defaults to `always_allow`.

------------------------------------------------------------------------

## 12.2 always_ask

The session pauses before executing.

``` text
Claude
  |
  v
Tool request
  |
  v
WAIT
  |
  v
Human approval
  |
  +--> allow -> execute
  |
  +--> deny  -> do not execute
```

This is useful for:

-   destructive shell commands
-   production operations
-   external side effects
-   privileged APIs

Example:

``` yaml
default_config:
  permission_policy:
    type: always_ask
```

------------------------------------------------------------------------

## 12.3 auto

The server evaluates each call.

The evaluation can result in:

``` text
ALLOW
DENY
ASK
```

This is more dynamic than `always_allow` or `always_ask`.

The decision can consider:

-   tool
-   tool input
-   session content/context

Therefore two calls to the same tool can potentially receive different
decisions.

------------------------------------------------------------------------

# 13. Per-tool permissions

You do not have to apply one permission policy to every tool.

Example:

``` yaml
tools:
  - type: agent_toolset_20260401

    default_config:
      permission_policy:
        type: always_allow

    configs:
      - name: bash
        permission_policy:
          type: always_ask
```

This means:

``` text
read      -> automatic
grep      -> automatic
glob      -> automatic
write     -> automatic
bash      -> ask human
web_fetch -> automatic
```

This is a strong production pattern.

------------------------------------------------------------------------

# 14. Tool disabling

You can disable specific tools.

Example:

``` yaml
tools:
  - type: agent_toolset_20260401
    configs:
      - name: web_search
        enabled: false
      - name: web_fetch
        enabled: false
```

You can also use a deny-by-default configuration:

``` yaml
tools:
  - type: agent_toolset_20260401

    default_config:
      enabled: false

    configs:
      - name: bash
        enabled: true

      - name: read
        enabled: true

      - name: write
        enabled: true
```

This creates a much smaller capability boundary.

------------------------------------------------------------------------

# 15. Agent versioning

Agents are versioned resources.

Example:

``` text
Coding Agent

v1
 |
 | update
 v
v2
 |
 | update
 v
v3
```

Every meaningful configuration change can create a new version.

This allows:

``` text
Production sessions -> v1
Staging sessions    -> v2
New testing         -> v3
```

You can also pin a session to a particular agent version.

Example concept:

``` python
session = client.beta.sessions.create(
    agent={
        "type": "agent",
        "id": agent.id,
        "version": 1,
    },
    environment_id=environment.id,
)
```

This is important for reproducibility.

------------------------------------------------------------------------

# 16. Why version pinning matters

Imagine you deploy:

``` text
Agent v10
```

and start a long-running task.

Then you update the agent:

``` text
Agent v11
```

You generally do not want an already-running job to unexpectedly change
its entire behavior.

Versioning gives you controlled rollout.

A useful deployment model is:

``` text
                 Agent v10
                    |
             Production
                    |
                 Sessions

                 Agent v11
                    |
                 Staging
                    |
                Test sessions
```

After validation:

``` text
Production -> v11
```

This is conceptually similar to application deployment versioning.

------------------------------------------------------------------------

# 17. Agent lifecycle

An agent can be:

``` text
created
  |
  v
versioned
  |
  v
updated
  |
  v
new versions
  |
  v
archived
```

Archiving makes an agent read-only.

Existing sessions can continue, but new sessions cannot reference the
archived agent.

------------------------------------------------------------------------

# 18. Environment architecture

The environment is the execution boundary.

## Cloud environment

Conceptually:

``` text
Anthropic
  |
  +-- Agent orchestration
  |
  +-- Claude inference
  |
  +-- Sandbox
        |
        +-- filesystem
        +-- processes
        +-- bash
        +-- network
```

Your application communicates with the Anthropic API.

The actual tool execution happens in the sandbox.

------------------------------------------------------------------------

# 19. Self-hosted environment

Self-hosted Managed Agents changes the execution boundary.

Architecture:

``` text
                 Anthropic
                    |
                    |
             Agent orchestration
                    |
                    | tool execution requests
                    v
             YOUR INFRASTRUCTURE
                    |
             Environment Worker
                    |
          +---------+---------+
          |         |         |
       Files      Bash      Network
```

The key point is:

> Orchestration remains on Anthropic's side, but tool execution happens
> in infrastructure you control.

Anthropic documentation explicitly describes the filesystem, spawned
processes, and network reach as remaining under your control.

------------------------------------------------------------------------

# 20. Self-hosted data flow

A simplified flow:

``` text
User
 |
 v
Your application
 |
 v
Anthropic Managed Agents
 |
 v
Claude decides:
"Run command X"
 |
 v
Tool execution request
 |
 v
Self-hosted worker
 |
 +--> execute command
 |
 +--> collect stdout/stderr
 |
 v
Result
 |
 v
Anthropic control plane
 |
 v
Claude sees result
 |
 v
Claude decides next step
```

This is one of the most important architectural characteristics.

The model needs tool results in order to reason about what happened.

Therefore, even with self-hosted execution, tool inputs/results still
cross the Anthropic control-plane boundary.

------------------------------------------------------------------------

# 21. Why self-hosted environments matter

Self-hosting is useful when:

-   code cannot leave your network
-   internal services are private
-   databases are private
-   compliance requires infrastructure control
-   network egress must be controlled
-   execution must happen inside your VPC/VNet
-   your security team owns the runtime

Example:

``` text
Corporate Network
|
+-- Kubernetes
|    |
|    +-- Internal APIs
|    +-- PostgreSQL
|    +-- GitLab
|    +-- Vault
|
+-- Managed Agent Worker
       |
       +-- Claude tool execution
```

The agent can potentially reach resources according to your network
policies.

------------------------------------------------------------------------

# 22. Self-hosted worker

A self-hosted environment behaves like a work queue.

Conceptually:

``` text
Anthropic
   |
   | session assigned
   v
Environment queue
   |
   v
Worker polls
   |
   v
Worker receives execution request
   |
   v
Execute locally
   |
   v
Return result
```

The worker is responsible for executing tool requests.

Anthropic documents a pre-built worker CLI and also describes building a
worker using generic sandbox platforms.

Examples documented by Anthropic include:

-   AWS Lambda MicroVMs
-   Blaxel
-   Cloudflare
-   Daytona
-   E2B
-   Fly.io
-   GKE Agent Sandbox
-   Modal
-   Namespace
-   Superserve
-   Vercel

------------------------------------------------------------------------

# 23. Session lifecycle

A session is where the actual task happens.

Basic lifecycle:

``` text
CREATE
  |
  v
IDLE
  |
  | user.message
  v
RUNNING
  |
  +--> tool call
  |
  +--> tool result
  |
  +--> model reasoning
  |
  +--> more tools
  |
  v
IDLE
```

You can later send another message:

``` text
IDLE
 |
 | user.message
 v
RUNNING
 |
 v
IDLE
```

This is why sessions are stateful.

------------------------------------------------------------------------

# 24. Creating a session

A session needs:

``` text
agent ID
environment ID
```

Conceptually:

``` python
session = client.beta.sessions.create(
    agent=agent.id,
    environment_id=environment.id,
)
```

The session references the agent and environment.

------------------------------------------------------------------------

# 25. Agent version selection

If you pass:

``` text
agent = "agent_x"
```

the session uses the latest agent version.

If you pass:

``` text
agent = {
    type: "agent",
    id: "...",
    version: 1
}
```

you pin the session.

This gives you both:

``` text
latest-version workflow
```

and:

``` text
reproducible-version workflow
```

------------------------------------------------------------------------

# 26. Initial events

A session can be created with initial events.

Instead of:

``` text
1. create session
2. send message
```

you can do:

``` text
create session
+
initial_events
```

The documented API supports up to 50 initial `user.message` and
`user.define_outcome` events.

Conceptually:

``` python
session = client.beta.sessions.create(
    agent=agent.id,
    environment_id=environment.id,
    initial_events=[
        {
            "type": "user.message",
            "content": [
                {
                    "type": "text",
                    "text": "Inspect the repository and fix failing tests."
                }
            ],
        }
    ],
)
```

A non-empty initial event list starts the agent loop immediately.

------------------------------------------------------------------------

# 27. The actual agent loop

This is the most important part.

Suppose the user says:

``` text
Fix the failing tests in this repository.
```

The internal flow is approximately:

``` text
USER EVENT
   |
   v
Session receives task
   |
   v
Claude receives current context
   |
   v
Claude reasons
   |
   +---- Need repository files?
   |          |
   |          v
   |        glob/read
   |
   +---- Need search?
   |          |
   |          v
   |        grep
   |
   +---- Need execution?
   |          |
   |          v
   |        bash
   |
   v
Tool result
   |
   v
Claude observes result
   |
   v
Claude reasons again
   |
   +---- More tools?
   |       |
   |       +--> yes -> repeat
   |       |
   |       +--> no
   |
   v
Agent response
   |
   v
SESSION IDLE
```

The critical property is the **iterative loop**.

A single model response is not the complete task.

The harness repeatedly lets the model observe the current state and
choose the next action.

------------------------------------------------------------------------

# 28. Tool execution example

Suppose the task is:

``` text
Create fibonacci.py and generate fibonacci.txt.
```

Claude might internally produce a sequence like:

``` text
agent.message
  "I'll inspect the directory first."

agent.tool_use
  glob("**/*")

tool result
  repository contents

agent.tool_use
  write("fibonacci.py", ...)

tool result
  success

agent.tool_use
  bash("python fibonacci.py")

tool result
  success

agent.tool_use
  read("fibonacci.txt")

tool result
  contents

agent.message
  "The file was created successfully."

session.status_idle
```

The quickstart documentation demonstrates this exact architectural
pattern: Claude writes the script, runs it in the sandbox, verifies the
output, and then becomes idle.

------------------------------------------------------------------------

# 29. Streaming

Managed Agents uses server-sent events (SSE) to stream events.

Conceptually:

``` text
Anthropic
    |
    | HTTP streaming connection
    v
Your application

event 1
event 2
event 3
event 4
...
```

Your application can render events as they happen.

This is different from waiting for the entire task to finish.

------------------------------------------------------------------------

# 30. Why SSE matters

Long-running agents may take:

``` text
seconds
minutes
hours
```

You do not want your frontend to wait for one huge synchronous HTTP
response.

Instead:

``` text
request
   |
   +--> session running
   |
   +--> agent message
   |
   +--> tool use
   |
   +--> tool result
   |
   +--> agent message
   |
   +--> idle
```

The frontend can display progress.

------------------------------------------------------------------------

# 31. Event-driven UI architecture

A modern frontend can consume:

``` text
agent.message
agent.tool_use
session.status_idle
```

and render:

``` text
Claude:
I'll inspect the repository.

[Tool] glob

Found 142 files.

[Tool] grep

Found 4 failing-test references.

[Tool] bash

pytest ...

Tests passed.

Claude:
The issue was...
```

The event log can therefore become the source of truth for the UI.

------------------------------------------------------------------------

# 32. Persisted events

Managed Agent event history is persisted server-side.

This means the application does not have to treat the browser as the
canonical transcript.

Conceptually:

``` text
Browser
   |
   v
Backend
   |
   v
Managed Session
   |
   +-- persisted events
   +-- transcript
   +-- tool events
   +-- status
```

The application can retrieve session events later.

------------------------------------------------------------------------

# 33. Interrupting an agent

A running agent can be interrupted using a user event.

Conceptually:

``` text
RUNNING
   |
   | user.interrupt
   v
STOP / INTERRUPTED
```

This is important for long-running jobs.

For example:

``` text
Agent:
Running migration...

Human:
Stop. Do not continue.

user.interrupt
```

The application can then redirect the agent.

------------------------------------------------------------------------

# 34. Steering an agent

A powerful characteristic is that you can send another user event while
the agent is working.

For example:

``` text
USER:
Investigate this incident.

Agent:
checking logs...

USER:
Focus specifically on Redis timeout errors.

Agent:
adjusts investigation
```

This makes the session interactive even when the task is long-running.

------------------------------------------------------------------------

# 35. Stateful sessions

Managed Agents are stateful by design.

A session can preserve:

-   conversation history
-   sandbox state
-   files
-   outputs
-   session events

Therefore:

``` text
Turn 1
  |
  +--> create file
  |
  v
Turn 2
  |
  +--> inspect file
  |
  v
Turn 3
  |
  +--> modify file
```

The agent does not have to recreate everything from scratch on every
interaction.

------------------------------------------------------------------------

# 36. Sandbox state

Consider:

``` text
/workspace
├── app.py
├── tests/
├── requirements.txt
└── output.json
```

Claude can create these files during one part of the session and use
them later.

This is much closer to a real workstation than a stateless
prompt/response API.

------------------------------------------------------------------------

# 37. Long-running execution

Managed Agents is designed for tasks that may require many iterations.

Example:

``` text
Task:
Modernize a 300-file Python repository.
```

Potential loop:

``` text
inspect
 ↓
plan
 ↓
edit
 ↓
run tests
 ↓
inspect failures
 ↓
edit
 ↓
run tests
 ↓
lint
 ↓
fix
 ↓
run tests
 ↓
review
 ↓
finish
```

The application does not need to manually implement every transition.

------------------------------------------------------------------------

# 38. Prompt caching and compaction

The Managed Agents harness includes optimizations such as prompt caching
and compaction.

The objective is to keep long-running agent sessions efficient.

Conceptually:

``` text
Long session

Turn 1
Turn 2
Turn 3
...
Turn 50
Turn 51
...
```

Without context management, the amount of historical information can
become expensive or exceed context limits.

Compaction can summarize older material while retaining important recent
context.

The exact compaction behavior and configuration should be treated as
platform behavior rather than something the application should
reimplement blindly.

------------------------------------------------------------------------

# 39. Large tool outputs

Managed Agents handles very large tool outputs.

When a tool output exceeds approximately:

``` text
100,000 characters
```

the system can spill the output into a sandbox file and provide the
model with a truncated preview plus the file path.

This changes the behavior from:

``` text
Huge output
   ↓
Put everything into model context
```

to:

``` text
Huge output
   |
   +--> file in sandbox
   |
   +--> short preview + path
             |
             v
        Claude reads file
        only when needed
```

This is an important context-efficiency mechanism.

------------------------------------------------------------------------

# 40. Skills

Skills provide reusable domain-specific expertise.

A useful conceptual separation is:

``` text
System prompt
    = global behavior

Skill
    = reusable domain/workflow knowledge

Tool
    = capability/action

MCP
    = external service capability
```

For example:

``` text
Agent: Security Engineer

Skills:
- Kubernetes troubleshooting
- AWS incident response
- PCI compliance investigation
- Python secure coding
```

The same skill can potentially be reused across multiple agents.

Skills use progressive disclosure, meaning the agent can load the
relevant material when needed instead of forcing every piece of
knowledge into the initial prompt.

------------------------------------------------------------------------

# 41. GitHub context

Managed Agents can work with GitHub repositories.

A typical coding workflow becomes:

``` text
GitHub repository
       |
       v
Session environment
       |
       v
Claude
       |
       +--> inspect repository
       +--> modify code
       +--> run tests
       +--> produce changes
```

This is one reason Managed Agents is particularly suitable for
autonomous software-engineering tasks.

------------------------------------------------------------------------

# 42. Memory

Managed Agents supports persistent memory stores.

Think of two different state types:

### Session state

``` text
What happened in this session?
```

### Memory

``` text
What should the agent remember across sessions?
```

Architecture:

``` text
Session A
   |
   +--> discovers preference/fact
   |
   v
Memory store
   |
   v
Session B
   |
   +--> loads relevant memory
```

This allows knowledge to persist beyond one session.

------------------------------------------------------------------------

# 43. Memory vs filesystem

They are not identical.

Filesystem:

``` text
/workspace/project/config.json
```

is execution state.

Memory:

``` text
User prefers PostgreSQL.
Deployment uses GitOps.
```

is persistent agent knowledge.

A good mental model:

``` text
Filesystem
= working state

Session transcript
= conversational state

Memory store
= reusable long-term knowledge
```

------------------------------------------------------------------------

# 44. Dreams / memory reorganization

Anthropic has also documented a research-preview "dreaming" capability.

Conceptually:

``` text
Past sessions
      +
Existing memory
      |
      v
Dream / consolidation process
      |
      +--> merge duplicates
      +--> remove stale knowledge
      +--> identify new insights
      |
      v
Reorganized memory store
```

This is analogous to a background memory-consolidation process.

It should not be confused with ordinary model reasoning during a
session.

------------------------------------------------------------------------

# 45. Multi-agent orchestration

Managed Agents can support agents that delegate work to other agents.

Conceptually:

``` text
                    Coordinator
                        |
          +-------------+-------------+
          |             |             |
          v             v             v
       Research       Coding        Testing
        Agent          Agent         Agent
```

The coordinator is itself an agent.

It can decide:

``` text
This is a research task
        |
        v
delegate to researcher
```

Then:

``` text
Research result
        |
        v
Coordinator
        |
        v
delegate implementation
```

------------------------------------------------------------------------

# 46. Coordinator architecture

A multi-agent system can look like:

``` text
                 User
                  |
                  v
            Coordinator
                  |
       +----------+----------+
       |          |          |
       v          v          v
    Analyst     Coder      Reviewer
       |          |          |
       +----------+----------+
                  |
                  v
             Coordinator
                  |
                  v
              Final answer
```

This can separate responsibilities.

For example:

``` text
Coordinator:
plan and delegate

Research agent:
collect facts

Coding agent:
modify repository

Test agent:
run validation

Security agent:
review changes
```

The coordinator then integrates the results.

------------------------------------------------------------------------

# 47. Advisor model

Anthropic also documents an advisor capability.

A session can consult another model for strategic guidance.

Conceptually:

``` text
Primary agent
     |
     | "I need a second opinion"
     v
Advisor model
     |
     v
Strategic guidance
     |
     v
Primary agent continues
```

The advisor does not necessarily replace the primary agent.

It acts more like a specialist consulted during the task.

------------------------------------------------------------------------

# 48. Scheduled deployments

Managed Agents supports scheduled deployments.

This allows:

``` text
cron
 |
 v
Managed Agent session
 |
 v
task execution
```

Example:

``` text
Every day at 01:00
      |
      v
Create session
      |
      v
Run security analysis
      |
      v
Generate report
```

This removes the need to build your own scheduler for some recurring
workloads.

------------------------------------------------------------------------

# 49. Example scheduled DevOps agent

Imagine:

``` text
Daily 01:00
    |
    v
Security Agent
    |
    +--> inspect Kubernetes
    +--> inspect logs
    +--> query vulnerability data
    +--> summarize findings
    +--> create report
    |
    v
Slack / email / dashboard
```

The schedule starts sessions; the agent performs the work.

------------------------------------------------------------------------

# 50. Webhooks

Managed Agents supports webhooks for lifecycle events.

Instead of continuously polling:

``` text
while true:
    GET session
```

you can use:

``` text
Managed Agents
      |
      | webhook
      v
Your backend
```

Events can cover various resource lifecycles including sessions and,
according to current release documentation, agents, deployments,
deployment runs, environments, and memory stores.

This is useful for production orchestration.

------------------------------------------------------------------------

# 51. Outcomes

Managed Agents also supports explicit outcomes.

Instead of simply saying:

``` text
Do this task.
```

you can define:

``` text
Desired outcome:
The repository has zero failing tests and a generated test report.
```

The outcome acts as a goal specification.

Conceptually:

``` text
Outcome
   |
   v
Agent planning
   |
   v
Tool execution
   |
   v
Validation
   |
   +--> outcome achieved
   |
   +--> continue working
```

This is useful for autonomous work where the important thing is the
final state rather than a specific sequence of commands.

------------------------------------------------------------------------

# 52. Budgets

Managed Agents sessions can have a budget.

The budget is a hard spending cap for the session.

Conceptually:

``` text
Session
 |
 +--> model calls
 +--> tool cycles
 +--> model calls
 +--> ...
 |
 v
Budget reached
 |
 v
Session pauses
```

The current documentation describes a `budget_reached` stop reason.

This is important for production systems because an autonomous loop must
have cost boundaries.

------------------------------------------------------------------------

# 53. Vaults and credentials

Managed Agents supports vault-based credentials.

The purpose is to avoid putting secrets directly into:

``` text
system prompts
user messages
agent YAML
source code
```

Instead:

``` text
Agent
  |
  v
Vault
  |
  v
Credential
  |
  v
Sandbox / request
```

Current platform capabilities include environment-variable credentials
and credential injection behavior.

This is particularly useful for:

``` text
AWS CLI
GitHub CLI
database clients
cloud CLIs
private APIs
```

------------------------------------------------------------------------

# 54. Secret injection model

A safe conceptual pattern is:

``` text
Secret
   |
   v
Vault
   |
   v
Session
   |
   v
Environment variable
   |
   v
CLI/tool
```

rather than:

``` text
Secret
   |
   v
system prompt
   |
   v
model context
```

The latter unnecessarily exposes the credential to model context.

------------------------------------------------------------------------

# 55. MCP tunnels

MCP tunnels can connect agents to MCP servers inside private networks.

Conceptually:

``` text
Anthropic Managed Agent
        |
        | secure tunnel
        v
Private Network
        |
        +-- Internal MCP server
        |
        +-- Internal services
```

Self-hosted sandboxes and MCP tunnels solve different problems:

``` text
Self-hosted sandbox
= where code/tool execution happens

MCP tunnel
= how Anthropic reaches a private MCP server
```

They can be combined.

------------------------------------------------------------------------

# 56. Cloud vs self-hosted vs MCP tunnel

A useful matrix:

  -----------------------------------------------------------------------
  Architecture      Agent             Tool execution    Private internal
                    orchestration                       services
  ----------------- ----------------- ----------------- -----------------
  Cloud sandbox     Anthropic         Anthropic         Limited by
                                                        configured
                                                        network

  Self-hosted       Anthropic         Your              Yes, subject to
                                      infrastructure    your network

  Cloud + MCP       Anthropic         Anthropic sandbox MCP can reach
  tunnel                                                private server

  Self-hosted + MCP Anthropic         Your              Both execution
  tunnel                              infrastructure    and MCP access
                                                        can stay within
                                                        your boundary
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 57. Managed Agent as a distributed system

The best way to understand the architecture is as a distributed system.

``` text
                         +----------------+
                         | Your frontend  |
                         +-------+--------+
                                 |
                                 v
                         +----------------+
                         | Your backend   |
                         +-------+--------+
                                 |
                              API/SDK
                                 |
                                 v
                  +-------------------------------+
                  | Anthropic Managed Agent Plane |
                  |                               |
                  |  Session Manager              |
                  |  Agent Config                 |
                  |  Event Store                  |
                  |  Agent Harness                |
                  |  Claude Inference             |
                  +---------------+---------------+
                                  |
                     tool execution request
                                  |
                    +-------------+-------------+
                    |                           |
                    v                           v
             Cloud Sandbox              Self-hosted Worker
                    |                           |
             +------+------+              +-----+-----+
             |             |              |     |     |
           Files         Bash           Files Bash Network
             |
           Network
```

------------------------------------------------------------------------

# 58. Control plane vs data plane

This distinction is extremely useful.

## Control plane

Responsible for:

-   agent definitions
-   versions
-   sessions
-   event history
-   orchestration
-   model inference
-   scheduling
-   lifecycle
-   coordination

## Execution/data plane

Responsible for:

-   files
-   processes
-   commands
-   filesystem mutations
-   network access
-   local runtime

Cloud:

``` text
Anthropic control plane
+
Anthropic execution plane
```

Self-hosted:

``` text
Anthropic control plane
+
Your execution plane
```

------------------------------------------------------------------------

# 59. Building a coding agent

A minimal architecture:

``` text
Git repository
       |
       v
Managed Agent
       |
       +-- Claude
       +-- read
       +-- write
       +-- edit
       +-- grep
       +-- glob
       +-- bash
       |
       v
Sandbox
       |
       +-- git
       +-- Python
       +-- Node
       +-- test tools
```

Agent configuration:

``` yaml
name: Coding Agent

model: claude-opus-5

tools:
  - type: agent_toolset_20260401

system: |
  You are a senior software engineer.
  Inspect before modifying.
  Run tests after changes.
  Explain failures clearly.
```

------------------------------------------------------------------------

# 60. Example coding lifecycle

Task:

``` text
Fix issue #142.
```

Agent:

``` text
1. inspect repository
2. inspect git status
3. search issue-related code
4. read relevant files
5. identify root cause
6. edit code
7. run tests
8. inspect failures
9. modify again
10. rerun tests
11. review diff
12. summarize
```

This is exactly the sort of multi-step workflow where a managed harness
is useful.

------------------------------------------------------------------------

# 61. Building a Kubernetes/SRE agent

For an infrastructure agent, the architecture could be:

``` text
Agent
 |
 +-- bash
 +-- read
 +-- grep
 +-- web_search
 +-- web_fetch
 +-- MCP
       |
       +-- Kubernetes
       +-- Cloud
       +-- Monitoring
       +-- Incident system
```

Example task:

``` text
Investigate why API latency increased.
```

Agent might:

``` text
1. inspect metrics
2. inspect pods
3. inspect events
4. inspect logs
5. correlate timestamps
6. inspect deployment changes
7. inspect external dependencies
8. form hypothesis
9. validate hypothesis
10. report root cause/evidence
```

The agent harness repeatedly executes the tool loop.

------------------------------------------------------------------------

# 62. Safe production SRE pattern

For production infrastructure, do not blindly allow all commands.

A stronger design is:

``` text
Read-only tools
    -> always_allow

Diagnostic bash
    -> always_allow / auto

Mutation commands
    -> always_ask

Destructive operations
    -> always_ask

Production MCP tools
    -> always_ask or auto
```

Example:

``` text
kubectl get
kubectl describe
kubectl logs
        |
        v
automatic

kubectl delete
kubectl rollout restart
        |
        v
approval
```

This creates a capability boundary.

------------------------------------------------------------------------

# 63. Building a research agent

Architecture:

``` text
Agent
 |
 +-- web_search
 +-- web_fetch
 +-- write
 +-- read
 +-- grep
 |
 v
Research workspace
 |
 +-- sources/
 +-- notes/
 +-- report.md
```

Task:

``` text
Research current Kubernetes ingress changes
and produce a technical report.
```

Agent can:

``` text
search
  ↓
fetch
  ↓
compare
  ↓
write notes
  ↓
synthesize
  ↓
write report
```

------------------------------------------------------------------------

# 64. Building a security agent

A security agent can combine:

``` text
Bash
Files
Web
MCP
Skills
Memory
```

Example:

``` text
Security Agent
 |
 +-- local scanner
 +-- GitHub
 +-- CVE database
 +-- Kubernetes
 +-- cloud APIs
 +-- ticketing system
```

Potential flow:

``` text
Scheduled deployment
        |
        v
Pull latest repository
        |
        v
Run dependency scan
        |
        v
Query vulnerability information
        |
        v
Correlate findings
        |
        v
Generate report
        |
        v
Create ticket through MCP
```

Sensitive actions can require approval.

------------------------------------------------------------------------

# 65. Agent + MCP architecture

Example enterprise setup:

``` text
                   Claude
                     |
               Managed Agent
                     |
              +------+------+
              |             |
          Built-in        MCP
            tools          tools
              |             |
              |        +----+----+
              |        |         |
             Bash    GitHub     Jira
              |        |         |
              v        v         v
          Sandbox   External  External
```

The MCP tool can be permission-controlled independently.

------------------------------------------------------------------------

# 66. Agent + custom tool architecture

Suppose you have an internal deployment API.

``` text
Claude
 |
 | deploy_service(...)
 v
Managed Agent
 |
 | custom tool request
 v
Your backend
 |
 | authenticated internal call
 v
Deployment API
 |
 v
result
 |
 v
Claude
```

This is useful when the action must stay inside your backend.

------------------------------------------------------------------------

# 67. Agent + self-hosted Kubernetes architecture

For an enterprise Kubernetes setup:

``` text
                    Internet
                       |
                       v
              Your Agent API
                       |
                       v
                Anthropic API
                       |
                       v
             Managed Agent Control
                       |
                       | work item
                       v
               Self-hosted worker
                       |
             +---------+---------+
             |                   |
             v                   v
        Kubernetes API       Internal APIs
             |
        +----+----+
        |         |
       Pods     Services
```

The worker can be deployed as:

``` text
Deployment
   |
   +-- worker pod
```

with restricted:

``` text
RBAC
NetworkPolicy
service account
egress
filesystem
```

------------------------------------------------------------------------

# 68. Applying zero-trust principles

For a production self-hosted agent:

``` text
Agent
 |
 +-- dedicated service account
 +-- minimal RBAC
 +-- namespace isolation
 +-- network policies
 +-- short-lived credentials
 +-- secret vault
 +-- approval for mutations
 +-- audit logs
```

Do not give the worker:

``` text
cluster-admin
```

unless there is a very strong reason.

Prefer:

``` text
get/list/watch
```

for diagnostics.

And separately authorize:

``` text
patch/update/delete
```

when required.

------------------------------------------------------------------------

# 69. GitOps integration

Managed Agents can fit into GitOps workflows.

For example:

``` text
Agent
 |
 | modify repository
 v
Git
 |
 v
Pull Request
 |
 v
CI
 |
 v
Argo CD
 |
 v
Kubernetes
```

A production-safe pattern is:

``` text
Agent
  |
  +--> analyze issue
  +--> modify manifest
  +--> run tests
  +--> create PR
       |
       v
    human review
       |
       v
      merge
       |
       v
     ArgoCD
```

This avoids giving the agent direct production deployment authority.

------------------------------------------------------------------------

# 70. Why the harness matters

Without a harness:

``` text
You need to implement:

while not done:
    response = model(...)
    if tool_call:
        execute()
        append_result()
    ...
```

And then you discover you also need:

``` text
timeouts
retries
streaming
state
interrupts
context management
tool permissions
sandbox
large output handling
long-running execution
scheduling
webhooks
memory
multi-agent
```

Managed Agents packages much of this into a platform primitive.

That is the primary value proposition.

------------------------------------------------------------------------

# 71. The "agent" is not just Claude

A useful equation is:

``` text
Agent
=
Model
+
Prompt
+
Tools
+
Permissions
+
Runtime
+
State
+
Events
+
Optional Memory
+
Optional MCP
+
Optional Delegation
```

Therefore:

``` text
Claude model != complete agent
```

The model is the reasoning component.

The harness is what repeatedly connects reasoning to action.

------------------------------------------------------------------------

# 72. The runtime loop in minute detail

Consider:

``` text
User:
"Fix the failing API tests."
```

### Step 1 --- Event arrives

``` text
user.message
```

The session receives the task.

### Step 2 --- Context assembled

The system determines relevant session context:

``` text
system prompt
agent configuration
conversation history
tool definitions
skills
MCP configuration
session state
```

### Step 3 --- Model inference

Claude reasons about the next action.

Potential result:

``` text
call glob("**/*test*")
```

### Step 4 --- Permission evaluation

The system checks:

``` text
Is glob enabled?
What permission policy applies?
```

### Step 5 --- Tool execution

The tool executes in the environment.

### Step 6 --- Result returned

Example:

``` text
Found:
tests/api/test_checkout.py
tests/api/test_payment.py
```

### Step 7 --- Model observes result

Claude receives the tool result.

### Step 8 --- Next action

Claude decides:

``` text
read("tests/api/test_checkout.py")
```

### Step 9 --- Repeat

The loop continues.

### Step 10 --- Validation

Claude may execute:

``` bash
pytest tests/api/
```

### Step 11 --- Failure handling

If tests fail:

``` text
test output
    |
    v
Claude analyzes
    |
    v
edit code
    |
    v
pytest again
```

### Step 12 --- Completion

Once Claude determines the task is complete:

``` text
agent.message
```

followed by:

``` text
session.status_idle
```

------------------------------------------------------------------------

# 73. Why "idle" is important

Idle does not necessarily mean:

``` text
the session is deleted
```

It means the current agent execution has no more work to perform.

The session can remain available for another user event.

Thus:

``` text
Session
 |
 +--> run task A
 |       |
 |       v
 |      idle
 |
 +--> run task B
 |       |
 |       v
 |      idle
 |
 +--> run task C
```

This creates a persistent conversational worker.

------------------------------------------------------------------------

# 74. Session as a durable job/thread

A useful analogy:

``` text
Traditional HTTP request
=
one request -> one response

Managed Agent session
=
durable thread + execution environment + event log
```

This is why it is suitable for:

-   coding agents
-   research agents
-   analyst agents
-   DevOps agents
-   scheduled agents
-   long-running workflows

------------------------------------------------------------------------

# 75. Failure handling

A production wrapper should still plan for:

``` text
API failure
sandbox failure
tool failure
network failure
model failure
permission denial
budget exhaustion
worker failure
session interruption
```

A robust application should treat the session as an asynchronous job
rather than assuming every task completes in one HTTP call.

------------------------------------------------------------------------

# 76. Observability

Because the architecture is event-driven, useful observability
dimensions include:

``` text
session ID
agent ID
agent version
environment ID
event type
tool name
tool duration
tool success/failure
approval state
budget usage
session status
```

A production dashboard could show:

``` text
Session: sess_xxx

Status: RUNNING

Agent:
Coding Agent v12

Elapsed:
18m 42s

Tools:
bash       24
read       51
grep       18
write       7
web_search  4

Current:
Running tests
```

------------------------------------------------------------------------

# 77. Security boundary

There are multiple boundaries:

``` text
1. Model boundary
2. Agent configuration boundary
3. Permission boundary
4. Environment boundary
5. Network boundary
6. Credential boundary
7. MCP boundary
8. Application boundary
```

A strong design configures all of them.

------------------------------------------------------------------------

# 78. Data retention consideration

Managed Agents is stateful by design.

Anthropic currently states that Managed Agents is not eligible for Zero
Data Retention or HIPAA BAA coverage because sessions store:

-   conversation history
-   sandbox state
-   outputs

The API provides mechanisms to delete sessions and uploaded files.

This is an architectural decision, not merely a UI setting.

If your application requires strict ZDR or HIPAA BAA eligibility, verify
feature-specific eligibility before choosing Managed Agents.

------------------------------------------------------------------------

# 79. Beta status

The platform is currently beta and requires:

``` text
managed-agents-2026-04-01
```

as the beta header.

The SDK can set the beta header automatically.

Some advanced capabilities have separate research-preview status.

Therefore:

``` text
Do not hard-code assumptions about beta behavior forever.
```

Pin SDK versions and test upgrades.

------------------------------------------------------------------------

# 80. Declarative infrastructure with `ant`

Anthropic's `ant` CLI allows resources to be defined as files and
applied.

Conceptually:

``` text
Repository
|
+-- agent.md
+-- environment.yaml
+-- skill/
+-- deployment.yaml
+-- claude-lock.json
|
v
ant apply
|
v
Anthropic resources
```

This makes Managed Agents feel closer to infrastructure-as-code.

------------------------------------------------------------------------

# 81. Why `claude-lock.json` matters

The CLI can record resource IDs/versions in a lockfile.

Conceptually:

``` text
agent definition
      +
lockfile
      |
      v
ant apply
      |
      v
update existing resource
```

This helps CI/CD avoid accidentally creating duplicate resources.

A GitOps-like workflow can therefore be:

``` text
Git
 |
 v
Review
 |
 v
CI
 |
 v
ant apply
 |
 v
Managed Agent resources
```

------------------------------------------------------------------------

# 82. Managed Agents + GitOps

A mature setup could look like:

``` text
agent-platform-repo/
|
+-- agents/
|    +-- sre-agent.md
|    +-- coding-agent.md
|    +-- security-agent.md
|
+-- environments/
|    +-- prod.yaml
|    +-- staging.yaml
|
+-- skills/
|
+-- deployments/
|
+-- claude-lock.json
|
+-- README.md
```

Pipeline:

``` text
Git commit
    |
    v
PR
    |
    v
review
    |
    v
CI validation
    |
    v
ant apply
    |
    v
Managed Agents
```

This is conceptually very close to the infrastructure-as-code model.

------------------------------------------------------------------------

# 83. Recommended production architecture

For a serious enterprise deployment:

``` text
                         Users
                           |
                           v
                    Web / Slack / API
                           |
                           v
                    Application Backend
                           |
                 +---------+---------+
                 |                   |
                 v                   v
             Sessions           Webhooks
                 |
                 v
         Anthropic Managed Agents
                 |
      +----------+-----------+
      |                      |
      v                      v
 Cloud Sandbox        Self-hosted Worker
                             |
                    +--------+--------+
                    |        |        |
                    v        v        v
                  K8s      Git      Internal APIs
```

Supporting systems:

``` text
Vault / secrets
      |
      v
credentials

MCP
      |
      v
external/internal services

Memory
      |
      v
persistent agent knowledge

Skills
      |
      v
domain expertise

Monitoring
      |
      v
events / logs / metrics
```

------------------------------------------------------------------------

# 84. Example enterprise SRE agent design

## Agent

``` yaml
name: Production SRE

model:
  id: claude-opus-5
  effort: high

tools:
  - type: agent_toolset_20260401
    default_config:
      permission_policy:
        type: always_allow
    configs:
      - name: bash
        permission_policy:
          type: auto

system: |
  You are a production SRE.
  Diagnose incidents using evidence.
  Prefer read-only inspection.
  Do not perform destructive actions without approval.
```

## Environment

``` yaml
name: sre-prod-worker

config:
  type: self_hosted
```

## Network

``` text
worker
 |
 +--> Kubernetes API
 +--> monitoring
 +--> logging
 +--> internal DNS
 +--> Git
```

## Permissions

``` text
read/list/watch -> allowed

restart/patch -> approval

delete -> approval

cluster-admin -> forbidden
```

------------------------------------------------------------------------

# 85. Example task

User:

``` text
Investigate checkout latency increase from 23:05 to 23:10 IST.
Do not modify anything.
```

Agent process:

``` text
1. inspect session/task context
2. query monitoring
3. inspect pod metrics
4. inspect logs
5. search Redis errors
6. inspect deployment changes
7. correlate timestamps
8. formulate hypothesis
9. validate with additional evidence
10. produce incident report
```

No mutation permissions are necessary.

This is a strong use case for a read-only diagnostic agent.

------------------------------------------------------------------------

# 86. Coding agent with human-in-the-loop

Another production pattern:

``` text
Agent
 |
 +-- read -> automatic
 +-- grep -> automatic
 +-- edit -> automatic
 +-- tests -> automatic
 +-- git diff -> automatic
 |
 +-- git push -> approval
 +-- PR merge -> approval
 +-- production deploy -> approval
```

The agent can do most of the mechanical work while humans retain control
over consequential operations.

------------------------------------------------------------------------

# 87. Multi-agent coding pipeline

A larger system could be:

``` text
                    Coordinator
                         |
       +-----------------+----------------+
       |                 |                |
       v                 v                v
   Researcher         Coder            Tester
       |                 |                |
       +-----------------+----------------+
                         |
                         v
                     Reviewer
                         |
                         v
                    Coordinator
```

Flow:

``` text
Requirement
   |
   v
Coordinator
   |
   +--> Research
   |
   +--> Implementation
   |
   +--> Testing
   |
   +--> Review
   |
   v
Final result
```

This can reduce the cognitive load on one agent and provide
specialization.

------------------------------------------------------------------------

# 88. Scheduled security pipeline

Example:

``` text
01:00
 |
 v
Scheduled deployment
 |
 v
Security agent session
 |
 +--> clone/update repository
 +--> dependency scan
 +--> secret scan
 +--> static analysis
 +--> web/CVE research
 +--> correlate findings
 +--> write report
 |
 v
Webhook
 |
 v
Security dashboard / ticket
```

------------------------------------------------------------------------

# 89. Memory-driven support agent

Architecture:

``` text
Customer
   |
   v
Support Agent
   |
   +--> session history
   |
   +--> memory store
   |
   +--> CRM MCP
   |
   +--> ticketing MCP
   |
   v
Resolution
```

Memory can preserve reusable facts while the session contains the
current conversation.

------------------------------------------------------------------------

# 90. Managed Agent vs building your own harness

  Capability                  Messages API              Managed Agents
  --------------------------- ------------------------- ----------------------
  Model access                Yes                       Yes
  Custom loop                 You build                 Managed
  Sandbox                     You build/provide         Cloud or self-hosted
  Built-in filesystem tools   You integrate             Built-in
  Bash                        You integrate             Built-in
  Web tools                   You integrate             Built-in
  Session persistence         You build                 Built-in
  Event streaming             You build orchestration   Built-in
  Tool permissions            You build                 Built-in
  Long-running sessions       You build                 Built-in
  Scheduled deployments       You build                 Built-in
  Memory                      You build/integrate       Supported
  Multi-agent                 You build                 Supported
  MCP                         Supported                 Supported
  Fine-grained loop control   Very high                 Lower
  Infrastructure burden       Higher                    Lower

The tradeoff is essentially:

``` text
Messages API
= maximum control

Managed Agents
= maximum managed infrastructure
```

------------------------------------------------------------------------

# 91. What Anthropic is actually managing

When people hear "managed agent", it is easy to think:

> Anthropic hosts Claude and nothing else.

The bigger picture is:

``` text
Model inference
        +
Agent loop
        +
Tool orchestration
        +
Session state
        +
Event streaming
        +
Sandbox integration
        +
Permission mechanism
        +
Long-running execution
        +
Scheduling
        +
Lifecycle
```

That combined system is the managed harness.

------------------------------------------------------------------------

# 92. What you still own

Managed Agents does not eliminate your application architecture.

You still need to decide:

``` text
Who can start sessions?
Which agent?
Which environment?
Which permissions?
Which data?
Which MCP servers?
Which secrets?
Which network access?
Which outputs?
Which approval process?
Which retention policy?
```

You also need:

``` text
frontend/backend
authentication
authorization
business logic
observability
incident response
cost controls
governance
```

Managed Agents provides the agent execution primitive, not an entire
enterprise application.

------------------------------------------------------------------------

# 93. The most important mental model

Remember these five layers:

``` text
LAYER 1 — MODEL
Claude reasoning

LAYER 2 — AGENT
Prompt + model + tools + skills + MCP

LAYER 3 — SESSION
Running task + history + events

LAYER 4 — ENVIRONMENT
Sandbox where tools execute

LAYER 5 — APPLICATION
Your UI/API/business system
```

Diagram:

``` text
+--------------------------------------+
|           YOUR APPLICATION           |
|       Web / API / Slack / CLI       |
+------------------+-------------------+
                   |
+------------------v-------------------+
|               SESSION                |
|       state + events + history       |
+------------------+-------------------+
                   |
+------------------v-------------------+
|                AGENT                 |
| model + prompt + tools + MCP + skills|
+------------------+-------------------+
                   |
+------------------v-------------------+
|             AGENT HARNESS            |
| planning/tool loop/permissions/etc.  |
+------------------+-------------------+
                   |
+------------------v-------------------+
|             ENVIRONMENT              |
| filesystem + processes + network     |
+--------------------------------------+
```

------------------------------------------------------------------------

# 94. How to build one from zero

## Step 1 --- Create API credentials

Obtain an Anthropic API key.

Store it securely.

Example:

``` bash
export ANTHROPIC_API_KEY="..."
```

Do not commit it.

------------------------------------------------------------------------

## Step 2 --- Install SDK

Python:

``` bash
pip install anthropic
```

The current quickstart documents the Anthropic SDK installation and the
Managed Agents beta session APIs.

------------------------------------------------------------------------

## Step 3 --- Define the agent

Example:

``` yaml
---
name: Coding Assistant
model: claude-opus-5
tools:
  - type: agent_toolset_20260401
---

You are a helpful coding agent.

Inspect the repository before changing files.
Run relevant tests after changes.
```

------------------------------------------------------------------------

## Step 4 --- Create environment

Cloud:

``` yaml
name: coding-environment

config:
  type: cloud
  networking:
    type: unrestricted
```

For production, networking should normally be restricted according to
your requirements rather than copied blindly from a quickstart.

------------------------------------------------------------------------

## Step 5 --- Create session

``` python
session = client.beta.sessions.create(
    agent=agent.id,
    environment_id=environment.id,
)
```

------------------------------------------------------------------------

## Step 6 --- Send user event

``` python
client.beta.sessions.events.send(
    session.id,
    events=[
        {
            "type": "user.message",
            "content": [
                {
                    "type": "text",
                    "text": "Inspect the repository and fix the failing tests.",
                }
            ],
        }
    ],
)
```

------------------------------------------------------------------------

## Step 7 --- Stream events

``` python
with client.beta.sessions.events.stream(session.id) as stream:
    for event in stream:
        print(event)
```

Your application can inspect event types and render them.

------------------------------------------------------------------------

# 95. Minimal conceptual implementation

``` python
from anthropic import Anthropic

client = Anthropic()

# 1. Agent
agent = client.beta.agents.create(
    name="Coding Agent",
    model="claude-opus-5",
    tools=[
        {
            "type": "agent_toolset_20260401",
        }
    ],
    system="""
    You are a senior software engineer.
    Inspect before changing files.
    Run tests after modifications.
    """,
)

# 2. Environment
environment = client.beta.environments.create(
    name="coding-env",
    config={
        "type": "cloud",
        "networking": {
            "type": "unrestricted",
        },
    },
)

# 3. Session
session = client.beta.sessions.create(
    agent=agent.id,
    environment_id=environment.id,
)

# 4. Work
with client.beta.sessions.events.stream(session.id) as stream:
    client.beta.sessions.events.send(
        session.id,
        events=[
            {
                "type": "user.message",
                "content": [
                    {
                        "type": "text",
                        "text": "Create a Python script that generates Fibonacci numbers.",
                    }
                ],
            }
        ],
    )

    for event in stream:
        print(event)
```

> Treat this as an architectural example. Exact SDK signatures can
> evolve during beta.

------------------------------------------------------------------------

# 96. What happens after the API call

The important part is not the Python code.

The important architecture is:

``` text
Your Python application
        |
        | create session
        v
Anthropic
        |
        | create runtime/session
        v
Environment
        |
        | task event
        v
Claude
        |
        | tool request
        v
Harness
        |
        | execute
        v
Sandbox
        |
        | result
        v
Harness
        |
        v
Claude
        |
        | next tool request
        v
...
```

That loop continues until Claude has completed the task or the session
is stopped/paused for a reason such as permissions or budget.

------------------------------------------------------------------------

# 97. What makes it "autonomous"

Autonomy does not mean:

``` text
Claude does anything it wants.
```

It means:

``` text
Given a goal + capabilities + permissions,
the agent chooses the sequence of actions
needed to work toward the goal.
```

The boundaries are:

``` text
Goal
  +
System prompt
  +
Tools
  +
Permissions
  +
Environment
  +
Credentials
```

The model operates inside those boundaries.

------------------------------------------------------------------------

# 98. Capability security model

An agent's effective capabilities can be represented as:

``` text
Effective capability
=
Enabled tools
∩
Permission policy
∩
Environment access
∩
Network policy
∩
Credentials
∩
MCP capabilities
```

For example:

``` text
Bash enabled
+
permission = always_ask
+
worker can reach Kubernetes
+
service account has get/list
=
diagnostic Kubernetes capability
```

But:

``` text
Bash enabled
+
worker cannot reach Kubernetes
=
no Kubernetes capability
```

The tool definition alone does not grant access to everything.

------------------------------------------------------------------------

# 99. Recommended architecture for your own agent harness project

If you are studying Managed Agents to build your own harness, the
architecture to replicate conceptually is:

``` text
                Agent Controller
                       |
             +---------+---------+
             |                   |
          Session             Agent Registry
             |                   |
             v                   v
        Event Store          Agent Versions
             |
             v
        Agent Runner
             |
       +-----+-----+
       |           |
   Model API    Tool Router
                   |
          +--------+--------+
          |        |       |
        Bash     Files     MCP
          |
          v
       Sandbox
```

Add:

``` text
Permission Engine
Budget Manager
Context Manager
Scheduler
Webhook Dispatcher
Memory Store
Observability
Secret Manager
```

This is the conceptual architecture behind a serious managed-agent
platform.

------------------------------------------------------------------------

# 100. If you were implementing the harness yourself

A minimum implementation would require:

``` text
1. Agent registry
2. Agent versioning
3. Session registry
4. Event store
5. Model adapter
6. Tool registry
7. Tool executor
8. Sandbox
9. Permission engine
10. Streaming transport
11. Context manager
12. Interrupt mechanism
13. Persistence
14. Retry mechanism
15. Cost/budget tracking
```

Advanced implementation:

``` text
16. MCP
17. Skills
18. Memory
19. Multi-agent delegation
20. Advisor
21. Scheduling
22. Webhooks
23. Secrets/vault
24. GitHub integration
25. Self-hosted workers
26. Data residency
27. Outcome tracking
28. Large-output spilling
29. Audit logs
30. policy engine
```

This explains why building a production-grade agent harness is much more
work than simply calling an LLM.

------------------------------------------------------------------------

# 101. Managed Agents architecture in one diagram

``` text
                              USER
                                |
                                v
                     +----------------------+
                     | Your Application     |
                     | Web/API/Slack/CLI    |
                     +----------+-----------+
                                |
                                | API / SDK
                                v
              +---------------------------------------+
              |       ANTHROPIC CONTROL PLANE         |
              |                                       |
              |  Agent Registry                       |
              |  Agent Versions                       |
              |  Session Manager                      |
              |  Event Store                          |
              |  Agent Harness                        |
              |  Permission Engine                    |
              |  Claude Inference                     |
              |  Scheduler / Deployments              |
              |  Webhooks                             |
              |  Memory / Skills                      |
              +-------------------+-------------------+
                                  |
                         Tool execution
                                  |
                    +-------------+-------------+
                    |                           |
                    v                           v
          ANTHROPIC CLOUD SANDBOX       SELF-HOSTED WORKER
                    |                           |
          +---------+---------+        +--------+--------+
          |         |         |        |        |       |
        Files     Bash      Web      Files    Bash   Network
          |         |         |        |        |       |
          +---------+---------+        +--------+-------+
                    |                           |
                    +-------------+-------------+
                                  |
                                  v
                            TOOL RESULTS
                                  |
                                  v
                              CLAUDE
                                  |
                           next action
                                  |
                                  v
                              repeat
```

------------------------------------------------------------------------

# 102. Practical decision guide

Use **Messages API** when:

``` text
You need:
- custom agent loop
- custom state model
- custom orchestration
- very specific execution semantics
- maximum control
```

Use **Managed Agents** when:

``` text
You need:
- autonomous execution
- long-running work
- persistent sessions
- built-in sandbox
- built-in tools
- event streaming
- scheduled runs
- self-hosted execution
- lower infrastructure burden
```

Use **self-hosted Managed Agents** when:

``` text
You need:
- private network access
- internal services
- execution inside your infrastructure
- organization-controlled runtime
- custom compliance controls
```

------------------------------------------------------------------------

# 103. Current limitations / things to verify before production

Because the feature is beta, verify current documentation for:

-   supported models
-   exact SDK method names
-   session limits
-   rate limits
-   maximum execution duration
-   sandbox resource limits
-   network behavior
-   data retention
-   self-hosted worker requirements
-   MCP availability
-   memory behavior
-   scheduling limits
-   pricing
-   region/data residency
-   supported cloud platforms

Do not treat examples in this document as a permanent API contract.

------------------------------------------------------------------------

# 104. Key takeaways

## Takeaway 1

Managed Agents is not merely a different endpoint for Claude.

It is a **managed runtime architecture**.

## Takeaway 2

The central object model is:

``` text
Agent
Environment
Session
Events
```

## Takeaway 3

The agent is reusable and versioned.

``` text
Agent definition
     |
     +--> Session A
     +--> Session B
     +--> Session C
```

## Takeaway 4

The session is stateful.

``` text
conversation + filesystem + outputs + events
```

## Takeaway 5

The agent loop is managed.

``` text
reason -> tool -> result -> reason -> tool -> ...
```

## Takeaway 6

Tools are capabilities.

``` text
Bash
Files
Web
MCP
Custom tools
```

## Takeaway 7

Permissions are a separate security layer.

``` text
enabled != automatically trusted
```

## Takeaway 8

The environment determines where execution happens.

``` text
cloud
or
self-hosted
```

## Takeaway 9

Self-hosting moves execution into your infrastructure but does not move
Claude's orchestration/model control plane into your infrastructure.

## Takeaway 10

Managed Agents can be extended with:

``` text
Skills
Memory
MCP
Multi-agent orchestration
Advisor
Scheduled deployments
Webhooks
Vaults
Outcomes
Budgets
```

------------------------------------------------------------------------

# 105. Official sources

Primary documentation:

-   Claude Managed Agents overview:
    https://platform.claude.com/docs/en/managed-agents/overview

-   Managed Agents quickstart:
    https://platform.claude.com/docs/en/managed-agents/quickstart

-   Agent setup:
    https://platform.claude.com/docs/en/managed-agents/agent-setup

-   Sessions:
    https://platform.claude.com/docs/en/managed-agents/sessions

-   Tools: https://platform.claude.com/docs/en/managed-agents/tools

-   Permission policies:
    https://platform.claude.com/docs/en/managed-agents/permission-policies

-   Self-hosted sandboxes:
    https://platform.claude.com/docs/en/managed-agents/self-hosted-sandboxes

-   Multi-agent orchestration:
    https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration

-   Memory: https://platform.claude.com/docs/en/managed-agents/memory

-   Scheduled deployments:
    https://platform.claude.com/docs/en/managed-agents/scheduled-deployments

-   Managed Agents reference:
    https://platform.claude.com/docs/en/managed-agents/reference

-   Supplied YouTube video: https://youtu.be/19HDQ9HppOA

------------------------------------------------------------------------

# 106. Final mental model

If you remember only one diagram, remember this:

``` text
                         YOUR APP
                            |
                            v
                         SESSION
                            |
                            v
                          AGENT
          +-----------------+------------------+
          |                 |                  |
        MODEL             TOOLS              SKILLS
          |                 |                  |
          |          +------+------+           |
          |          |      |      |           |
          |        Bash   Files    Web         |
          |                 |                  |
          |                MCP                 |
          |                 |                  |
          +-----------------+------------------+
                            |
                            v
                       AGENT LOOP
                            |
                  +---------+---------+
                  |                   |
               REASON              ACT
                  |                   |
                  +---------+---------+
                            |
                            v
                       TOOL RESULT
                            |
                            v
                         REASON
                            |
                         repeat
                            |
                            v
                          DONE
```

The core idea is therefore:

> **Claude Managed Agents turns Claude from a model you call into a
> managed, stateful, tool-using execution system that can autonomously
> work through a task inside a controlled environment.**

That is the architectural difference that matters most.
