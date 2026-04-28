# Architecture Diagrams — Day 05: Event-Driven Systems with Kafka

---

## ASCII Diagram — Event Flow Architecture

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                         EVENT PRODUCERS                                      ║
║   [Web App]    [Mobile App]    [Backend Services]    [Payment System]        ║
╚═══════╤═══════════════╤══════════════════╤═══════════════════╤══════════════╝
        │               │                  │                   │
        │  publish(key, value)              │                   │
        └───────────────┴──────────────────┴───────────────────┘
                                    │
                                    ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  APACHE KAFKA                                                                ║
║──────────────────────────────────────────────────────────────────────────────║
║                                                                              ║
║  Topic: user.events (12 partitions, keyed by user_id)                       ║
║  ┌─────────────────────────────────────────────────────────────────────┐    ║
║  │ Partition 0: [off=0: evt_A] [off=1: evt_D] [off=2: evt_G] ...      │    ║
║  │ Partition 1: [off=0: evt_B] [off=1: evt_E] [off=2: evt_H] ...      │    ║
║  │ Partition 2: [off=0: evt_C] [off=1: evt_F] [off=2: evt_I] ...      │    ║
║  └─────────────────────────────────────────────────────────────────────┘    ║
║                                                                              ║
║  Topic: system.errors (6 partitions)                                        ║
║  Topic: support.tickets (3 partitions)                                      ║
║                                                                              ║
║  Retention: configurable (default 7 days)                                   ║
║  Replication factor: 3 (for fault tolerance)                                ║
╚══════════════════════════════╤═══════════════════════════════════════════════╝
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
╔═════════════════╗  ╔══════════════════╗  ╔═════════════════════╗
║ CONSUMER GROUP  ║  ║  CONSUMER GROUP  ║  ║  CONSUMER GROUP     ║
║ flink-enrichment║  ║  pinot-connector ║  ║  alert-service      ║
║─────────────────║  ║──────────────────║  ║─────────────────────║
║ Reads all       ║  ║ Reads all        ║  ║ Reads error events  ║
║ partitions      ║  ║ partitions       ║  ║ only                ║
║                 ║  ║                  ║  ║                     ║
║ Enriches events ║  ║ Writes to Pinot  ║  ║ Fires PagerDuty     ║
║ Routes to sinks ║  ║ real-time table  ║  ║ alerts              ║
╚════════╤════════╝  ╚══════════════════╝  ╚═════════════════════╝
         │
         ├──────────────────────────────────┐
         ▼                                  ▼
╔═════════════════════╗          ╔══════════════════════════╗
║  APACHE PINOT       ║          ║  EMBEDDING PIPELINE      ║
║  Real-Time OLAP     ║          ║  text → vectors          ║
║  SQL in <100ms      ║          ║  → Vector Store (Qdrant) ║
╚═════════════════════╝          ╚══════════════════════════╝
         │                                  │
         └──────────────────┬───────────────┘
                            ▼
                   ╔════════════════╗
                   ║  LLM LAYER     ║
                   ║  Retrieval +   ║
                   ║  Reasoning     ║
                   ╚════════════════╝


KEY PROPERTIES:
  Producers and consumers are fully decoupled
  Multiple consumer groups read the same topic independently
  Each consumer tracks its own offset (position in the log)
  Events are retained for replay — consumers can re-read history
  Partition key (user_id) guarantees ordering per user
```

---

## ASCII Diagram — Partition + Offset Model

```
Topic: user.events
─────────────────────────────────────────────────────────────────────

Partition 0 (users hashed to 0):
  offset: 0          1          2          3          4
          [u_001:pv] [u_001:clk][u_004:err][u_001:pur][u_004:pv ]
                                                ↑
                                    Consumer A offset = 4
                                    (next read: offset 4)

Partition 1 (users hashed to 1):
  offset: 0          1          2          3
          [u_002:pv] [u_002:err][u_002:pur][u_002:lgout]
                         ↑
                Consumer B offset = 2
                (next read: offset 2)

Partition 2 (users hashed to 2):
  offset: 0          1          2
          [u_003:sgn][u_003:pv] [u_003:err]
                                      ↑
                              Consumer C offset = 3
                              (next read: nothing yet)

Legend: pv=page_view, clk=click, err=error, pur=purchase, sgn=signup, lgout=logout
```

---

## Mermaid Diagram — Event-Driven Architecture

```mermaid
flowchart LR
    subgraph Producers["Event Producers"]
        P1[Web App]
        P2[Mobile App]
        P3[Backend Services]
    end

    subgraph Kafka["Apache Kafka"]
        T1[user.events\n12 partitions]
        T2[system.errors\n6 partitions]
        T3[support.tickets\n3 partitions]
    end

    subgraph Consumers["Consumer Groups"]
        C1[Flink Enrichment\nenrich · window · route]
        C2[Pinot Connector\nreal-time ingestion]
        C3[Alert Service\nerror detection]
        C4[Embedding Pipeline\ntext → vectors]
    end

    subgraph Outputs["Output Systems"]
        O1[Apache Pinot\nSQL queries]
        O2[Vector Store\nsemantic search]
        O3[PagerDuty\nalerts]
        O4[LLM Layer\nreasoning]
    end

    P1 --> T1
    P2 --> T1
    P3 --> T1
    P3 --> T2
    P3 --> T3

    T1 --> C1
    T1 --> C2
    T2 --> C3
    T3 --> C4

    C1 --> O1
    C1 --> O2
    C2 --> O1
    C3 --> O3
    C4 --> O2
    O1 --> O4
    O2 --> O4

    style Producers fill:#0d1e30,color:#7eb8f7
    style Kafka fill:#0d2a1a,color:#7ef7a0
    style Consumers fill:#1a0d30,color:#b07ef7
    style Outputs fill:#2a0d1a,color:#f77eb0
```

---

## Mermaid Diagram — Event Lifecycle

```mermaid
sequenceDiagram
    participant App as Web App
    participant K as Kafka Broker
    participant F as Flink Consumer
    participant P as Apache Pinot
    participant V as Vector Store

    App->>K: produce(topic="user.events", key="u_4821", value={...})
    Note over K: Append to partition 7, offset 88421<br/>Replicate to 2 follower brokers

    K-->>App: ack (offset=88421)
    Note over App: publish confirmed in ~5ms

    K->>F: deliver event (consumer group: flink-enrichment)
    Note over F: received within ~10ms of publish

    F->>F: enrich with user profile
    F->>F: update session window state

    par parallel sinks
        F->>P: write enriched row
        Note over P: queryable within ~1s
    and
        F->>V: upsert embedding
        Note over V: queryable within ~50ms
    end
```
