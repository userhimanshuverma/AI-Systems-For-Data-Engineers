# Architecture Diagrams — Day 14: Hybrid Retrieval

---

## ASCII Diagram — Hybrid Retrieval Architecture

```
USER QUERY: "Why is user u_4821 at risk of churning?"
                              │
                              ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  QUERY PARSER                                                                ║
║  intent = churn_investigation                                                ║
║  user_id = u_4821                                                            ║
║  time_range = 7d                                                             ║
╚══════════════════════════╤═══════════════════════════════════════════════════╝
                           │
              ┌────────────┴────────────┐
              │  PARALLEL RETRIEVAL     │
              ▼                         ▼
╔═════════════════════════╗   ╔══════════════════════════════════════════════╗
║  APACHE PINOT           ║   ║  VECTOR DB (Qdrant / Pinecone)               ║
║  Structured Retrieval   ║   ║  Semantic Retrieval                          ║
║─────────────────────────║   ║──────────────────────────────────────────────║
║                         ║   ║                                              ║
║  SELECT user_id,        ║   ║  query_vec = embed(                          ║
║    error_rate,          ║   ║    "checkout errors and churn risk"          ║
║    intent_score,        ║   ║  )                                           ║
║    churn_risk,          ║   ║                                              ║
║    pricing_visits       ║   ║  results = search(                           ║
║  FROM user_events       ║   ║    query_vec,                                ║
║  WHERE user_id=         ║   ║    filter={"user_id": "u_4821"},             ║
║    'u_4821'             ║   ║    top_k=4                                   ║
║  AND ts > ago('7d')     ║   ║  )                                           ║
║                         ║   ║                                              ║
║  Returns:               ║   ║  Returns:                                    ║
║  {                      ║   ║  [                                           ║
║    error_rate: 0.50,    ║   ║    "User hit 500 error on /checkout",        ║
║    intent_score: 0.82,  ║   ║    "Clicked Upgrade to Pro on /pricing",     ║
║    churn_risk: true,    ║   ║    "Support ticket: checkout failing",        ║
║    pricing_visits: 3    ║   ║    "Transaction declined on billing"          ║
║  }                      ║   ║  ]                                           ║
║                         ║   ║                                              ║
║  Latency: ~68ms         ║   ║  Latency: ~50ms                              ║
║  Data age: ~1s          ║   ║  Data age: ~1-5s                             ║
╚═════════════════════════╝   ╚══════════════════════════════════════════════╝
              │                         │
              └────────────┬────────────┘
                           ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  CONTEXT MERGER                                                              ║
║                                                                              ║
║  1. Deduplicate (remove overlapping event_ids)                              ║
║  2. Format structured metrics as natural language                           ║
║  3. Format semantic events as bullet list                                   ║
║  4. Token-budget: keep total context < 400 tokens                          ║
║  5. Assemble: [system prompt] + [structured] + [semantic] + [query]        ║
╚══════════════════════════╤═══════════════════════════════════════════════════╝
                           │
                           ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  LLM (GPT-4o / Claude)                                                       ║
║                                                                              ║
║  Input:  ~350 tokens (structured facts + semantic context)                  ║
║  Output: JSON { summary, action, confidence, evidence }                     ║
║  Latency: ~500ms                                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝


WHAT EACH LAYER CONTRIBUTES
─────────────────────────────────────────────────────────────────────────────
Pinot:      error_rate=50%, intent_score=0.82, churn_risk=TRUE, errors=5
            → The LLM knows the FACTS

Vector DB:  "hit 500 error on /checkout", "clicked Upgrade to Pro",
            "support ticket: checkout failing"
            → The LLM knows the STORY

Together:   "User has 50% error rate (fact) because checkout keeps failing
            (story) despite wanting to upgrade (story + fact)"
            → Complete, accurate, actionable response
```

---

## ASCII Diagram — Vector-Only vs Hybrid Comparison

```
VECTOR-ONLY RETRIEVAL
─────────────────────────────────────────────────────────────────────────────
Query → Vector Search → Top-4 events → LLM

LLM receives:
  "User hit error on /checkout"
  "User clicked Upgrade to Pro"
  "User visited /pricing"
  "User submitted support ticket"

LLM response:
  "User appears to have checkout issues and upgrade intent."
  ❌ No error count. No rate. No confidence. Vague.
  ❌ LLM may hallucinate: "User had about 3-4 errors" (wrong)


HYBRID RETRIEVAL
─────────────────────────────────────────────────────────────────────────────
Query → [Pinot SQL + Vector Search] → Merge → LLM

LLM receives:
  STRUCTURED: error_rate=50%, errors=5, intent=0.82, churn_risk=TRUE
  SEMANTIC:   "hit 500 error on /checkout", "clicked Upgrade to Pro",
              "support ticket: checkout failing"

LLM response:
  "User u_4821 has a 50% error rate (5 errors in 7 days), all on /checkout.
   Despite 3 visits to /pricing and clicking 'Upgrade to Pro', checkout
   failures are blocking conversion. Support ticket confirms the issue.
   Recommend: escalate checkout fix + send upgrade offer."
  ✅ Specific numbers. Behavioral story. Actionable recommendation.
```

---

## Mermaid Diagram — Full Hybrid Retrieval Architecture

```mermaid
flowchart TD
    subgraph Input["Query Input"]
        Q[User Query\n"Why is u_4821 at risk?"]
        QP[Query Parser\nintent + user_id + time_range]
    end

    subgraph Structured["Structured Retrieval — Apache Pinot"]
        PS[Pinot SQL\nSELECT metrics WHERE user_id=...]
        PM[Pinot Result\nerror_rate, intent_score, churn_risk]
    end

    subgraph Semantic["Semantic Retrieval — Vector DB"]
        QE[Query Embedding\nsame model as documents]
        VS[Vector Search\ntop-k + metadata filter]
        VM[Vector Result\nevent descriptions]
    end

    subgraph Merge["Context Merger"]
        DD[Deduplicate\nby event_id]
        FM[Format\nstructured → text]
        TB[Token Budget\n< 400 tokens]
        CA[Assembled Context\nfacts + story]
    end

    subgraph LLM["LLM Layer"]
        LM[LLM\nGPT-4o / Claude]
        OUT[JSON Response\nsummary + action + confidence]
    end

    Q --> QP
    QP --> PS --> PM
    QP --> QE --> VS --> VM
    PM --> DD
    VM --> DD
    DD --> FM --> TB --> CA --> LM --> OUT

    style Input fill:#0d1e30,color:#7eb8f7
    style Structured fill:#0d2a1a,color:#7ef7a0
    style Semantic fill:#1a0d30,color:#b07ef7
    style Merge fill:#1a1a0d,color:#f7f77e
    style LLM fill:#2a0d1a,color:#f77eb0
```

---

## Retrieval Responsibility Matrix

```
QUESTION                              PINOT    VECTOR DB    BOTH
─────────────────────────────────────────────────────────────────────────────
"How many errors did u_4821 have?"    ✅        ❌           —
"What is the error rate?"             ✅        ❌           —
"Is churn_risk TRUE?"                 ✅        ❌           —
"What pages did the user visit?"      ✅        ⚠️ partial   —
"What happened during checkout?"      ❌        ✅           —
"What did the user say in tickets?"   ❌        ✅           —
"Are there similar past incidents?"   ❌        ✅           —
"Why is the user at risk?"            ❌        ❌           ✅ (both needed)
"What should we do?"                  ❌        ❌           ✅ (both needed)
─────────────────────────────────────────────────────────────────────────────
Rule: Use Pinot for facts. Use Vector DB for context. Use both for reasoning.
```
