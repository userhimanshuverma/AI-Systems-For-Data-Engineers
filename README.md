# AI Systems for Data Engineers
### From Data Pipelines → Intelligent Systems — 28-Day Roadmap

> A structured, hands-on learning series for data engineers ready to build production-grade AI systems — not just pipelines.

---

## Who This Is For

- Data engineers who want to understand where the field is heading
- Engineers building or maintaining pipelines who need to integrate LLMs and AI
- Anyone who wants to go beyond ETL and design intelligent, real-time data systems

---

## What You'll Build

By the end of this series, you will have designed and prototyped a **full end-to-end AI-powered data system** that includes:

- A real-time event-driven data backbone (Kafka + Pinot)
- An LLM-ready data layer with embeddings and vector search
- A RAG pipeline with hybrid retrieval
- An agent-based decision system
- An orchestrated, observable, cost-optimized architecture

---

## 28-Day Roadmap

| Day | Topic | Phase |
|-----|-------|-------|
| 01 | Why Data Engineering is Changing | Phase 1 — Reset the Mental Model |
| 02 | Batch vs Real-Time vs AI Systems | Phase 1 |
| 03 | The New Stack | Phase 1 |
| 04 | System Blueprint | Phase 1 |
| 05 | Kafka & Event-Driven Systems | Phase 2 — Real-Time Data Backbone |
| 06 | Event Schema Design | Phase 2 |
| 07 | Stream Processing | Phase 2 |
| 08 | Apache Pinot | Phase 2 |
| 09 | Latency vs Freshness | Phase 2 |
| 10 | LLM Data Requirements | Phase 3 — Making Data LLM-Ready |
| 11 | Embedding Pipelines | Phase 3 |
| 12 | Vector DB Design | Phase 3 |
| 13 | Data Freshness in RAG | Phase 3 |
| 14 | Hybrid Retrieval | Phase 3 |
| 15 | RAG in Production | Phase 4 — Intelligence Layer |
| 16 | Query Understanding | Phase 4 |
| 17 | Agents vs Pipelines | Phase 4 |
| 18 | Agent Tooling | Phase 4 |
| 19 | Decision Systems | Phase 4 |
| 20 | Apache Airflow | Phase 5 — Orchestration & Reliability |
| 21 | Async Architectures | Phase 5 |
| 22 | Failure Modes | Phase 5 |
| 23 | Observability | Phase 5 |
| 24 | Cost Optimization | Phase 6 — Scaling & Cost |
| 25 | Scaling Systems | Phase 6 |
| 26 | Performance Optimization | Phase 6 |
| 27 | End-to-End Architecture | Phase 7 — Final System |
| 28 | Case Study | Phase 7 |

---

## Architecture Preview

```
[ Event Sources ]
       │
       ▼
[ Kafka — Event Backbone ]
       │
  ┌────┴────┐
  ▼         ▼
[ Stream   [ Batch
 Processing] Processing ]
  │              │
  └──────┬───────┘
         ▼
  [ Feature Store / Vector DB ]
         │
         ▼
  [ LLM + RAG Layer ]
         │
         ▼
  [ Agent / Decision System ]
         │
         ▼
  [ API / Application Layer ]
```

---

## How to Use This Repo

1. Follow the days in order — each builds on the last
2. Read the `README.md` in each day's folder for the concept
3. Check `/projects` for the running system implementation
4. Use `/resources` for curated tools and references
5. Use `/docs` for architecture diagrams and design notes

---

## Repo Structure

```
AI-Systems-For-Data-Engineers/
├── README.md
├── docs/
├── projects/
├── resources/
├── assets/
├── phase-1-mental-model/
│   ├── day-01-why-data-engineering-is-changing/
│   ├── day-02-batch-vs-realtime-vs-ai/
│   ├── day-03-the-new-stack/
│   └── day-04-system-blueprint/
├── phase-2-realtime-backbone/
│   ├── day-05-kafka-event-driven/
│   ├── day-06-event-schema-design/
│   ├── day-07-stream-processing/
│   ├── day-08-apache-pinot/
│   └── day-09-latency-vs-freshness/
├── phase-3-llm-ready-data/
│   ├── day-10-llm-data-requirements/
│   ├── day-11-embedding-pipelines/
│   ├── day-12-vector-db-design/
│   ├── day-13-data-freshness-in-rag/
│   └── day-14-hybrid-retrieval/
├── phase-4-intelligence-layer/
│   ├── day-15-rag-in-production/
│   ├── day-16-query-understanding/
│   ├── day-17-agents-vs-pipelines/
│   ├── day-18-agent-tooling/
│   └── day-19-decision-systems/
├── phase-5-orchestration-reliability/
│   ├── day-20-apache-airflow/
│   ├── day-21-async-architectures/
│   ├── day-22-failure-modes/
│   └── day-23-observability/
├── phase-6-scaling-cost/
│   ├── day-24-cost-optimization/
│   ├── day-25-scaling-systems/
│   └── day-26-performance-optimization/
└── phase-7-final-system/
    ├── day-27-end-to-end-architecture/
    └── day-28-case-study/
```

---

## License

MIT — use freely, build seriously.
