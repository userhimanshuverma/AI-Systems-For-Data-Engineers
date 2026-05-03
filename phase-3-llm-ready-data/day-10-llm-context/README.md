# Day 10 — What LLMs Actually Need (Not Your Tables)

> **Phase 3 — Making Data LLM-Ready**
> The biggest mistake data engineers make when building AI systems is treating the LLM like a database query engine. It isn't. It's a text completion machine. Feed it text. Get text back.

---

## Introduction

You've built the pipeline. Events flow through Kafka. Flink enriches them. Pinot stores them. The data is fresh, structured, and queryable.

Now you pass a Pinot query result to an LLM and ask: *"Why is user u_4821 at risk of churning?"*

The LLM returns something vague. Or wrong. Or it hallucinates numbers.

The pipeline isn't the problem. The **interface between your data and the LLM** is the problem.

LLMs don't consume tables. They consume text. The job of a data engineer in an AI system is not just to store data — it's to **transform data into the form an LLM can reason over**. That transformation is called **context engineering**.

---

## Why Tables Don't Work for LLMs

### Structure Mismatch

A database table is optimized for machines: rows, columns, types, indexes. Every cell is a discrete value. Relationships are expressed through joins. Meaning is encoded in schema design.

An LLM processes tokens sequentially. It has no concept of "column" or "row." When you pass a table to an LLM, it sees a flat sequence of characters — and it has to infer the structure from the formatting.

```
What you think you're passing:
┌──────────┬────────────┬──────────┬────────────┐
│ user_id  │ error_count│ plan     │ churn_risk │
├──────────┼────────────┼──────────┼────────────┤
│ u_4821   │ 5          │ free     │ true       │
└──────────┴────────────┴──────────┴────────────┘

What the LLM actually sees:
"user_id,error_count,plan,churn_risk\nu_4821,5,free,true"
```

The LLM can parse this. But it's working harder than it needs to, and the signal-to-noise ratio is low. Column names like `error_count` and `churn_risk` are meaningful to a developer but not to a language model reasoning about user behavior.

### Lack of Semantic Meaning

A table row tells you *what* the values are. It doesn't tell you *what they mean* in context.

```
error_count = 5
```

Does this mean:
- 5 errors in the last 10 seconds (critical)?
- 5 errors in the last 7 days (moderate)?
- 5 errors out of 5 total events (100% error rate, critical)?
- 5 errors out of 500 total events (1% error rate, normal)?

The number alone is meaningless without context. A table row doesn't carry that context. A well-constructed text description does.

### Token Inefficiency

Every token the LLM processes costs time and money. A table with 20 columns and 50 rows might use 2,000 tokens to convey information that could be expressed in 200 tokens of well-structured text. You're paying 10x for worse results.

---

## How LLMs Actually Work (Simple)

### Tokens

LLMs don't read words — they read **tokens**. A token is roughly 3–4 characters or 0.75 words. The sentence "User u_4821 has 5 errors" is approximately 8 tokens.

Tokens matter because:
- Every model has a **context window limit** (the maximum tokens it can process at once)
- Longer inputs cost more (API pricing is per token)
- More tokens = more processing time = higher latency

### Context Window

The context window is the LLM's working memory. Everything the model can "see" when generating a response must fit within this window.

```
Context window = system prompt + retrieved context + user query + response space

GPT-4o:       128,000 tokens  (~96,000 words)
Claude 3.5:   200,000 tokens  (~150,000 words)
GPT-4o-mini:  128,000 tokens  (~96,000 words)
```

Large context windows don't mean you should fill them. Research consistently shows that LLM performance degrades with irrelevant context — the model gets confused by noise. **Precision beats volume.**

### Sequential Understanding

LLMs process tokens left to right. They build up a representation of meaning as they read. This means:
- **Order matters** — put the most important context first
- **Recency matters** — information near the end of the prompt has more influence on the response
- **Repetition helps** — key facts mentioned multiple times are weighted more heavily

---

## What LLMs Actually Need

### 1. Context (Not Data)

The LLM needs to understand the *situation*, not just the *values*. Context means:
- Who is this user?
- What have they been doing?
- What is the current state?
- What is the question being asked?

### 2. Natural Language Representation

Convert structured data to natural language before passing it to the LLM. Not because the LLM can't parse JSON — it can — but because natural language is what the model was trained on. It reasons better over text that resembles its training data.

```
❌ {"user_id": "u_4821", "error_count": 5, "churn_risk": true}

✅ "User u_4821 (free plan, US, at_risk segment) has experienced 5 checkout
   errors in the last session, representing a 50% error rate. They visited
   the /pricing page 3 times without converting. Churn risk is HIGH."
```

### 3. Relevant Information Only

The LLM doesn't need your entire database. It needs the specific facts relevant to the question being asked. Passing irrelevant data:
- Wastes tokens
- Increases latency and cost
- Degrades response quality (the model gets distracted by irrelevant signals)

### 4. Structured Output Instructions

Tell the LLM exactly what format you want back. If you need JSON, say so. If you need a specific schema, provide it. LLMs are much more reliable when given explicit output format instructions.

```
System prompt: "Respond in JSON with keys: summary, action, confidence (0-1), evidence (list)"
```

---

## Context Engineering (Core Section)

Context engineering is the practice of **transforming raw data into the optimal input for an LLM**. It has three steps:

### Step 1 — Select Relevant Signals

Not all data is relevant to every query. A query about checkout errors doesn't need the user's signup date. A query about upgrade intent doesn't need error codes.

```python
# Query: "Why is this user at risk of churning?"
# Relevant signals:
relevant = {
    "error_count":    5,      # ← directly relevant
    "error_rate":     0.50,   # ← directly relevant
    "churn_risk":     True,   # ← directly relevant
    "pricing_visits": 3,      # ← relevant (intent signal)
    "plan":           "free", # ← relevant (context)
}

# Not relevant for this query:
irrelevant = {
    "signup_date":    "2025-11-01",  # ← not relevant
    "country":        "US",          # ← not relevant for churn
    "session_id":     "sess_9x8y",   # ← internal ID, not useful
    "event_id":       "evt_a1b2",    # ← internal ID, not useful
}
```

### Step 2 — Transform to Natural Language

Convert the selected signals into a coherent text description. This is the most important step.

```python
def build_context(user_id, metrics, events):
    lines = []

    # User identity and state
    lines.append(
        f"User {user_id} is on the {metrics['plan']} plan "
        f"({metrics['segment']} segment, {metrics['country']})."
    )

    # Behavioral signals
    lines.append(
        f"In the current session: {metrics['session_events']} events, "
        f"{metrics['error_count']} errors ({metrics['error_rate']:.0%} error rate)."
    )

    # Intent signals
    if metrics['pricing_visits'] > 0:
        lines.append(
            f"Visited /pricing {metrics['pricing_visits']} times "
            f"without converting (upgrade intent score: {metrics['intent_score']:.2f})."
        )

    # Risk signals
    if metrics['churn_risk']:
        lines.append("Churn risk flag is TRUE based on error rate and plan tier.")

    # Recent events (most relevant first)
    for event in events[:3]:
        lines.append(f"- {event}")

    return "\n".join(lines)
```

### Step 3 — Structure the Prompt

Assemble the context into a well-structured prompt with clear sections:

```
[SYSTEM PROMPT]
You are a data analyst assistant. Answer questions about user behavior
using ONLY the provided context. Do not invent data. Be specific and cite evidence.
Respond in JSON: {"summary": str, "action": str, "confidence": float, "evidence": list}

[CONTEXT]
User u_4821 is on the free plan (at_risk segment, US).
In the current session: 10 events, 5 errors (50% error rate).
Visited /pricing 3 times without converting (upgrade intent score: 0.82).
Churn risk flag is TRUE based on error rate and plan tier.
- User hit 500 error on /checkout at 14:32
- User hit 500 error on /checkout at 14:35
- User clicked "Upgrade to Pro" on /pricing at 14:38

[QUESTION]
Why is this user at risk of churning?
```

---

## Before vs After Example

### Before — Raw Table Input

```
Input to LLM:
user_id,event_type,ts,page,error_code,plan,segment,error_rate,churn_risk
u_4821,system.server_error,2026-04-27T14:32:01Z,/checkout,500,free,at_risk,0.5,true
u_4821,system.server_error,2026-04-27T14:35:22Z,/checkout,500,free,at_risk,0.5,true
u_4821,ui.button_click,2026-04-27T14:38:01Z,/pricing,,free,at_risk,0.5,true

LLM Response:
"The user u_4821 has experienced server errors on the checkout page and
has clicked a button on the pricing page. The churn_risk field is true."
```

Technically correct. Completely useless. No synthesis, no recommendation, no insight.

### After — Context-Engineered Input

```
Input to LLM:
User u_4821 (free plan, at_risk segment) has experienced 5 checkout errors
(50% error rate) in the current session. They visited /pricing 3 times and
clicked "Upgrade to Pro" — showing strong upgrade intent (score: 0.82).
Despite the intent, checkout failures are blocking conversion.
Churn risk is HIGH. Last 3 events:
- 500 error on /checkout at 14:32
- 500 error on /checkout at 14:35
- Clicked "Upgrade to Pro" on /pricing at 14:38

LLM Response:
{
  "summary": "User u_4821 is at high churn risk due to repeated checkout
              failures blocking a clear upgrade intent. They attempted to
              upgrade 3 times but hit 500 errors each time.",
  "action": "escalate_checkout_fix",
  "confidence": 0.94,
  "evidence": [
    "5 checkout errors in current session (50% error rate)",
    "3 visits to /pricing with upgrade intent score 0.82",
    "Clicked 'Upgrade to Pro' after each error — intent is clear"
  ]
}
```

Same data. Completely different output quality. The difference is context engineering.

---

## Real-World Example — User Behavior to Natural Language

**System:** SaaS support assistant. Support agent asks: *"What's going on with user u_4821?"*

### Data Available (from Pinot + Vector Store)

**Pinot query result:**
```json
{
  "user_id": "u_4821",
  "plan": "free",
  "segment": "at_risk",
  "session_errors": 5,
  "error_rate": 0.50,
  "pricing_visits": 3,
  "intent_score": 0.82,
  "churn_risk": true,
  "last_active": "2 minutes ago"
}
```

**Vector store retrieval (top-3 semantic matches):**
```
1. "User u_4821 hit 500 error on /checkout at 14:32"
2. "User u_4821 clicked 'Upgrade to Pro' on /pricing at 14:38"
3. "User u_4821 submitted support ticket: 'checkout keeps failing'"
```

### Context Builder Output

```
User u_4821 is on the free plan (at_risk segment). Last active 2 minutes ago.

Session summary: 10 events, 5 errors (50% error rate).
Visited /pricing 3 times. Upgrade intent score: 0.82 (HIGH).
Churn risk: TRUE.

Recent activity:
- 500 error on /checkout at 14:32 UTC
- Clicked "Upgrade to Pro" on /pricing at 14:38 UTC
- Submitted support ticket: "checkout keeps failing"
```

### LLM Response

```json
{
  "summary": "User u_4821 is actively trying to upgrade but is blocked by
              repeated checkout errors. They've hit 5 errors in this session
              and submitted a support ticket. High churn risk if not resolved.",
  "action": "escalate_to_engineering",
  "confidence": 0.96,
  "evidence": [
    "5 checkout errors (50% error rate) in current session",
    "3 visits to /pricing — clear upgrade intent",
    "Support ticket submitted about checkout failures",
    "Upgrade intent score: 0.82 — user wants to convert"
  ]
}
```

---

## Where This Fits in Architecture

```
Kafka → Flink → Pinot ──────────────────────────────────┐
                                                         │
                Vector Store ────────────────────────────┤
                                                         ▼
                                              [Context Builder]
                                              ├── Select signals
                                              ├── Transform to text
                                              └── Structure prompt
                                                         │
                                                         ▼
                                                      [LLM]
                                              ├── Receives: context + query
                                              ├── Returns: JSON response
                                              └── Grounded in retrieved data
```

The Context Builder is the bridge between your data infrastructure and the LLM. It is not a trivial component — it is where the quality of your AI system is determined.

---

## Common Mistakes

### 1. Passing Full Datasets
```
❌ SELECT * FROM user_events WHERE user_id = 'u_4821' → dump to LLM
✅ SELECT the 5-10 most relevant metrics → transform to text → pass to LLM
```
A full dataset has hundreds of rows. The LLM doesn't need all of them. It needs the most relevant signals for the specific question.

### 2. Ignoring Token Limits
```
❌ Pass 50 events as raw JSON (2,000+ tokens)
✅ Pass top-3 most relevant events as natural language (150 tokens)
```
Token limits are real. Even with large context windows, more tokens = more cost + more latency + worse quality.

### 3. No Context Selection
```
❌ Pass all available fields regardless of the query
✅ Select fields relevant to the specific question being asked
```
A query about churn doesn't need the user's device type. A query about mobile errors does. Context selection is query-dependent.

### 4. No Output Format Specification
```
❌ "Tell me about this user" → free-form text response
✅ "Respond in JSON with keys: summary, action, confidence, evidence"
```
Without output format instructions, LLM responses are inconsistent and hard to parse programmatically.

### 5. Treating LLM as a Calculator
```
❌ "What is the average error rate across all users?" → LLM
✅ Compute in Pinot: SELECT AVG(error_rate) FROM user_events
   Then pass the result to LLM for interpretation if needed
```
LLMs are not reliable for arithmetic. Always compute numbers in your data layer. Pass results to the LLM for reasoning and synthesis.

---

## Key Takeaways

1. **LLMs consume text, not tables.** The interface between your data and the LLM is a text transformation problem, not a query problem.

2. **Context engineering is the most important skill in AI data systems.** The quality of your LLM responses is determined by the quality of your context, not the quality of your model.

3. **Select before you transform.** Only pass signals relevant to the specific question. Irrelevant context degrades LLM output quality.

4. **Natural language beats raw JSON.** The LLM was trained on text. It reasons better over text that resembles its training data.

5. **Specify output format explicitly.** JSON mode, structured outputs, or explicit format instructions make LLM responses reliable and parseable.

6. **Never ask the LLM to compute.** Compute in Pinot/SQL. Pass results to the LLM for interpretation. LLMs hallucinate numbers.

---

## What's Next

**Day 11** — Embedding Pipelines: converting text context into dense vectors for semantic retrieval.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
