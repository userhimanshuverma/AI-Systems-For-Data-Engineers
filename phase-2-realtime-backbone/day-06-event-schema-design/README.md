# Day 06 — Designing Event Schemas for AI

> **Phase 2 — Real-Time Data Backbone**
> An event schema is a contract. A bad contract produces bad data. Bad data produces bad AI.

---

## Introduction

On Day 5 we established that events are the atomic unit of real-time systems. Today we go one level deeper: what should those events actually contain?

Schema design is where most teams make their first serious mistake. They log the minimum — just enough to debug — and then wonder why their AI system produces vague, low-confidence answers six months later.

The reason is simple: **an LLM can only reason over what's in the context window, and the context window is only as good as the events that fed it.** A thin event produces a thin embedding, which produces a weak retrieval result, which produces a poor LLM response.

Schema design is not a data engineering concern. It is an AI system concern.

---

## The Problem with Poor Event Design

### Missing Context
```json
// What most teams log
{ "user_id": "u_4821", "event": "click", "ts": "2026-04-27T14:32:01Z" }
```

This tells you a user clicked something. It does not tell you:
- What they clicked
- What page they were on
- What they were trying to do
- What device they were using
- What happened before this click

When this event is embedded and stored in a vector store, the resulting vector represents almost nothing. A semantic search for "users frustrated with checkout" will not surface this event — because there is no checkout context in it.

### Lack of Metadata
Without metadata, you cannot filter retrievals. If every event looks the same structurally, you cannot ask "give me only error events from mobile users on the free plan." You get everything or nothing.

### Inability to Support Downstream AI
The LLM reasoning layer needs **narrative context** — a sequence of events that tells a story. A minimal event schema produces events that, when converted to text, read like:

> "User u_4821 clicked at 14:32."

A well-designed schema produces events that read like:

> "User u_4821 (free plan, US, mobile) clicked the 'Upgrade Plan' button on the /pricing page at 14:32, during a session that started 8 minutes ago from a Google Ads referral."

The second version is what an LLM can reason over. The first is noise.

---

## What is an Event Schema?

An event schema is a **defined structure that every event of a given type must conform to**. It specifies:
- Which fields are required
- What type each field must be
- What values are valid for each field
- What the field means

A schema is a contract between the producer (the application) and every downstream consumer (Flink, Pinot, the embedding pipeline, the LLM layer).

### Good vs Bad Schema

**Bad schema — minimal, ambiguous:**
```json
{
  "user": "u_4821",
  "action": "click",
  "time": 1714225921
}
```
Problems:
- `user` should be `user_id` (inconsistent naming)
- `action` is too vague — click on what?
- `time` is a Unix timestamp with no timezone — ambiguous
- No context about where, what device, what session

**Good schema — rich, consistent, AI-ready:**
```json
{
  "event_id":       "evt_a1b2c3d4",
  "schema_version": "2.1",
  "event_type":     "ui.button_click",
  "user_id":        "u_4821",
  "session_id":     "sess_9x8y7z",
  "ts":             "2026-04-27T14:32:01.412Z",
  "context": {
    "page":         "/pricing",
    "element_id":   "cta_upgrade_plan",
    "element_text": "Upgrade to Pro",
    "referrer":     "/home"
  },
  "device": {
    "type":         "mobile",
    "os":           "iOS 17",
    "browser":      "Safari"
  },
  "user_properties": {
    "plan":         "free",
    "country":      "US",
    "signup_days_ago": 45,
    "segment":      "at_risk"
  }
}
```

Every field has a purpose. Every field is usable by a downstream system.

---

## Core Components of a Good Event

### 1. Identifiers
```json
"event_id":   "evt_a1b2c3d4"   // globally unique — enables deduplication
"user_id":    "u_4821"          // who did it — enables user-level filtering
"session_id": "sess_9x8y7z"    // groups events into sessions — enables session analysis
```

`event_id` must be globally unique (UUID or similar). Without it, you cannot deduplicate events if a producer retries. Without `session_id`, you cannot reconstruct the sequence of actions within a single visit.

### 2. Event Type
```json
"event_type": "ui.button_click"
```

Use a **namespaced, hierarchical naming convention**:
- `ui.button_click` — user interface interaction
- `ui.page_view` — page navigation
- `commerce.purchase` — transaction event
- `system.error` — application error
- `auth.login` — authentication event

This makes filtering trivial: `WHERE event_type LIKE 'ui.%'` returns all UI events.

### 3. Timestamp
```json
"ts": "2026-04-27T14:32:01.412Z"
```

Always use **ISO 8601 with UTC timezone**. Never use Unix timestamps in event schemas — they require conversion and are ambiguous without timezone context. Include milliseconds for ordering precision.

### 4. Context
```json
"context": {
  "page":         "/pricing",
  "element_id":   "cta_upgrade_plan",
  "element_text": "Upgrade to Pro",
  "referrer":     "/home"
}
```

Context answers: **where did this happen and what was the user interacting with?** This is the most important section for AI systems. The embedding of an event is largely determined by its context fields.

### 5. Device
```json
"device": {
  "type":    "mobile",
  "os":      "iOS 17",
  "browser": "Safari"
}
```

Device context enables segmentation: mobile users behave differently from desktop users. Checkout errors on mobile are a different problem from checkout errors on desktop.

### 6. User Properties (at event time)
```json
"user_properties": {
  "plan":            "free",
  "country":         "US",
  "signup_days_ago": 45,
  "segment":         "at_risk"
}
```

**Capture user properties at the time of the event, not by joining later.** A user's plan may change. If you join at query time, you lose the historical context. Embedding the plan at event time means the vector accurately represents the user's state when the event occurred.

### 7. Schema Version
```json
"schema_version": "2.1"
```

Every event must carry its schema version. When you evolve the schema, consumers can handle both old and new versions gracefully. Without this field, a schema change silently breaks all downstream consumers.

---

## Schema Design Principles

### 1. Consistency
Every event of the same type must have the same structure. If `user_id` is sometimes `userId` and sometimes `user_id`, your Pinot table will have null columns and your embeddings will be inconsistent.

**Enforce this with a schema registry** (Confluent Schema Registry with Avro, or a JSON Schema validator in your producer). Day 6 code includes a simple validator.

### 2. Context-Rich but Not Bloated
Include everything a downstream system might need to answer a question about this event. Do not include everything you could possibly log.

**Include:**
- What happened (event_type)
- Who did it (user_id, session_id)
- Where it happened (page, element)
- What state the user was in (plan, segment)
- What device they used

**Do not include:**
- Raw HTML of the page
- Full user profile (just the relevant properties)
- Nested objects more than 2 levels deep
- Fields that are always null

### 3. Backward Compatibility
When you add a new field, make it **optional with a default value**. Never remove or rename a required field — this breaks all existing consumers.

```
v1.0 → v1.1: Added optional field "device.app_version" ✅ safe
v1.0 → v2.0: Renamed "user_id" to "userId"             ❌ breaking change
v1.0 → v1.1: Removed field "referrer"                  ❌ breaking change
```

### 4. Naming Conventions
Pick one convention and enforce it everywhere:
- Use `snake_case` for all field names
- Use namespaced event types: `domain.action` (e.g., `ui.button_click`)
- Use ISO 8601 for all timestamps
- Use consistent ID formats (prefix + random: `evt_`, `sess_`, `u_`)

---

## Real-World Example — E-Commerce User Activity

**Scenario:** An e-commerce platform wants to use AI to identify users at risk of abandoning their cart.

### Weak Schema (what most teams start with)
```json
{ "uid": "u_4821", "evt": "add_to_cart", "t": 1714225921, "item": "SKU_9981" }
```

When embedded: *"User u_4821 added SKU_9981 to cart."*

LLM query: *"Why did this user abandon their cart?"*
LLM answer: *"Insufficient context to determine cart abandonment reason."*

### Strong Schema (what AI systems need)
```json
{
  "event_id":       "evt_c3d4e5f6",
  "schema_version": "1.0",
  "event_type":     "commerce.add_to_cart",
  "user_id":        "u_4821",
  "session_id":     "sess_ab12cd",
  "ts":             "2026-04-27T14:32:01.412Z",
  "context": {
    "page":          "/product/SKU_9981",
    "referrer":      "/search?q=running+shoes",
    "cart_item_count_before": 0
  },
  "product": {
    "sku":           "SKU_9981",
    "name":          "Trail Runner Pro X",
    "category":      "footwear",
    "price_usd":     129.99,
    "in_stock":      true
  },
  "device": {
    "type":          "mobile",
    "os":            "Android 14"
  },
  "user_properties": {
    "plan":          "registered",
    "country":       "US",
    "lifetime_orders": 2,
    "segment":       "repeat_buyer"
  }
}
```

When embedded: *"User u_4821 (registered, US, repeat buyer, 2 lifetime orders) added 'Trail Runner Pro X' ($129.99, footwear) to cart on mobile (Android 14) at 14:32, arriving from a search for 'running shoes'. Cart was empty before this action."*

LLM query: *"Why did this user abandon their cart?"*
LLM answer: *"User u_4821 added a $129.99 item to an empty cart via mobile after a search query. They are a repeat buyer with only 2 lifetime orders. High-value mobile cart additions from low-frequency buyers have a 68% abandonment rate in this segment. Likely cause: price hesitation or mobile checkout friction. Recommended action: send a mobile-optimized cart recovery email with a 10% discount."*

The schema is the difference between a useless answer and an actionable one.

---

## How Schema Impacts AI Systems

### Retrieval Quality
The vector store returns documents based on semantic similarity. A thin event produces a generic vector that matches everything weakly. A rich event produces a specific vector that matches the right queries strongly.

**Thin event embedding:** represents "a user did something"
**Rich event embedding:** represents "a free-plan mobile user clicked upgrade on the pricing page after 3 checkout errors"

### Embedding Quality
Embedding models convert text to vectors. The quality of the vector is proportional to the information density of the text. More context = more discriminative vector = better retrieval precision.

### LLM Reasoning Quality
The LLM can only reason over what's in the context window. If the retrieved events are thin, the LLM has nothing to work with. Rich events give the LLM specific evidence to cite in its response.

---

## Common Mistakes

### 1. Logging Too Little
```
❌ { "user_id": "u_4821", "event": "error" }
✅ Include: error code, page, element, user state, device, session context
```
You cannot add context retroactively. Once the event is logged, what's missing is gone forever.

### 2. Logging Too Much
```
❌ Include the full DOM, complete user profile, raw HTTP headers
✅ Include only what a downstream system would need to answer a question
```
Bloated events increase storage costs, slow down embedding, and add noise to vectors.

### 3. No Schema Standardization
```
❌ Different teams use different field names: userId, user_id, uid, userID
✅ Define a canonical schema. Enforce it in the producer with a validator.
```
Inconsistent schemas make Pinot tables unreliable and embeddings incomparable.

### 4. Mutable Event Fields
```
❌ Store user.plan in the event, then update it when the plan changes
✅ Events are immutable. Capture plan at event time. Never update events.
```
If you join plan at query time, you lose the historical state. The AI system needs to know what plan the user was on *when the event occurred*.

### 5. No Schema Version
```
❌ Evolve the schema silently — just add/remove fields
✅ Increment schema_version on every structural change
```
Without versioning, a schema change silently corrupts downstream consumers.

---

## Key Takeaways

1. **Schema design is an AI concern, not just a data concern.** The quality of your event schema directly determines the quality of your LLM responses.

2. **Capture context at event time.** User properties, device, page, referrer — all of it. You cannot reconstruct this later.

3. **Events are immutable.** Never update an event after it's written. If state changes, emit a new event.

4. **Use consistent naming conventions.** `snake_case`, namespaced event types, ISO 8601 timestamps. Enforce with a validator.

5. **Version your schema.** Every event carries `schema_version`. Consumers use it to handle migrations gracefully.

6. **Rich events produce rich embeddings.** The embedding is only as good as the text it's derived from. Thin events = thin vectors = weak retrieval = poor AI responses.

---

## What's Next

**Day 07** — Stream Processing: using Apache Flink to enrich, filter, and transform events in motion before they reach storage.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
