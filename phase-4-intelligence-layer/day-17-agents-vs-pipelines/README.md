# Day 17 — Agents over Data Systems

> **Phase 4 — Intelligence Layer**
> An agent is not a smarter pipeline. It's a different architectural pattern with different tradeoffs. Knowing when to use each is the skill.

---

## Introduction

"Agent" has become one of the most overloaded words in AI systems. Every demo shows an agent autonomously solving complex problems. Every blog post says agents will replace pipelines.

The reality is more nuanced. Agents are powerful for specific problems. They are overkill — and often worse — for most data engineering tasks. The question is not "should I use an agent?" but "does this problem require adaptive decision-making, or is a deterministic pipeline sufficient?"

This day answers that question with concrete architectural guidance.

---

## What is an Agent?

An agent is a system where an LLM acts as a **decision-making controller** that:
1. Receives a goal or task
2. Decides which tools to call and in what order
3. Observes the results of each tool call
4. Decides what to do next based on those results
5. Repeats until the goal is achieved or a stopping condition is met

The key distinction: **the LLM controls the execution flow**. In a pipeline, the execution flow is hardcoded. In an agent, the LLM decides it at runtime.

### Decision-Making Layer
The LLM receives the current state (task + tool results so far) and outputs either:
- A tool call: `{"tool": "query_pinot", "args": {"sql": "SELECT..."}}`
- A final answer: `{"answer": "User u_4821 is at risk because..."}`

### Tool Orchestration
Tools are functions the agent can call. Each tool has:
- A name and description (so the LLM knows when to use it)
- An input schema (what arguments it accepts)
- An output format (what it returns)

```python
tools = [
    {"name": "query_pinot",    "description": "Run SQL against real-time analytics"},
    {"name": "search_vectors", "description": "Semantic search over event history"},
    {"name": "get_user_profile","description": "Fetch user profile from feature store"},
    {"name": "send_alert",     "description": "Send alert to support team"},
]
```

### Adaptive Workflows
The agent's execution path is not predetermined. For the same task, it might:
- Call `query_pinot` first, find no errors, then call `search_vectors` for context
- Or call `search_vectors` first, find a support ticket, then call `query_pinot` for metrics
- Or call `get_user_profile` first, see the user is enterprise, and skip the churn analysis entirely

This adaptability is the agent's superpower — and its main source of complexity.

---

## Pipelines vs Agents

### Pipelines

A pipeline is a **deterministic, ordered sequence of steps**. The execution path is fixed at design time.

```
Step 1: Parse query
Step 2: Query Pinot (always)
Step 3: Search vectors (always)
Step 4: Filter context
Step 5: Call LLM
Step 6: Return response
```

**Properties:**
- **Deterministic** — same input always produces the same execution path
- **Reliable** — easy to test, monitor, and debug
- **Predictable** — latency and cost are bounded and known
- **Fast** — no LLM overhead for orchestration decisions
- **Auditable** — every step is logged and traceable

**Best for:** Well-defined, repeatable tasks where the execution path doesn't need to change based on intermediate results.

### Agents

An agent is an **adaptive, LLM-driven workflow** where the execution path is decided at runtime.

```
Step 1: LLM receives task
Step 2: LLM decides → call tool A
Step 3: LLM observes result → decides → call tool B or C
Step 4: LLM observes result → decides → call tool D or answer
Step 5: LLM generates final response
```

**Properties:**
- **Adaptive** — execution path changes based on intermediate results
- **Dynamic** — can handle tasks that weren't anticipated at design time
- **Reasoning-driven** — the LLM reasons about what to do next
- **Slower** — multiple LLM calls for orchestration
- **Harder to debug** — non-deterministic execution paths
- **More expensive** — each orchestration step costs tokens

---

## When NOT to Use Agents

### Simple, Fixed Workflows
```
❌ Agent: "Retrieve user metrics and generate a summary"
✅ Pipeline: query_pinot → format_context → call_llm → return

The execution path never changes. An agent adds LLM overhead
for orchestration decisions that don't need to be made dynamically.
```

### Fixed Retrieval
```
❌ Agent: "Always search Pinot and Vector DB for every query"
✅ Pipeline: query_pinot + search_vectors (parallel) → merge → llm

If you always need both, hardcode it. Don't ask the LLM to decide.
```

### Deterministic Data Transformations
```
❌ Agent: "Transform this CSV into a structured format"
✅ Pipeline: parse → validate → transform → output

Transformation logic is deterministic. An agent adds no value
and introduces hallucination risk.
```

### High-Volume, Low-Latency Paths
```
❌ Agent: "Process 10,000 events per second with agent orchestration"
✅ Pipeline: Kafka → Flink → Pinot (no LLM in the hot path)

Agents are 100ms–2s per step. Pipelines are milliseconds.
Never put an agent in a high-throughput data path.
```

---

## When Agents Make Sense

### Root Cause Analysis
The investigation path depends on what you find:
```
Task: "Why did user u_4821 churn?"

Agent decides:
  Step 1: query_pinot("errors for u_4821") → 5 errors found
  Step 2: search_vectors("checkout errors u_4821") → finds support ticket
  Step 3: query_pinot("payment gateway status last 2h") → gateway was down
  Step 4: get_similar_cases("payment gateway churn") → 3 similar cases
  Step 5: generate_answer("Root cause: payment gateway outage...")

A pipeline would have hardcoded steps 1-4 regardless of what was found.
The agent skips irrelevant steps and adds relevant ones dynamically.
```

### Multi-Step Reasoning
When each step's output determines the next step:
```
Task: "Should we offer u_4821 a discount?"

Agent decides:
  Step 1: get_user_profile → plan=free, ltv=$0, churn_risk=high
  Step 2: query_pinot → 5 errors, intent_score=0.82
  Step 3: check_discount_eligibility → eligible (first-time offer)
  Step 4: calculate_discount_amount → 20% based on LTV potential
  Step 5: answer: "Yes, offer 20% discount. High intent, blocked by errors."

The discount calculation depends on eligibility, which depends on profile,
which depends on the initial assessment. Each step gates the next.
```

### Dynamic Tool Selection
When the right tool depends on the query type:
```
Task: "Analyze the checkout funnel this week"

Agent decides:
  → This is an analytical task, not a user-specific investigation
  → Skip get_user_profile (not relevant)
  → Call query_pinot with funnel aggregation query
  → Call search_vectors for qualitative context
  → Synthesize both

A pipeline would call all tools regardless. The agent selects only what's needed.
```

---

## Architecture Placement

Agents sit **above** your data infrastructure. They orchestrate calls to:

```
┌─────────────────────────────────────────────────────────────┐
│  AGENT (LLM controller)                                      │
│  Decides: which tools to call, in what order, when to stop  │
└──────────────────────────────────────────────────────────────┘
         │           │           │           │
         ▼           ▼           ▼           ▼
    [Pinot SQL]  [Vector DB]  [APIs]    [Feature Store]
    real-time    semantic     external   user profiles
    analytics    search       services
```

The agent does **not** replace these systems. It orchestrates them. The data infrastructure (Kafka, Flink, Pinot, Vector DB) remains unchanged. The agent is a new layer on top.

**Critical rule:** Agents should never be in the hot data path. They belong in the **query/reasoning layer**, not the ingestion or processing layer.

---

## Challenges of Agents

### Hallucinated Actions
The LLM may decide to call a tool with incorrect arguments, or call a tool that doesn't exist.

**Mitigation:** Validate tool calls before execution. Use structured output (JSON mode) for tool selection. Implement a tool call validator.

### Retry Complexity
When a tool call fails, the agent must decide whether to retry, try a different tool, or give up. This logic is non-trivial.

**Mitigation:** Implement explicit retry policies per tool. Set maximum step limits. Define fallback behaviors.

### Tool Reliability
The agent's output is only as reliable as its tools. A flaky Pinot query or a slow vector search degrades the entire agent.

**Mitigation:** Implement timeouts per tool. Cache tool results where appropriate. Monitor tool call success rates.

### Latency
Each agent step involves an LLM call (~200–500ms) plus the tool execution. A 5-step agent takes 1–3 seconds minimum.

**Mitigation:** Parallelize independent tool calls. Cache results. Set hard step limits. Use faster models for orchestration.

### Memory and State Management
The agent's context window grows with each step. Long conversations hit token limits.

**Mitigation:** Summarize intermediate results. Keep tool outputs concise. Implement sliding window memory for long tasks.

---

## Real-World Example — Root Cause Investigation

**Task:** *"User u_4821 just churned. What happened and what should we do?"*

### Pipeline Approach (fixed)
```
Step 1: query_pinot(user_id=u_4821, time=7d)
Step 2: search_vectors(query="u_4821 behavior", top_k=4)
Step 3: format_context(structured + semantic)
Step 4: call_llm(context + task)
Step 5: return response

Always 4 steps. Always the same tools. Always the same order.
Works well for standard churn queries. Misses nuance.
```

### Agent Approach (adaptive)
```
Step 1: LLM → call query_pinot(user_id=u_4821, time=2h)
         Result: 5 errors, error_rate=0.80, churn_risk=TRUE

Step 2: LLM → call search_vectors("checkout errors u_4821")
         Result: "payment gateway timeout", "checkout failing"

Step 3: LLM → call query_pinot("payment gateway errors last 2h")
         Result: 847 errors across 23 users — gateway was down

Step 4: LLM → call get_similar_cases("payment gateway outage churn")
         Result: 3 similar cases, all recovered with proactive outreach

Step 5: LLM → generate_answer
         "Root cause: payment gateway outage (not user-specific).
          23 users affected. Historical pattern: proactive outreach
          recovers 80% of affected users. Recommend: immediate
          outreach to all 23 users with apology + discount offer."
```

The agent discovered the gateway outage by dynamically querying for it — something the pipeline would never do because it wasn't hardcoded. This is the agent's value: **discovering the right questions to ask based on what it finds**.

---

## Common Mistakes

### 1. Agentizing Everything
```
❌ Use an agent for every query, including simple lookups
✅ Use pipelines for well-defined, repeatable tasks
   Use agents only when the execution path genuinely needs to adapt
```

### 2. Replacing Pipelines Unnecessarily
```
❌ "Agents are more powerful, so let's replace our Flink pipeline"
✅ Agents and pipelines serve different purposes
   Flink processes millions of events/second. An agent cannot.
   Keep your data infrastructure. Add agents on top.
```

### 3. Ignoring Reliability
```
❌ Deploy an agent without retry logic, timeouts, or fallbacks
✅ Treat agent tool calls like external API calls:
   - Timeout after N seconds
   - Retry with backoff
   - Fall back to pipeline if agent fails
```

### 4. No Step Limits
```
❌ Allow the agent to run indefinitely
✅ Set a maximum step count (e.g., 8 steps)
   An agent that loops forever is a production incident.
```

### 5. Putting Agents in the Hot Path
```
❌ Use an agent to process every incoming Kafka event
✅ Agents belong in the query/reasoning layer
   Data processing belongs in Flink/Spark pipelines
```

---

## Key Takeaways

1. **Agents are not better pipelines.** They're a different pattern for a different class of problems. Most data engineering tasks don't need agents.

2. **Use pipelines when the execution path is known.** Deterministic, reliable, fast, cheap. The right default.

3. **Use agents when the execution path depends on intermediate results.** Root cause analysis, multi-step reasoning, dynamic tool selection.

4. **Agents sit above your data infrastructure.** They orchestrate Pinot, Vector DB, and APIs. They don't replace them.

5. **Agent reliability requires explicit engineering.** Timeouts, retries, step limits, output validation. Don't assume the LLM will always do the right thing.

6. **Latency is the agent's biggest constraint.** Each step adds 200–500ms. Design for this. Parallelize where possible. Cache aggressively.

---

## What's Next

**Day 18** — Agent Tooling: designing tools that agents can call reliably, safely, and efficiently.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
