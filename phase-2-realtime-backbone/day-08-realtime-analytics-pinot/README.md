# Day 08 — Real-Time Analytics with Apache Pinot

> **Phase 2 — Real-Time Data Backbone**
> Pinot is the query engine that makes streaming data answerable. Sub-second SQL on data that's seconds old.

---

## Introduction

On Day 7 we enriched events with user profiles, session state, and derived features. Those enriched events now flow into two storage systems: a vector store (for semantic retrieval) and Apache Pinot (for structured, SQL-based queries).

Pinot is the answer to a specific problem: **how do you run analytical SQL queries on data that arrived 2 seconds ago?**

A traditional data warehouse (Snowflake, BigQuery) is optimized for complex queries over historical data — but it takes minutes to load new data. A transactional database (Postgres) handles writes fast but degrades under analytical query load. Pinot sits in between: it ingests from Kafka in real-time and serves SQL queries in under 100ms, even on tables with billions of rows.

For AI systems, Pinot is the structured retrieval layer. When the LLM needs hard numbers — "how many errors did this user have in the last hour?" — Pinot answers in milliseconds.

---

## The Problem Without Real-Time Analytics

### Slow Queries
A data warehouse query over yesterday's data takes 10–60 seconds. For a support agent asking about a user who churned 5 minutes ago, that's useless.

### Stale Insights
Batch pipelines update data hourly or daily. A user who hit 5 checkout errors in the last 10 minutes looks completely healthy in a batch system. The AI assistant gives the wrong answer.

### Delayed Decisions
Fraud detection, churn prevention, and real-time personalization all require acting on data within seconds of it occurring. A batch pipeline cannot power a fraud alert that fires in 200ms.

---

## What is Apache Pinot?

Apache Pinot is a **real-time distributed OLAP (Online Analytical Processing) datastore** designed for low-latency analytical queries on large datasets, including data that is still arriving.

### What Pinot is Good At
- Sub-second SQL queries on tables with billions of rows
- Ingesting data from Kafka in real-time (data queryable within ~1 second of arrival)
- High-concurrency query serving (thousands of queries per second)
- Time-series queries with time-based partitioning
- Star-schema style queries with pre-aggregated indexes

### What Pinot is NOT Meant For
- Transactional workloads (INSERT/UPDATE/DELETE per row) — use Postgres
- Complex multi-table JOINs — use a data warehouse
- Full-text search — use Elasticsearch
- Ad-hoc exploratory queries with complex subqueries — use BigQuery/Snowflake
- Storing mutable state — Pinot tables are append-only (with limited upsert support)

---

## How Pinot Works

### 1. Ingestion
Pinot ingests data from two sources:
- **Real-time:** Kafka connector reads from a topic and writes to in-memory segments
- **Batch:** Files (Avro, Parquet, JSON) loaded into offline segments

```
Kafka topic: user.events.enriched
    │
    ▼
Pinot Real-Time Ingestion
    │ reads from Kafka partition
    │ writes to in-memory segment (mutable)
    ▼
Pinot Real-Time Table: user_events_realtime
    │ data queryable within ~1s of Kafka publish
    │ segment committed to deep storage periodically
    ▼
Pinot Offline Table: user_events_offline
    (historical data, immutable segments, faster queries)
```

### 2. Indexing
Pinot builds multiple index types automatically:
- **Forward index:** stores raw column values for retrieval
- **Inverted index:** enables fast `WHERE column = value` filtering
- **Range index:** enables fast `WHERE column BETWEEN x AND y`
- **Sorted index:** one column per table can be sorted for range scans
- **Star-tree index:** pre-aggregates for fast GROUP BY queries

### 3. Query Execution
Queries go through the Pinot Broker, which:
1. Parses the SQL query
2. Routes to the correct server(s) based on partition pruning
3. Merges results from multiple servers
4. Returns to the caller

```
Client → Pinot Broker → Pinot Server(s) → Segments → Result
                                                      ↑
                                              P99 < 100ms
```

### 4. Where it Fits in the Architecture

```
Kafka (user.events.enriched)
    │
    ▼
Pinot Real-Time Connector
    │
    ▼
Pinot Table (user_events_realtime)
    │
    ▼
Pinot Broker (SQL query interface)
    │
    ├── Support agent queries: "errors for user u_4821 last hour"
    ├── LLM retrieval layer: structured metrics for context assembly
    └── Real-time dashboards: live error rates, active sessions
```

---

## Real-World Example — User Activity Monitoring

**System:** SaaS platform, 50K users, AI support assistant.

### Table Schema
```sql
CREATE TABLE user_events_realtime (
  event_id        VARCHAR,
  event_type      VARCHAR,
  user_id         VARCHAR,
  session_id      VARCHAR,
  ts              TIMESTAMP,
  page            VARCHAR,
  error_code      INT,
  -- enriched fields
  plan            VARCHAR,
  country         VARCHAR,
  segment         VARCHAR,
  lifetime_orders INT,
  -- session state
  session_events  INT,
  session_errors  INT,
  pricing_visits  INT,
  duration_s      INT,
  -- derived features
  error_rate      DOUBLE,
  churn_risk      BOOLEAN,
  intent_score    DOUBLE,
  is_high_value   BOOLEAN
)
USING REALTIME
PARTITIONED BY (user_id)
TIME_COLUMN ts
RETENTION 7d
```

### Query Examples

**1. Real-time error monitoring (last 10 seconds)**
```sql
SELECT user_id, COUNT(*) as error_count
FROM user_events_realtime
WHERE event_type = 'system.server_error'
  AND ts > ago('10s')
GROUP BY user_id
ORDER BY error_count DESC
LIMIT 10
```
*Use case: live error dashboard, fires alert if any user hits 3+ errors*

**2. Users at churn risk right now**
```sql
SELECT user_id, error_rate, intent_score, session_errors
FROM user_events_realtime
WHERE churn_risk = true
  AND ts > ago('1h')
ORDER BY error_rate DESC
LIMIT 20
```
*Use case: support team prioritization, LLM context retrieval*

**3. Upgrade intent detection**
```sql
SELECT user_id, pricing_visits, intent_score, plan
FROM user_events_realtime
WHERE intent_score > 0.7
  AND plan = 'free'
  AND ts > ago('30m')
ORDER BY intent_score DESC
LIMIT 10
```
*Use case: trigger real-time upgrade offer*

**4. Session-level aggregation**
```sql
SELECT
  user_id,
  MAX(session_errors)  AS max_errors,
  MAX(error_rate)      AS max_error_rate,
  MAX(pricing_visits)  AS max_pricing_visits,
  MAX(intent_score)    AS max_intent_score
FROM user_events_realtime
WHERE user_id = 'u_4821'
  AND ts > ago('7d')
GROUP BY user_id
```
*Use case: LLM context — "what has this user been doing this week?"*

**5. Real-time funnel analysis**
```sql
SELECT
  page,
  COUNT(DISTINCT user_id) AS unique_users,
  COUNT(CASE WHEN event_type = 'system.server_error' THEN 1 END) AS errors
FROM user_events_realtime
WHERE ts > ago('1h')
GROUP BY page
ORDER BY errors DESC
```
*Use case: identify which pages are causing the most errors right now*

---

## Common Mistakes

### 1. Using Pinot as a Transactional Database
```
❌ UPDATE user SET plan = 'pro' WHERE user_id = 'u_4821'
✅ Pinot is append-only (with limited upsert support for specific use cases)
   Use Postgres for mutable state. Use Pinot for analytical queries.
```

### 2. Ignoring Data Modeling
```
❌ Store raw nested JSON in Pinot and parse at query time
✅ Flatten the schema at ingest time (Day 7 enrichment does this)
   Pinot performs best on flat, denormalized schemas
```

### 3. Expecting Batch-Like Behavior
```
❌ Run complex multi-table JOINs in Pinot
✅ Pinot supports limited JOINs (lookup joins only in recent versions)
   For complex joins, use a data warehouse. Pinot is for single-table analytics.
```

### 4. Not Setting Retention Correctly
```
❌ Use default retention and run out of disk space
✅ Set retention based on query patterns:
   - Real-time table: 7 days (hot data, fast queries)
   - Offline table: 2 years (cold data, slower but complete)
```

### 5. Querying Without Time Filters
```
❌ SELECT * FROM user_events_realtime WHERE user_id = 'u_4821'
✅ Always include a time filter: AND ts > ago('7d')
   Without time filters, Pinot scans all segments — latency spikes
```

---

## Key Takeaways

1. **Pinot bridges streaming and querying.** It ingests from Kafka in real-time and serves SQL in under 100ms. Nothing else does both.

2. **Data is queryable within ~1 second of Kafka publish.** This is the freshness guarantee that makes real-time AI systems possible.

3. **Pinot is not a replacement for a data warehouse.** Use Pinot for recent data and fast queries. Use Snowflake/BigQuery for historical analysis and complex joins.

4. **Flat, denormalized schemas perform best.** The enrichment layer (Day 7) produces exactly this — flat rows with all context pre-joined.

5. **Always filter by time.** Pinot uses time-based partitioning for segment pruning. Time filters are the primary performance lever.

6. **Pinot is the structured half of the retrieval layer.** Vector store handles semantic queries. Pinot handles structured metrics. The LLM needs both.

---

## What's Next

**Day 09** — Latency vs Freshness: understanding the tradeoffs between how fast a system responds and how current its data is.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
