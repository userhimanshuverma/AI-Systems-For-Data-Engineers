# Day 05 — Event-Driven Systems with Kafka

> **Phase 2 — Real-Time Data Backbone**
> Events are the atomic unit of real-time systems. Kafka is the infrastructure that makes them durable, replayable, and scalable.

---

## Introduction

Every meaningful thing that happens in a system is an event: a user clicked a button, a payment was processed, a server threw a 500 error. These events contain the most current, most accurate picture of what's happening right now.

Traditional data systems ignore this. They poll databases on schedules, aggregate into tables, and serve yesterday's picture as today's answer. For dashboards, that's acceptable. For AI systems that need to reason about what a user is doing *right now*, it's a fundamental failure.

Event-driven architecture flips the model: instead of asking "what does the database say?", you ask "what just happened?" — and you get the answer in milliseconds.

---

## The Problem with Table-Based Systems

A table-based system stores the *current state* of the world. An event-driven system stores *everything that happened* to produce that state.

### Delayed Data
```
Table-based:
  User churns at 14:32
  Batch job runs at 15:00
  Dashboard updates at 15:05
  Support team sees it at 15:05 — 33 minutes later

Event-driven:
  User churns at 14:32
  Event published to Kafka at 14:32:00.012
  Consumer processes at 14:32:00.089
  Alert fires at 14:32:00.150 — 138ms later
```

### Lack of Real-Time Context
A database row tells you the current state. It doesn't tell you *how* the user got there. Did they visit /pricing 6 times before churning? Did they hit 3 errors on /checkout? That behavioral context lives in the event stream — not in a state table.

For an LLM to reason about user behavior, it needs the sequence of events, not just the final state.

---

## What is an Event?

An event is an **immutable record of something that happened**, with a timestamp.

Three properties define an event:
1. **It happened in the past** — events are facts, not intentions
2. **It is immutable** — once written, it never changes
3. **It has a timestamp** — ordering matters

### Real Examples

```json
// User clicked upgrade button
{
  "event_id": "evt_8821a",
  "event_type": "button_click",
  "user_id": "u_4821",
  "properties": { "element": "cta_upgrade", "page": "/pricing" },
  "ts": "2026-04-27T14:32:01.412Z"
}

// Payment processed
{
  "event_id": "evt_9932b",
  "event_type": "payment_processed",
  "user_id": "u_4821",
  "properties": { "amount_usd": 49, "plan": "pro", "status": "success" },
  "ts": "2026-04-27T14:32:08.901Z"
}

// Application error
{
  "event_id": "evt_1104c",
  "event_type": "server_error",
  "user_id": "u_4821",
  "properties": { "code": 500, "page": "/checkout", "trace_id": "abc123" },
  "ts": "2026-04-27T14:32:15.220Z"
}
```

Events are not commands ("do this") or queries ("tell me this"). They are facts ("this happened").

---

## What is Kafka?

Apache Kafka is a **distributed event streaming platform**. It is not a database, not a message queue in the traditional sense, and not a cache.

Its job is to:
1. **Receive** events from producers (applications, services)
2. **Store** them durably in ordered, partitioned logs
3. **Deliver** them to consumers reliably, at scale, with replay capability

The key insight: Kafka is a **log**. Events are appended to the end. Consumers read from any position in the log. The log is retained for a configurable period (hours to forever). This makes Kafka fundamentally different from a traditional message queue where messages are deleted after consumption.

### Core Concepts

#### Topic
A named, ordered stream of events. Think of it as a category or feed.

```
Topic: user.events
  ├── All user actions (clicks, page views, errors, purchases)
  └── Partitioned for parallelism

Topic: order.events
  └── All order lifecycle events

Topic: system.errors
  └── All application errors
```

#### Producer
Any application that publishes events to a Kafka topic.

```python
# Conceptually:
producer.publish(topic="user.events", key="u_4821", value=event_dict)
```

The `key` determines which partition the event goes to. Events with the same key always go to the same partition — this guarantees ordering per key (e.g., all events for user u_4821 are ordered).

#### Consumer
Any application that reads events from a Kafka topic.

```python
# Conceptually:
for event in consumer.subscribe(topic="user.events"):
    process(event)
```

Consumers track their position in the log using an **offset** — a sequential integer. This means:
- A consumer can re-read events from any point (replay)
- Multiple independent consumers can read the same topic without interfering
- A failed consumer can resume exactly where it left off

#### Partition
A topic is split into N partitions. Each partition is an independent, ordered log.

```
Topic: user.events (3 partitions)
  Partition 0: [evt_001, evt_004, evt_007, ...]  ← users hashed to 0
  Partition 1: [evt_002, evt_005, evt_008, ...]  ← users hashed to 1
  Partition 2: [evt_003, evt_006, evt_009, ...]  ← users hashed to 2
```

Why partitions matter:
- **Parallelism**: 3 partitions → 3 consumers can process simultaneously
- **Ordering**: ordering is guaranteed *within* a partition, not across partitions
- **Scalability**: more partitions = more throughput (up to broker limits)

**Rule of thumb for early-stage systems:** Start with 3–6 partitions per topic. You can increase partitions later, but you cannot decrease them.

#### Consumer Group
A set of consumers that share the work of reading a topic. Each partition is assigned to exactly one consumer in the group at a time.

```
Topic: user.events (3 partitions)
Consumer Group: flink-enrichment-job
  Consumer A → Partition 0
  Consumer B → Partition 1
  Consumer C → Partition 2
```

If Consumer B fails, Kafka reassigns Partition 1 to Consumer A or C automatically (rebalance).

#### Offset
The position of a consumer in a partition. Kafka stores committed offsets so consumers can resume after failure.

```
Partition 0: [evt_001, evt_004, evt_007, evt_010, ...]
                                  ↑
                          Consumer offset = 3
                          (next read: evt_010)
```

---

## Event Flow Architecture

```
[Application]  →  [Kafka Topic]  →  [Consumer]  →  [Processing]  →  [Output]
   producer          durable           reads          enriches        Pinot
                      log              events         detects         Vector DB
                                                      routes          Alert
```

### Step by Step

1. **Application publishes event** — user clicks, payment fires, error occurs
2. **Kafka stores event** — appended to the correct partition, assigned an offset
3. **Consumer reads event** — within milliseconds of publication
4. **Processing logic runs** — enrich, filter, aggregate, detect anomalies
5. **Output is emitted** — to Pinot (queryable), Vector DB (retrievable), or an alert system

---

## Real-World Example — User Activity Tracking

**System:** SaaS platform tracking 50K users, feeding an AI support assistant.

### Topics
| Topic | Producer | Consumers | Partitions |
|-------|----------|-----------|-----------|
| `user.events` | Web/mobile app | Flink enrichment, Pinot connector | 12 |
| `system.errors` | Backend services | Alert consumer, Flink | 6 |
| `support.tickets` | Support platform | Embedding pipeline | 3 |

### Event Flow
```
User visits /pricing (6th time this week)
  → App publishes to user.events (partition 7, offset 88421)
  → Flink consumer reads within 12ms
  → Flink enriches: plan=free, segment=at_risk, pricing_visits=6
  → Flink emits to:
      Pinot: structured row queryable in ~1s
      Embedding pipeline: text description → vector → Qdrant
  → Support AI query: "Why is u_4821 at risk?"
      Pinot: SELECT * WHERE user_id='u_4821' → {pricing_visits:6, errors:3}
      Qdrant: semantic search → top-4 relevant events
      LLM: "User visited /pricing 6 times, hit 3 checkout errors. Churn risk: HIGH."
```

---

## Why AI Systems Need Event Streams

### Freshness
An LLM reasoning about a user needs data from the last few minutes, not the last few hours. Kafka + stream processing delivers data to the retrieval layer within seconds of it occurring.

### Context
A single database row says "user_status = churned". The event stream says:
- visited /pricing 6 times
- hit 3 checkout errors
- submitted a support ticket saying "your checkout is broken"
- then churned

The LLM needs the sequence, not just the final state.

### Real-Time Decisions
Fraud detection, churn prevention, personalization — these require acting on events as they happen. A batch pipeline that runs hourly cannot power a fraud alert that fires in 200ms.

---

## Common Mistakes

### 1. Treating Kafka as a Database
```
❌ Query Kafka directly for user history: "give me all events for u_4821"
✅ Use Kafka as a transport. Store events in Pinot (SQL) or Vector DB (semantic).
   Kafka is a log, not a query engine.
```

### 2. Ignoring Schema Design
```
❌ Publish raw, unstructured JSON with inconsistent field names
✅ Define a schema (Avro or JSON Schema) and enforce it via Schema Registry
   Schema changes break consumers silently if not managed.
```

### 3. Overcomplicating Partitions Early
```
❌ Start with 100 partitions "for future scale"
✅ Start with 3–6 partitions. Add more when you have measured throughput data.
   Too many partitions increase broker overhead and rebalance time.
```

### 4. Not Setting Retention Correctly
```
❌ Use default retention (7 days) without thinking about replay needs
✅ Set retention based on your recovery window:
   - Need to replay 30 days of events? Set retention.ms = 2592000000
   - Storage is cheap. Losing events is expensive.
```

### 5. One Consumer Per Topic
```
❌ Build one monolithic consumer that does enrichment + storage + alerting
✅ Use consumer groups. Each concern gets its own consumer group.
   Flink enrichment, Pinot ingestion, and alerting are independent consumers.
```

---

## Key Takeaways

1. **Events are facts, not state.** They record what happened, not what is. This distinction is fundamental.

2. **Kafka is a log, not a database.** It stores events durably and delivers them reliably. It does not answer queries.

3. **Partitions enable parallelism.** More partitions = more consumers = more throughput. But start small.

4. **Offsets enable replay.** Any consumer can re-read any event from any point in history. This is Kafka's superpower.

5. **Consumer groups enable fan-out.** One event stream can feed multiple independent systems simultaneously without any coupling.

6. **AI systems need event streams for freshness and context.** A database row tells you the current state. An event stream tells you the story of how you got there.

---

## What's Next

**Day 06** — Event Schema Design: designing robust, evolvable event schemas with Avro and Schema Registry.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
