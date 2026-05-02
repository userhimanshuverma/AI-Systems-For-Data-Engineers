# Architecture Diagrams — Day 09: Latency vs Freshness Tradeoff

---

## ASCII Diagram — Pipeline Delays (Where Latency Accumulates)

```
EVENT OCCURS IN APPLICATION
t = 0ms
    │
    │  +5ms   (network + Kafka broker write)
    ▼
╔══════════════════════════════════════════════════════════════╗
║  KAFKA TOPIC: user.events                                    ║
║  Event stored at offset N                                    ║
║  Data age: ~5ms                                              ║
╚══════════════════════════════════════════════════════════════╝
    │
    │  +15ms  (Flink consumer poll interval)
    │  +8ms   (Redis lookup — static enrichment)
    │  +2ms   (session state update)
    │  +1ms   (derived feature computation)
    │  +5ms   (Kafka write — enriched topic)
    ▼
╔══════════════════════════════════════════════════════════════╗
║  FLINK OUTPUT: user.events.enriched                          ║
║  Enriched event in Kafka                                     ║
║  Data age: ~36ms                                             ║
╚══════════════════════════════════════════════════════════════╝
    │
    │  +800ms  (Pinot segment build + commit interval)
    │           ← THIS IS THE BIGGEST FRESHNESS BOTTLENECK
    ▼
╔══════════════════════════════════════════════════════════════╗
║  PINOT REAL-TIME TABLE: user_events_realtime                 ║
║  Event queryable via SQL                                     ║
║  Data age: ~836ms (~1 second)                                ║
╚══════════════════════════════════════════════════════════════╝
    │
    │  +68ms   (Pinot query execution — P99)
    │  OR
    │  +0ms    (cache hit, TTL not expired)
    │  +stale  (cache hit, data may be minutes old)
    ▼
╔══════════════════════════════════════════════════════════════╗
║  QUERY RESULT                                                ║
║  Fresh path:  data age ~904ms, query time ~68ms              ║
║  Cached path: data age ~5min,  query time ~5ms               ║
╚══════════════════════════════════════════════════════════════╝
    │
    │  +500ms  (LLM call — GPT-4o-mini)
    ▼
╔══════════════════════════════════════════════════════════════╗
║  AI RESPONSE                                                 ║
║  Fresh path:  total ~1.4s, data age ~1s                      ║
║  Cached path: total ~505ms, data age ~5min                   ║
╚══════════════════════════════════════════════════════════════╝


LATENCY BUDGET BREAKDOWN
─────────────────────────────────────────────────────────────────
Stage                    Latency    Cumulative    Freshness impact
─────────────────────────────────────────────────────────────────
App → Kafka              5ms        5ms           minimal
Kafka → Flink            15ms       20ms          minimal
Flink enrichment         11ms       31ms          minimal
Flink → Kafka (enr.)     5ms        36ms          minimal
Kafka → Pinot segment    800ms      836ms         ← MAJOR
Pinot query              68ms       904ms         none (read)
LLM call                 500ms      1,404ms       none (read)
─────────────────────────────────────────────────────────────────
Total (no cache):        ~1.4s      data age ~1s
Total (5min cache):      ~505ms     data age ~5min
─────────────────────────────────────────────────────────────────
```

---

## ASCII Diagram — Freshness vs Latency Spectrum

```
FRESHNESS vs QUERY LATENCY — Where Different Approaches Land
─────────────────────────────────────────────────────────────────

HIGH FRESHNESS
     │
     │  Kafka Direct Scan
     │  (data age: ~0ms, query: ~120ms, no SQL)
     │
     │  Pinot Real-Time (no cache)
     │  (data age: ~1s, query: ~68ms)  ← SWEET SPOT FOR AI
     │
     │  Pinot + Short Cache (TTL=30s)
     │  (data age: ~31s, query: ~5ms)
     │
     │  Pinot + Medium Cache (TTL=5min)
     │  (data age: ~5min, query: ~5ms)
     │
     │  Data Warehouse (batch, hourly)
     │  (data age: ~60min, query: ~2s)
     │
LOW  │  Data Warehouse (batch, daily)
FRESHNESS  (data age: ~24hr, query: ~10s)
     │
     └──────────────────────────────────────────────────────────
        FAST QUERY                              SLOW QUERY
        (low latency)                           (high latency)


AI SYSTEM REQUIREMENTS:
  Support tooling:    freshness < 5s,  query < 200ms  → Pinot no cache
  Fraud detection:    freshness < 1s,  query < 100ms  → Pinot no cache
  Weekly reports:     freshness < 1hr, query < 5s     → Warehouse + cache
  LLM context:        freshness < 30s, query < 100ms  → Pinot + short TTL
```

---

## ASCII Diagram — Consumer Lag and Freshness Degradation

```
KAFKA CONSUMER LAG — How Freshness Degrades Under Load
─────────────────────────────────────────────────────────────────

Normal operation (lag = 0):
  Kafka latest offset:   88,421
  Flink consumer offset: 88,421
  Lag: 0 messages
  Freshness: ~1 second ✅

Under load (lag building):
  Kafka latest offset:   89,500
  Flink consumer offset: 88,421
  Lag: 1,079 messages
  At 100 events/sec: ~10.8 seconds behind
  Freshness: ~12 seconds ⚠️

Severe lag (alert threshold):
  Kafka latest offset:   98,421
  Flink consumer offset: 88,421
  Lag: 10,000 messages
  At 100 events/sec: ~100 seconds behind
  Freshness: ~102 seconds ❌

MONITORING RULE:
  Alert when consumer lag > 1,000 messages (10s at 100 events/sec)
  Page when consumer lag > 10,000 messages (100s at 100 events/sec)
```

---

## Mermaid Diagram — Latency vs Freshness Architecture

```mermaid
flowchart TD
    subgraph Event["Event Origin"]
        APP[Application\nt=0ms]
    end

    subgraph Pipeline["Data Pipeline — Latency Accumulates Here"]
        K[Kafka\nt+5ms\ndata age: 5ms]
        F[Flink Enrichment\nt+36ms\ndata age: 36ms]
        P[Pinot Real-Time\nt+836ms\ndata age: ~1s]
    end

    subgraph Query["Query Layer — Freshness vs Speed Tradeoff"]
        NC[No Cache\nquery: 68ms\ndata age: ~1s\n✅ Fresh]
        SC[Short Cache TTL=30s\nquery: 5ms\ndata age: ≤31s\n⚠️ Acceptable]
        LC[Long Cache TTL=5min\nquery: 5ms\ndata age: ≤5min\n❌ Stale for AI]
    end

    subgraph AI["AI Layer"]
        LLM[LLM Response\n+500ms]
    end

    APP --> K --> F --> P
    P --> NC --> LLM
    P --> SC --> LLM
    P --> LC --> LLM

    style Event fill:#0d1e30,color:#7eb8f7
    style Pipeline fill:#0d2a1a,color:#7ef7a0
    style Query fill:#1a1a0d,color:#f7f77e
    style AI fill:#2a0d1a,color:#f77eb0
```

---

## Mermaid Diagram — Tiered Freshness Design

```mermaid
flowchart LR
    subgraph Queries["Query Types"]
        Q1[Fraud Detection\nfreshness < 1s]
        Q2[Support Tooling\nfreshness < 5s]
        Q3[LLM Context\nfreshness < 30s]
        Q4[Hourly Reports\nfreshness < 1hr]
        Q5[Historical Analysis\nfreshness < 1day]
    end

    subgraph Storage["Storage + Cache Layer"]
        P1[Pinot\nno cache]
        P2[Pinot\nTTL=30s cache]
        P3[Pinot\nTTL=5min cache]
        W1[Warehouse\nTTL=30min cache]
        W2[Warehouse\nTTL=6hr cache]
    end

    Q1 --> P1
    Q2 --> P1
    Q3 --> P2
    Q4 --> W1
    Q5 --> W2

    style Queries fill:#0d1e30,color:#7eb8f7
    style Storage fill:#1a0d30,color:#b07ef7
```
