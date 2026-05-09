# Day 16 — Query Understanding Layer

> **Phase 4 — Intelligence Layer**
> A query is not a search string. It's a compressed expression of intent, context, and expectation. The query understanding layer decompresses it before any retrieval happens.

---

## Introduction

On Day 15 we saw that production RAG systems need five layers. The first — and most important — is query understanding. Everything downstream depends on it.

When a support agent asks *"Why is u_4821 struggling?"*, the system needs to know:
- This is an error/churn investigation (not a general question)
- The scope is a single user (not all users)
- The time range is recent (not historical)
- It needs both structured metrics (Pinot) and behavioral context (Vector DB)
- Freshness is critical (< 5 seconds)

Without query understanding, every query gets the same treatment: embed → vector search → LLM. That works for demos. It fails in production.

---

## Why Raw Queries Are Ambiguous

Natural language is inherently ambiguous. The same surface-level query can mean completely different things depending on context.

### Natural Language Ambiguity

```
"Show me the errors"
  → Could mean: errors for a specific user? All users? Last hour? Last week?
  → Could mean: server errors? UI errors? Validation errors?
  → Without understanding: retrieves everything, returns noise

"Is this user at risk?"
  → Which user? Risk of what? Churn? Fraud? Downgrade?
  → Without understanding: generic vector search, vague answer

"What happened last week?"
  → What happened to whom? In which system? What kind of events?
  → Without understanding: retrieves random events from last week
```

### Hidden Intent

Users rarely state their full intent. They assume the system understands context:

```
Support agent: "What's going on with u_4821?"
Hidden intent: "I need to understand this user's recent behavior,
               identify any issues, and get a recommended action
               before I call them."

What the system needs to do:
  1. Retrieve recent errors (Pinot: last 2h)
  2. Retrieve behavioral context (Vector DB: top-4 events)
  3. Check churn risk flag (Pinot: current state)
  4. Synthesize into an actionable summary (LLM)
```

### Contextual Meaning

The same word means different things in different contexts:

```
"errors"  → in a churn query: behavioral signal
           → in a debugging query: specific error codes and stack traces
           → in a monitoring query: error rate over time

"recent"  → for fraud detection: last 60 seconds
           → for support tooling: last 2 hours
           → for weekly reports: last 7 days
```

---

## What is a Query Understanding Layer?

The query understanding layer sits between the user's raw query and the retrieval system. Its job is to transform an ambiguous natural language query into a precise retrieval plan.

### Responsibilities

#### 1. Intent Extraction
Classify the query into a known intent category. Each intent maps to a different retrieval strategy.

```
Intent categories:
  error_investigation  → user has errors, need details + context
  churn_analysis       → identify at-risk users, need metrics + patterns
  upgrade_analysis     → identify upgrade candidates, need intent signals
  retention_analysis   → engagement patterns, need session data
  general              → fallback, semantic search only
```

#### 2. Entity Extraction
Extract structured entities from the query text:

```
"Show me errors for u_4821 in the last 2 hours"
  → user_id:     "u_4821"
  → time_range:  2 hours
  → event_type:  errors

"Which free-plan users are at risk this week?"
  → user_id:     None (all users)
  → plan_filter: "free"
  → time_range:  7 days
  → risk_flag:   churn_risk=true
```

#### 3. Time/Context Understanding
Map natural language time references to precise time windows:

```
"just now"      → last 15 minutes
"recently"      → last 2 hours
"today"         → last 24 hours
"this week"     → last 7 days
"this month"    → last 30 days
"last quarter"  → last 90 days
```

#### 4. Retrieval Planning
Decide which retrieval systems to use and how:

```
For error_investigation:
  use_pinot:  True  (need exact error counts and rates)
  use_vector: True  (need behavioral context)
  freshness:  high  (need current state)
  top_k:      3     (focused, not broad)

For churn_analysis (all users):
  use_pinot:  True  (need to rank users by risk)
  use_vector: True  (need context per user)
  freshness:  medium
  top_k:      5     (broader scope)

For general:
  use_pinot:  False (no structured query needed)
  use_vector: True  (semantic search only)
  freshness:  low
  top_k:      3
```

---

## Query → System Action Transformation

### Example 1: Error Investigation

```
Raw query:    "Show me all errors for user u_4821 in the last 2 hours"

Parsed:
  intent:     error_investigation
  user_id:    u_4821
  time_range: 2 hours
  entities:   {event_type: "error"}

Retrieval plan:
  Pinot SQL:  SELECT * FROM user_events WHERE user_id='u_4821'
              AND event_type LIKE '%error%' AND ts > ago('2h')
  Vector:     embed("error failure crash u_4821") → top-3
  Freshness:  required (< 5s)
  Token budget: 200

LLM receives:
  [STRUCTURED] 3 errors in last 2h, error_rate=0.50, page=/checkout
  [SEMANTIC]   "hit 500 error on /checkout", "payment failed"
  [QUERY]      "Show me all errors for user u_4821 in the last 2 hours"
```

### Example 2: Churn Analysis

```
Raw query:    "Which free-plan users are most at risk this week?"

Parsed:
  intent:     churn_analysis
  user_id:    None (all users)
  time_range: 7 days
  plan:       free
  entities:   {churn_risk: true}

Retrieval plan:
  Pinot SQL:  SELECT user_id, error_rate, intent_score
              FROM user_events WHERE plan='free' AND churn_risk=true
              AND ts > ago('7d') ORDER BY error_rate DESC LIMIT 10
  Vector:     embed("churn risk behavior errors disengagement") → top-5
  Freshness:  medium (< 60s acceptable)
  Token budget: 400

LLM receives:
  [STRUCTURED] Top 10 at-risk users with metrics
  [SEMANTIC]   Behavioral patterns for top users
  [QUERY]      "Which free-plan users are most at risk this week?"
```

### Example 3: Upgrade Analysis

```
Raw query:    "Who is most likely to upgrade this month?"

Parsed:
  intent:     upgrade_analysis
  user_id:    None
  time_range: 30 days
  entities:   {intent_score: high}

Retrieval plan:
  Pinot SQL:  SELECT user_id, intent_score, pricing_visits
              FROM user_events WHERE plan='free' AND intent_score > 0.6
              AND ts > ago('30d') ORDER BY intent_score DESC LIMIT 10
  Vector:     embed("upgrade intent pricing page feature limit") → top-3
  Freshness:  low (daily batch acceptable)
  Token budget: 300
```

---

## Types of Query Intent

### Analytical
Questions about patterns, trends, and aggregations across users or time.
```
"What is the average error rate this week?"
"How many users churned last month?"
"Which pages have the most errors?"
```
→ Primarily Pinot (aggregations). Vector DB for context.

### Troubleshooting
Questions about specific issues for specific users or systems.
```
"Why is user u_4821 having checkout errors?"
"What's causing the spike in 500 errors?"
"Why did this user's session fail?"
```
→ Both Pinot (exact metrics) and Vector DB (behavioral context). High freshness.

### Recommendation
Questions asking for suggested actions or predictions.
```
"Which users should we reach out to today?"
"Who is most likely to upgrade?"
"What should we do about u_4821?"
```
→ Pinot for ranking. Vector DB for context. LLM for synthesis.

### Operational
Questions about system state and health.
```
"Is the checkout system working?"
"What's the current error rate?"
"Are there any active incidents?"
```
→ Primarily Pinot (real-time metrics). Very high freshness.

---

## Retrieval Planning

The retrieval plan is the output of query understanding. It tells the retrieval layer exactly what to fetch and how.

### Choosing Structured vs Semantic Retrieval

| Signal | Use Pinot | Use Vector DB |
|--------|-----------|---------------|
| Need exact counts | ✅ | ❌ |
| Need error rates | ✅ | ❌ |
| Need user ranking | ✅ | ❌ |
| Need behavioral narrative | ❌ | ✅ |
| Need similar past incidents | ❌ | ✅ |
| Need unstructured text | ❌ | ✅ |
| Need both facts + story | ✅ | ✅ |

### Deciding Freshness Needs

| Intent | Freshness SLA | Cache TTL |
|--------|--------------|-----------|
| error_investigation | < 5 seconds | None |
| churn_analysis | < 60 seconds | 30s |
| upgrade_analysis | < 1 hour | 30min |
| retention_analysis | < 24 hours | 6h |
| general | < 1 hour | 30min |

### Selecting Context Scope

```
Single user query:   top_k = 3-4 (focused)
Multi-user query:    top_k = 5-10 (broader, then filter)
Analytical query:    top_k = 3 (context only, Pinot does the work)
Operational query:   top_k = 2 (minimal context, speed matters)
```

---

## Real-World Example — Premium User Retention Analysis

**Query:** *"Which of our at-risk free-plan users showed upgrade intent this week but didn't convert?"*

### Query Understanding Output

```python
{
  "intent":     "churn_analysis",
  "user_id":    None,
  "time_range": 168,  # 7 days in hours
  "plan":       "free",
  "filters": {
    "churn_risk":   True,
    "intent_score": "> 0.5",  # showed upgrade intent
  },
  "retrieval_plan": {
    "use_pinot":  True,
    "use_vector": True,
    "pinot_query": """
      SELECT user_id, error_rate, intent_score, pricing_visits
      FROM user_events WHERE plan='free'
        AND churn_risk=true AND intent_score > 0.5
        AND ts > ago('7d')
      ORDER BY intent_score DESC LIMIT 10
    """,
    "vector_query": "upgrade intent pricing page checkout failure blocked conversion",
    "top_k":      5,
    "freshness":  "medium",
    "token_budget": 400,
  }
}
```

### Why This Matters

Without query understanding, this query would be treated as a generic vector search. The system would embed the full query string and return the top-5 semantically similar events — which might include completely irrelevant documents.

With query understanding, the system knows exactly what to fetch, from where, with what filters, and how fresh the data needs to be. The LLM receives a precisely assembled context and produces a specific, actionable response.

---

## Common Mistakes

### 1. Direct Query → LLM
```
❌ Pass raw query directly to LLM: "Which users are at risk?"
✅ Parse intent first → build retrieval plan → retrieve → assemble context → LLM
```
Without understanding, the LLM has no data to reason over. It will hallucinate.

### 2. No Intent Classification
```
❌ Treat all queries as semantic search queries
✅ Classify intent → route to appropriate retrieval strategy
   An error investigation needs different retrieval than a churn analysis
```

### 3. Retrieving Too Much Context
```
❌ Retrieve top-20 chunks for every query
✅ Use intent to determine top_k: error investigation → 3, churn analysis → 5
   More context is not always better. Irrelevant context degrades LLM quality.
```

### 4. Ignoring Time Context
```
❌ Always query the last 7 days regardless of query
✅ Extract time references: "last 2 hours" → 2h window, "this week" → 7d window
   Wrong time window = wrong data = wrong answer
```

### 5. No Retrieval Routing
```
❌ Always use both Pinot and Vector DB for every query
✅ Route based on intent: operational queries → Pinot only (speed)
   general queries → Vector DB only (no structured data needed)
```

---

## Key Takeaways

1. **Query understanding is the first layer of production RAG.** Everything downstream depends on correctly parsing the query.

2. **Intent classification determines retrieval strategy.** Different intents need different combinations of Pinot, Vector DB, freshness, and top_k.

3. **Entity extraction enables precise filtering.** User IDs, time ranges, plan filters — these turn broad queries into targeted retrievals.

4. **Time context is critical.** "Recently" means different things for fraud detection vs weekly reports. Always map to explicit time windows.

5. **Retrieval planning is the output.** The query understanding layer produces a retrieval plan, not a response. The plan drives everything else.

6. **Without query understanding, RAG is just expensive keyword search.** The intelligence is in the understanding, not the retrieval.

---

## What's Next

**Day 17** — Agents vs Pipelines: when to use a deterministic pipeline vs an LLM-driven agent.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
