# AI Systems for Data Engineers — Day 24: Cost Engineering for LLM Systems

Production LLM systems usually fail on economics before they fail on answer quality. Day 24 focuses on architecture decisions that keep quality high while preventing cost blow-ups in real traffic.

## Introduction

Cost engineering is a design responsibility, not a finance afterthought. In production AI systems, spend is created by:

- the number of model calls,
- the number of tokens per call,
- the number of retries/loops,
- and the routing policy between model tiers.

If these are not controlled from day one, scaling users will scale cost faster than business value.

**The Math of AI Scale:** A 10-step agent loop with a heavy model might cost $0.15 per request. At 10,000 Daily Active Users (DAU), that's $1,500/day or **$45,000/month**. Routing 80% of those routine requests to a smaller/cheaper model drops that bill to **$9,000/month**. Cost engineering is the difference between a profitable product and an unsustainable demo.

## Why AI systems fail financially before technically

Many systems reach "acceptable quality" early but still fail in production due to unit economics:

- **Cost multipliers are hidden**: retries, agent loops, and tool chains create more calls than expected.
- **Context grows silently**: retrieval depth and chat history increase token load over time.
- **No budget controls**: orchestration layers optimize only for quality, not cost-per-request.
- **Insufficient observability**: teams track latency and accuracy but not per-stage cost attribution.

The system appears healthy technically while margins erode operationally.

## Where LLM Costs Actually Come From

### 1) Token growth

Per-request token usage accumulates across:

- system instructions,
- conversation history,
- retrieved chunks,
- tool output,
- model response.

Token growth is typically gradual, so costs drift upward unless budgets are enforced.

### 2) Retrieval expansion

Increasing `top_k` and chunk sizes raises prompt size linearly:

- deeper retrieval can improve recall,
- but beyond a point, it adds mostly noise plus cost and latency.

### 3) Retries

Retries from transient failures or parsing issues turn one user request into multiple paid calls.

### 4) Agent loops

Plan-execute-reflect loops are useful but expensive:

- each loop can add retrieval, tool output, and additional model generation.

### 5) Multi-model workflows

Pipelines often include:

- embeddings,
- retrieval/rerank,
- generation,
- validation/summarization.

Even moderate per-step cost can become large at workflow scale.

### 6) Redundant context

Repeatedly sending unchanged policy blocks, duplicate chunks, and irrelevant history is avoidable spend.

## Token Control Strategies

### Context compression

Compress evidence before generation:

- summarize long logs/events into compact state,
- keep only high-signal details required for the answer.

### Relevance ranking

Use ranked retrieval and score thresholds:

- include only chunks that materially improve answer quality.

### Prompt trimming

Reduce static overhead:

- keep instructions precise,
- avoid verbose boilerplate repeated on every request.

### Deduplication

Remove duplicate/near-duplicate context blocks before prompt assembly.

## Caching Strategies

### Response caching

Cache final responses for repeated or deterministic requests.

- best for FAQs and stable summaries
- TTL should match data freshness requirements

### Retrieval caching

Cache retrieval outputs (document IDs/chunks) for repeated query patterns.

- reduces repeated vector/database work

### Embedding caching

Cache embeddings for repeated texts and templates.

- useful in both ingestion and query-time flows

### Native API Prompt Caching

Modern API providers (Anthropic, OpenAI, Google) support caching large context blocks natively.

- **How it works:** You send a large static prompt (like a codebase or long document) once, and subsequent requests reusing that prefix get a 50-80% discount and faster time-to-first-token.
- **When to use:** Heavy system instructions, large few-shot examples, or static reference documents sent with every user message.

### Semantic cache concepts

Cache by meaning, not just exact string:

- retrieve cached answer when semantic similarity passes threshold,
- use conservative thresholds and freshness rules to avoid stale/misaligned reuse.

## Model Routing

### Small vs large model routing

Use smaller API tiers for high-volume routine tasks (classification, extraction, FAQ). Reserve larger tiers for ambiguous, multi-step, or high-stakes reasoning.

### Open-Source & SLM Routing

For strict, repeatable tasks (like intent classification, basic entity extraction, or PII redaction), route requests to locally hosted Open-Source models (e.g., Llama 3 8B) or Small Language Models (SLMs). This drops the marginal cost of these frequent steps to near-zero (only compute).

### Complexity-aware routing

Route using explicit signals:

- estimated input size,
- retrieval depth,
- reasoning complexity,
- tool dependencies,
- SLA and task criticality.

### Cost-aware orchestration

Orchestrators should enforce:

- per-request cost ceilings,
- per-workflow budget caps,
- fallback behavior when projected cost exceeds policy.

## Execution Strategies

### Batch Processing APIs

If a task does not have a strict real-time SLA (e.g., nightly summaries, bulk document classification, offline evaluations), use the Batch API endpoints offered by major providers.

- **Impact:** Typically provides a 50% discount compared to synchronous API calls.
- **Tradeoff:** Responses can take up to 24 hours (though often complete sooner).

## Cost vs Quality Tradeoffs

### Retrieval depth

- Higher depth can increase recall, but also increases token cost and latency.
- Lower depth is cheaper/faster, but may miss edge evidence.

### Context size

- Larger context may improve complex analysis,
- but excessive context can degrade quality due to noise while increasing cost.

### Latency

- Cache hits and smaller tiers reduce latency significantly.
- deep retrieval + large-tier models increase tail latency.

### Model quality

- Larger models help in difficult reasoning cases.
- For routine requests, smaller models are often sufficient with strong retrieval and prompt design.

## Real-World Example: FAQ vs Complex Retention Analysis

The same platform can have very different cost profiles by request type.

### A) FAQ request

Example: "What does churn risk score mean?"

- **Routing**: small model tier
- **Retrieval**: shallow (`top_k=1..2`) or none
- **Cache profile**: high response/semantic cache hit rate
- **Outcome**: low latency, low effective cost, high throughput

### B) Retention analysis request

Example: "Why did enterprise retention drop over 6 weeks?"

- **Routing**: medium/large model tier
- **Retrieval**: deeper (`top_k=5..8`) over metrics + events + notes
- **Cache profile**: low hit rate due to uniqueness
- **Outcome**: higher latency and materially higher per-request cost

### Architecture implication

Do not force both request classes through one uniform path. Separate routing, retrieval depth, and budget policies by workload class.

## Common Cost Mistakes

- Sending full context every time
- No caching strategy
- Using large models for everything
- Recursive agent loops without step/budget guards

## Architecture Diagrams

See `diagrams/architecture.md` for:

- ASCII diagram (caching + routing architecture)
- Mermaid diagram (cost-aware AI workflow)

## Repository Structure

```
day-24-cost-optimization/
├── README.md
├── simulation.html
├── code/
│   ├── token_optimizer.py
│   ├── model_router.py
│   ├── cache_simulation.py
│   └── cost_tracker.py
└── diagrams/
    └── architecture.md
```

## Optional Integration Examples

### 1) Cache-aware retrieval

```python
from code.cache_simulation import RetrievalCache

cache = RetrievalCache(ttl_seconds=300)
key = ("retention_drop", 4)  # (query_signature, top_k)
docs = cache.get(key)
if docs is None:
    docs = retrieve_top_k(query="retention_drop", top_k=4)
    cache.set(key, docs)
```

### 2) Model routing logic

```python
from code.model_router import TaskProfile, ModelRouter

router = ModelRouter()
task = TaskProfile(
    task_type="analysis",
    estimated_input_tokens=1100,
    requires_multi_step_reasoning=True,
    latency_sla_ms=2500,
)
decision = router.route(task)
print(decision.selected_model, decision.reason)
```

### 3) Async cost-aware execution

```python
import asyncio
from code.cost_tracker import CostTracker, StageUsage

async def run_workflow(tracker: CostTracker, workflow_id: str):
    tracker.record(StageUsage(workflow_id, "retrieval", latency_ms=120))
    await asyncio.sleep(0)
    tracker.record(StageUsage(
        workflow_id,
        "generation",
        model_tier="small",
        tokens_in=650,
        tokens_out=180,
        latency_ms=700,
    ))
    if tracker.workflow_cost(workflow_id) > tracker.max_cost_per_workflow:
        return {"status": "aborted", "reason": "budget_exceeded"}
    return {"status": "ok"}
```

## Optional Tool Setup (Minimal)

For local experimentation:

1. Python 3.10+ (no external packages required)
2. Run:
   - `python code/token_optimizer.py`
   - `python code/model_router.py`
   - `python code/cache_simulation.py`
   - `python code/cost_tracker.py`
3. Open `simulation.html` in a browser

## Key Takeaways

- LLM spend is primarily an architecture outcome.
- Highest-impact optimizations come from combining token control, caching, and routing.
- Separate simple and complex request paths.
- Use cost telemetry and guardrails to enforce sustainable unit economics.
