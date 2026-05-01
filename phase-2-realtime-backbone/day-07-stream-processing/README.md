# Day 07 — Stream Processing (Enrichment Layer)

> **Phase 2 — Real-Time Data Backbone**
> Raw events are incomplete signals. Stream processing is where incomplete becomes actionable.

---

## Introduction

On Day 6 we designed rich event schemas. But even a well-designed event only contains what the application knew at the moment it fired. It doesn't know the user's purchase history. It doesn't know how many errors they've hit this session. It doesn't know their churn risk score.

Stream processing is the layer that adds this missing context — in real-time, before the event reaches any storage system.

This matters enormously for AI systems. The LLM reasoning layer can only work with what's in the retrieved context. If the stored events are raw and thin, the retrieval is weak and the LLM response is vague. If the stored events are enriched with behavioral context, the retrieval is precise and the LLM response is actionable.

Stream processing is the enrichment layer between Kafka and storage.

---

## The Problem with Raw Events

A raw event captures what happened. It does not capture:

- **Who the user is** — their plan, segment, country, lifetime value
- **What they've been doing** — session history, recent errors, pages visited
- **What patterns exist** — error rate this session, visit frequency, conversion signals
- **What risk signals are present** — churn indicators, fraud patterns, anomalies

Without enrichment, every downstream system — Pinot, the vector store, the LLM — must either join this data at query time (expensive, slow) or go without it (weak results).

### Raw Event — What Kafka Receives
```json
{
  "event_id":   "evt_a1b2",
  "event_type": "ui.button_click",
  "user_id":    "u_4821",
  "session_id": "sess_9x8y",
  "ts":         "2026-04-27T14:32:01Z",
  "context":    { "page": "/pricing", "element_id": "cta_upgrade" }
}
```

This is correct and well-structured. But it's missing everything the downstream AI system needs to reason about this user.

### Enriched Event — What Pinot and the Vector Store Receive
```json
{
  "event_id":   "evt_a1b2",
  "event_type": "ui.button_click",
  "user_id":    "u_4821",
  "session_id": "sess_9x8y",
  "ts":         "2026-04-27T14:32:01Z",
  "context":    { "page": "/pricing", "element_id": "cta_upgrade" },

  "user_profile": {
    "plan":              "free",
    "country":           "US",
    "segment":           "at_risk",
    "signup_days_ago":   45,
    "lifetime_orders":   0
  },
  "session_state": {
    "session_event_count":  8,
    "session_error_count":  2,
    "session_pages_visited": ["/home", "/pricing", "/checkout", "/pricing"],
    "pricing_page_visits":  3,
    "session_duration_s":   312
  },
  "derived_features": {
    "session_error_rate":     0.25,
    "is_repeat_pricing_visit": true,
    "upgrade_intent_score":   0.82,
    "churn_risk_flag":        true
  }
}
```

The enriched event tells a story. The raw event records a fact.

---

## What is Stream Processing?

Stream processing is the continuous transformation of events as they flow through the system — before they reach any storage layer.

Unlike batch processing (which runs on a schedule over a fixed dataset), stream processing runs **continuously** and operates on **each event as it arrives**.

The core operations:

| Operation | What it does | Example |
|-----------|-------------|---------|
| **Filter** | Drop events that don't meet criteria | Only process `ui.*` events |
| **Map / Transform** | Change the structure of an event | Rename fields, parse timestamps |
| **Enrich** | Add data from an external source | Join with user profile from Redis |
| **Aggregate** | Compute running totals or statistics | Count errors per user per session |
| **Window** | Group events by time | All events in the last 30 minutes |
| **Detect** | Identify patterns across events | 3+ errors in 5 minutes = alert |

In production, Apache Flink is the standard for stateful stream processing. It handles exactly-once semantics, fault tolerance via checkpointing, and scales horizontally across partitions.

---

## Types of Enrichment

### 1. Static Enrichment (Lookup Data)
Joins the event with data that changes infrequently — user profiles, product catalogs, geographic mappings.

**Source:** Redis, a feature store, or an in-memory lookup table
**Latency:** < 5ms (Redis GET)
**Example:**
```
Raw:      { user_id: "u_4821" }
Lookup:   Redis GET user:u_4821 → { plan: "free", country: "US", segment: "at_risk" }
Enriched: { user_id: "u_4821", plan: "free", country: "US", segment: "at_risk" }
```

**Why it matters for AI:** The LLM needs to know the user's plan and segment to give a relevant response. Without this, every user looks identical.

### 2. Behavioral Enrichment (Session State)
Maintains per-user or per-session state across events. Tracks what the user has been doing within the current session.

**Source:** Flink's in-memory state backend (RocksDB for large state)
**Latency:** < 1ms (in-process state lookup)
**Example:**
```
Event 1: user u_4821 views /home
Event 2: user u_4821 views /pricing  → session_pages: ["/home", "/pricing"]
Event 3: user u_4821 hits error      → session_errors: 1
Event 4: user u_4821 views /pricing  → pricing_visits: 2, session_pages: [..., "/pricing"]
Event 5: user u_4821 clicks upgrade  → pricing_visits: 3, upgrade_intent detected
```

**Why it matters for AI:** The sequence of events within a session is the most powerful signal for intent detection. A user who visited /pricing 3 times before clicking upgrade is very different from one who clicked it immediately.

### 3. Derived Features (Computed Signals)
Computes higher-level signals from the raw and behavioral data. These are features that no single event contains but emerge from patterns across events.

**Source:** Computed by the stream processor from accumulated state
**Examples:**
```
session_error_rate     = session_errors / session_event_count
upgrade_intent_score   = f(pricing_visits, plan, segment, session_duration)
churn_risk_flag        = session_error_rate > 0.3 AND plan == "free"
is_high_value_session  = lifetime_orders > 2 AND session_duration > 300s
```

**Why it matters for AI:** These derived features are the signals the LLM uses to make confident, specific statements. "Churn risk flag is true" is more actionable than "user hit some errors."

---

## Example Transformation — Before and After

### Input (Raw Event from Kafka)
```json
{
  "event_id":   "evt_c3d4",
  "event_type": "system.server_error",
  "user_id":    "u_4821",
  "session_id": "sess_9x8y",
  "ts":         "2026-04-27T14:35:22Z",
  "context":    { "page": "/checkout", "error_code": 500 }
}
```

### Processing Steps
```
1. Static enrichment:
   Redis GET user:u_4821
   → plan=free, country=US, segment=at_risk, lifetime_orders=0

2. Session state update:
   Flink state for sess_9x8y:
   → session_event_count: 9 → 10
   → session_error_count: 2 → 3
   → session_pages_visited: append "/checkout"

3. Derived feature computation:
   session_error_rate = 3/10 = 0.30
   churn_risk_flag = (0.30 >= 0.30) AND (plan == "free") → True
   upgrade_intent_score: no upgrade click yet → 0.41
```

### Output (Enriched Event to Pinot + Vector Store)
```json
{
  "event_id":   "evt_c3d4",
  "event_type": "system.server_error",
  "user_id":    "u_4821",
  "session_id": "sess_9x8y",
  "ts":         "2026-04-27T14:35:22Z",
  "context":    { "page": "/checkout", "error_code": 500 },
  "user_profile": {
    "plan": "free", "country": "US",
    "segment": "at_risk", "lifetime_orders": 0
  },
  "session_state": {
    "session_event_count": 10,
    "session_error_count": 3,
    "pricing_page_visits": 3,
    "session_duration_s":  501
  },
  "derived_features": {
    "session_error_rate":    0.30,
    "churn_risk_flag":       true,
    "upgrade_intent_score":  0.41
  }
}
```

**Embedding text produced:**
> "User u_4821 (free plan, US, at_risk) hit a 500 error on /checkout at 14:35. Session: 10 events, 3 errors (30% error rate), visited /pricing 3 times. Churn risk: TRUE. Upgrade intent score: 0.41."

This is what the LLM reasons over. The raw event would have produced:
> "User u_4821 hit an error at 14:35."

---

## Real-World Example — User Activity Pipeline

**System:** SaaS platform, 50K users, AI-powered support assistant.

### Pipeline
```
Web App → Kafka (user.events) → Flink Enrichment Job → Pinot + Vector Store → LLM
```

### Flink Job Structure
```
Source:    KafkaSource("user.events", partitions=12)
           │
           ▼
Filter:    Drop heartbeat and health-check events
           │
           ▼
KeyBy:     user_id (ensures all events for a user go to same operator)
           │
           ▼
Process:   EnrichmentOperator (per-key stateful processing)
           ├── Static enrichment: Redis lookup for user profile
           ├── Session state: update event count, error count, pages
           └── Derived features: compute error rate, intent score, flags
           │
           ▼
Sink 1:    KafkaSink("user.events.enriched") → Pinot connector
Sink 2:    KafkaSink("user.events.enriched") → Embedding pipeline
```

### What Each Downstream System Gets

**Pinot** receives enriched rows with 30+ columns. Support agents can query:
```sql
SELECT user_id, session_error_rate, churn_risk_flag, upgrade_intent_score
FROM user_events_enriched
WHERE churn_risk_flag = true AND ts > ago('1h')
ORDER BY session_error_rate DESC
LIMIT 20
```

**Vector Store** receives embedding text like:
> "User u_4821 (free, US, at_risk) hit 500 error on /checkout. 3 errors in session, 30% error rate, visited /pricing 3 times. Churn risk: TRUE."

**LLM** receives retrieved chunks and answers:
> "User u_4821 is at high churn risk. They've hit 3 checkout errors (30% error rate) and visited /pricing 3 times without converting. Recommend: immediate checkout fix escalation + targeted upgrade offer."

---

## Where Stream Processing Fits in the System

```
Day 5: Kafka          → events arrive
Day 6: Schema Design  → events are well-structured
Day 7: Stream Processing → events are enriched with context
Day 8: Pinot          → enriched events are queryable
Day 9: Latency        → freshness guarantees are defined
```

Stream processing is the transformation layer. It sits between raw event capture and queryable storage. Without it, storage systems receive incomplete data and the AI layer has nothing meaningful to reason over.

---

## Common Mistakes

### 1. Only Filtering, Not Enriching
```
❌ Use stream processing only to filter out noise
✅ Use it to add context: user profile, session state, derived features
```
Filtering is the simplest use of stream processing. Enrichment is where the value is.

### 2. Ignoring Session State
```
❌ Process each event independently, with no memory of previous events
✅ Maintain per-session state: event count, error count, pages visited
```
A single event has limited signal. The sequence of events within a session is where intent and risk patterns emerge.

### 3. Doing Enrichment at Query Time
```
❌ Store raw events, join with profile data when querying Pinot
✅ Enrich at ingest time — pay the cost once, benefit every query
```
Query-time joins are expensive and slow. Enrichment at ingest time means every query gets pre-joined data for free.

### 4. Overcomplicating the Processing Logic
```
❌ Build a complex ML model inside the stream processor
✅ Keep stream processing simple: lookups, counts, rates, flags
   Run complex ML in batch; use results as lookup data in the stream
```
Stream processors are not ML inference engines. Keep the logic fast and stateless where possible.

### 5. Not Handling Late-Arriving Events
```
❌ Assume events always arrive in order
✅ Use event-time watermarks to handle out-of-order events
   A mobile event may arrive 30 seconds after it occurred
```

---

## Key Takeaways

1. **Raw events are incomplete.** They capture what happened, not who the user is or what they've been doing. Stream processing adds that context.

2. **Three types of enrichment:** static (profile lookup), behavioral (session state), derived (computed signals). All three are needed for a complete picture.

3. **Enrich at ingest, not at query time.** Pay the enrichment cost once. Every downstream query benefits.

4. **Session state is the most valuable enrichment.** The sequence of events within a session reveals intent, frustration, and risk patterns that no single event contains.

5. **Stream processing sits between Kafka and storage.** It is the transformation layer that makes raw events AI-ready.

6. **Keep processing logic simple.** Lookups, counts, rates, boolean flags. Complex ML belongs in batch pipelines, not stream processors.

---

## What's Next

**Day 08** — Apache Pinot: how enriched events become sub-second queryable data for the AI retrieval layer.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
