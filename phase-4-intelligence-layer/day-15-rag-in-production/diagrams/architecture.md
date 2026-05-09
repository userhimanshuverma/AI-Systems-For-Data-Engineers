# Day 15 — Architecture Diagrams: RAG in Production

---

## 1. ASCII Comparison: Toy RAG vs Production RAG

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                         TOY RAG  (fails in production)                      ║
╚══════════════════════════════════════════════════════════════════════════════╝

  User Query
      │
      ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  Step 1: Embed Query                                                    │
  │  embed("show me errors")  →  [0.12, -0.34, 0.87, ...]                  │
  │  ⚠ No intent classification. "show me errors" and "why is user         │
  │    churning?" get identical treatment.                                  │
  └──────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  Step 2: Vector Search (top-k=5)                                        │
  │  cosine_similarity(query_vec, all_docs) → top 5 chunks                 │
  │  ⚠ No structured retrieval. Can't answer "how many errors in 1h?"      │
  │  ⚠ No freshness check. Stale embeddings return wrong context.          │
  │  ⚠ No relevance filtering. All 5 chunks go to LLM regardless.          │
  └──────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  Step 3: LLM                                                            │
  │  prompt = system_prompt + top_5_chunks + user_query                    │
  │  response = llm.complete(prompt)                                        │
  │  ⚠ No output validation. Hallucinated user IDs pass through.           │
  │  ⚠ No confidence scoring. Wrong answers look like right answers.       │
  └─────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                               Answer (maybe wrong)


╔══════════════════════════════════════════════════════════════════════════════╗
║                    PRODUCTION RAG  (5 layers, each solving a failure mode)  ║
╚══════════════════════════════════════════════════════════════════════════════╝

  User Query
      │
      ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  LAYER 1: Query Understanding                                           │
  │                                                                         │
  │  classify_intent(query)   → churn_analysis | error_investigation |     │
  │                              upgrade_analysis | retention_analysis |   │
  │                              general                                    │
  │                                                                         │
  │  extract_entities(query)  → {user_id, time_range_hours,                │
  │                               plan_filter, segment_filter}              │
  │                                                                         │
  │  build_retrieval_plan()   → {use_pinot, use_vector, pinot_filters,     │
  │                               vector_query, top_k, freshness_required} │
  │                                                                         │
  │  ✓ Different query types get different retrieval strategies.            │
  └──────────────────────────────────┬──────────────────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │  (parallel retrieval)            │
                    ▼                                  ▼
  ┌──────────────────────────┐      ┌──────────────────────────────────────┐
  │  LAYER 2: Structured     │      │  LAYER 3: Semantic Retrieval         │
  │  Retrieval (Pinot SQL)   │      │  (Vector Store)                      │
  │                          │      │                                      │
  │  • counts & aggregations │      │  • behavioral context                │
  │  • time-range filters    │      │  • semantic similarity               │
  │  • rankings by metric    │      │  • event narratives                  │
  │  • plan/segment filters  │      │  • "why" questions                   │
  │                          │      │  • metadata-filtered search          │
  │  ✓ Facts, numbers, SQL   │      │  ✓ Context, patterns, meaning        │
  └──────────────┬───────────┘      └──────────────────┬───────────────────┘
                 │                                      │
                 └──────────────────┬───────────────────┘
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  LAYER 4: Context Filter                                                │
  │                                                                         │
  │  score_chunk()     → relevance = 0.5×similarity + 0.3×recency          │
  │                                + 0.2×metadata_match                    │
  │                                                                         │
  │  filter_context()  → drop below threshold, token budget ≤ 400,        │
  │                       deduplicate by event_id, order by relevance      │
  │                                                                         │
  │  format_context()  → natural language for LLM                          │
  │                                                                         │
  │  ✓ LLM receives only the most relevant, non-redundant context.         │
  └──────────────────────────────────┬──────────────────────────────────────┘
                                     │
                                     ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │  LAYER 5: Reasoning Layer (LLM + Validation)                            │
  │                                                                         │
  │  mock_llm(prompt, intent)   → structured JSON response                 │
  │                                                                         │
  │  validate_output(response)  → required fields present?                 │
  │                               confidence ≥ threshold?                  │
  │                               no contradictions with structured data?  │
  │                                                                         │
  │  ✓ Hallucinated outputs are caught before reaching downstream.         │
  └─────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
                          Validated Answer + Confidence


What each layer adds:
─────────────────────────────────────────────────────────────────────────────
Layer 1 (Query Understanding)  → routes queries to the right retrieval strategy
Layer 2 (Structured Retrieval) → answers factual, countable, time-range questions
Layer 3 (Semantic Retrieval)   → surfaces behavioral context and "why" patterns
Layer 4 (Context Filter)       → removes noise, enforces token budget, deduplicates
Layer 5 (Reasoning + Validate) → catches hallucinations, enforces output schema
```

---

## 2. Mermaid Flowchart — Production RAG Architecture

```mermaid
flowchart TD
    Q([User Query]) --> QU

    subgraph QU["Layer 1: Query Understanding"]
        CI[Classify Intent]
        EE[Extract Entities]
        RP[Build Retrieval Plan]
        CI --> EE --> RP
    end

    RP --> SR
    RP --> VR

    subgraph SR["Layer 2: Structured Retrieval"]
        P1[Pinot: at-risk users]
        P2[Pinot: error metrics]
        P3[Pinot: funnel data]
    end

    subgraph VR["Layer 3: Semantic Retrieval"]
        V1[Embed query]
        V2[Cosine similarity search]
        V3[Metadata filter]
        V1 --> V2 --> V3
    end

    SR --> CF
    VR --> CF

    subgraph CF["Layer 4: Context Filter"]
        SC[Score chunks]
        TB[Apply token budget ≤ 400]
        DD[Deduplicate by event_id]
        OR[Order by relevance]
        SC --> TB --> DD --> OR
    end

    CF --> RL

    subgraph RL["Layer 5: Reasoning Layer"]
        LM[LLM with structured prompt]
        VO[Validate output]
        CS[Confidence scoring]
        LM --> VO --> CS
    end

    CS --> A([Validated Answer])

    style QU fill:#1a1200,stroke:#f59e0b,color:#f59e0b
    style SR fill:#001428,stroke:#4d9fff,color:#4d9fff
    style VR fill:#1a0028,stroke:#a855f7,color:#a855f7
    style CF fill:#001a00,stroke:#22c55e,color:#22c55e
    style RL fill:#1a0014,stroke:#f472b6,color:#f472b6
```

---

## 3. Mermaid Sequence Diagram — Full Production RAG Request

```mermaid
sequenceDiagram
    actor User
    participant QU as Query Understanding
    participant Pinot as Pinot (SQL)
    participant VS as Vector Store
    participant CF as Context Filter
    participant LLM as LLM
    participant Val as Validator

    User->>QU: "Which free-plan users are most at risk this week?"

    Note over QU: classify_intent() → churn_analysis
    Note over QU: extract_entities() → {plan: free, time: 168h}
    Note over QU: build_retrieval_plan() → use_pinot=True, use_vector=True

    par Parallel Retrieval
        QU->>Pinot: SELECT user_id, error_rate, churn_risk_score<br/>FROM user_metrics WHERE plan='free'<br/>ORDER BY churn_risk_score DESC LIMIT 10
        Pinot-->>CF: 10 user metric rows (~80 tokens)
    and
        QU->>VS: embed("free plan user churn risk behavior errors")
        VS->>VS: cosine_similarity(query_vec, all_docs)
        VS-->>CF: top-15 semantic chunks (~600 tokens)
    end

    Note over CF: score_chunk() for each semantic chunk
    Note over CF: relevance = 0.5×sim + 0.3×recency + 0.2×metadata
    Note over CF: apply token budget: keep ≤ 320 tokens of semantic context
    Note over CF: deduplicate by event_id
    Note over CF: order by relevance score DESC

    CF->>LLM: structured prompt<br/>[system] + [metrics ~80t] + [context ~320t] + [query]

    Note over LLM: reason over filtered context
    LLM-->>Val: JSON response {users, risk_levels, evidence, confidence}

    Note over Val: required fields present?
    Note over Val: confidence ≥ 0.7?
    Note over Val: no contradictions with Pinot data?

    alt Validation passes
        Val-->>User: ranked at-risk users with evidence (confidence: 0.87)
    else Validation fails
        Val-->>User: low confidence response flagged for review
    end
```

---

## 4. Token Budget Visualization

```
Total LLM Context Budget: 400 tokens
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

System prompt:        [████████████████████] ~80 tokens  (always included)
Structured metrics:   [████████████████████] ~80 tokens  (Pinot results)
Semantic chunk 1:     [████████████████████] ~80 tokens  (score: 0.91)
Semantic chunk 2:     [████████████████████] ~80 tokens  (score: 0.84)
Semantic chunk 3:     [████████████████████] ~80 tokens  (score: 0.71)
                      ─────────────────────────────────────────────────
                      Total: 400 tokens ✓

Dropped (over budget):
  Semantic chunk 4:   [░░░░░░░░░░░░░░░░░░░░] ~80 tokens  (score: 0.62) ✗
  Semantic chunk 5:   [░░░░░░░░░░░░░░░░░░░░] ~80 tokens  (score: 0.54) ✗
  ...11 more chunks dropped...

Result: LLM receives focused, relevant context. Quality improves.
```

---

## 5. Retrieval Routing Decision Tree

```
                         User Query
                              │
                              ▼
                    ┌─────────────────┐
                    │ classify_intent │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
          ▼                  ▼                  ▼
   churn_analysis    error_investigation   upgrade_analysis
   retention_analysis                      general
          │                  │                  │
          ▼                  ▼                  ▼
   Pinot: top users    Pinot: error counts  Pinot: upgrade
   by churn_risk       by user/time         funnel metrics
   Vector: behavioral  Vector: error        Vector: feature
   context per user    event context        engagement context
   top_k=5             top_k=3              top_k=3
   freshness=True      freshness=True       freshness=False
```
