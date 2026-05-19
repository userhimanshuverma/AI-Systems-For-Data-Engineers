# Architecture Diagrams: Performance Optimization

## ASCII Diagram: Latency Across AI Architecture

```text
[User Request]
      │
      ▼
┌───────────────┐
│ Router / API  │ (10-50ms) -> High concurrency entry point
└───────┬───────┘
        │
        ├───────────────────────┐ [Cache Hit Path]
        │                       ▼
        │               ┌───────────────┐
        │               │ Semantic Cache│ (20-100ms)
        │               └───────┬───────┘
        │                       │
        ▼ [Cache Miss Path]     │
┌───────────────┐               │
│ Parallel Exec │               │
│ (Asyncio/Go)  │               │
└─┬─────┬─────┬─┘               │
  │     │     │                 │
  │     │     └───────────────┐ │
  ▼     ▼                     ▼ │
[DB]  [Vector DB]  [External API] (200-800ms pipeline latency)
  │     │                     │ │
  └─────┼─────────────────────┘ │
        ▼                       │
┌───────────────┐               │
│ Context Comp. │ (Summarizer/Reranker) (100-300ms)
└───────┬───────┘               │
        │                       │
        ▼                       │
┌───────────────┐               │
│ Model Router  │ (Classify task complexity) (50ms)
└───────┬───────┘               │
        │                       │
  ┌─────┴─────┐                 │
  ▼           ▼                 │
[Fast]      [Heavy]             │
[LLM]       [LLM]               │
(1-3s)      (10-30s)            │
  │           │                 │
  └─────┬─────┘                 │
        ▼                       │
[Streaming Response] <──────────┘
```

---

## Mermaid Diagram: Optimized AI Workflow

```mermaid
graph TD
    User([User Request]) --> API[API Gateway / Load Balancer]
    API --> SemanticCache{Check Semantic Cache}
    
    SemanticCache -- Cache Hit --> ReturnCache[Return Cached Response]
    ReturnCache --> Response([Streaming Response])
    
    SemanticCache -- Cache Miss --> ParallelOps[Async Parallel Coordinator]
    
    ParallelOps --> FetchDB[(Fetch SQL Data)]
    ParallelOps --> FetchVector[(Retrieve Embeddings)]
    ParallelOps --> FetchAPI[Call Third-party APIs]
    
    FetchDB --> MergeContext[Context Merger & Compressor]
    FetchVector --> MergeContext
    FetchAPI --> MergeContext
    
    MergeContext --> Router{Task Complexity Router}
    
    Router -- Simple / Summarization --> FastModel[Fast Model: Llama 3 8B / GPT-4o-mini]
    Router -- Complex / Reasoning --> HeavyModel[Heavy Model: GPT-4o / Claude 3.5 Sonnet]
    
    FastModel --> CacheUpdate[Update Cache]
    HeavyModel --> CacheUpdate
    
    CacheUpdate --> Response
    
    classDef fast fill:#2ecc71,stroke:#27ae60,stroke-width:2px;
    classDef slow fill:#e74c3c,stroke:#c0392b,stroke-width:2px;
    classDef router fill:#f39c12,stroke:#d35400,stroke-width:2px;
    classDef cache fill:#3498db,stroke:#2980b9,stroke-width:2px;
    
    class FastModel,ReturnCache fast;
    class HeavyModel slow;
    class Router,MergeContext router;
    class SemanticCache,CacheUpdate cache;
```
