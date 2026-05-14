# Day 21 — Async vs Sync Architectures

> **Phase 5 — Orchestration & Reliability**
> Synchronous systems are simple until they're not. Asynchronous systems are complex until they're the only thing that works at scale.

---

## Introduction

Every AI system starts synchronous. A request comes in, the system processes it, a response goes out. Simple, debuggable, fast to build.

Then traffic grows. The LLM call takes 800ms. The embedding lookup takes 50ms. The Pinot query takes 70ms. Under 10 requests/second, this is fine. Under 1,000 requests/second, every slow component becomes a bottleneck that blocks everything behind it.

This is where architecture matters more than code. The question is not "how do I make this faster?" — it's "which parts of this system need to respond immediately, and which parts can be decoupled?"

---

## What is a Sync Architecture?

A synchronous architecture processes each request in a **blocking, sequential flow**. The caller waits for the entire operation to complete before receiving a response.

```
Client → API → [Query Pinot] → [Search Vectors] → [Call LLM] → Response
         ↑                                                          ↓
         └──────────────── waits ~700ms ────────────────────────────┘
```

**Properties:**
- Simple to reason about — one request, one response, one thread
- Easy to debug — the call stack is linear
- Low latency for simple operations
- Blocks the caller for the full duration
- Does not scale well under high concurrency

**When sync works:**
- User-facing queries that need an immediate response
- Operations that complete in < 200ms
- Low-volume workflows (< 100 req/sec)
- Simple pipelines with no fan-out

**When sync breaks:**
- Long-running operations (LLM calls, batch embedding)
- High-concurrency workloads
- Operations with variable latency (external APIs)
- Fan-out patterns (one request triggers many downstream calls)

---

## What is an Async Architecture?

An asynchronous architecture **decouples the producer of work from the consumer of work** using a queue or message bus.

```
Client → API → [Enqueue task] → Response (202 Accepted)
                    │
                    ▼
              [Queue / Kafka]
                    │
                    ▼
              [Worker pool]
              ├── Worker 1: process task A
              ├── Worker 2: process task B
              └── Worker 3: process task C
                    │
                    ▼
              [Result store / callback]
```

**Properties:**
- Producer and consumer are decoupled — neither blocks the other
- Workers process at their own pace
- Queue absorbs traffic spikes (backpressure buffer)
- Failures are isolated — a failed task doesn't block other tasks
- More complex to debug — no linear call stack
- Requires result delivery mechanism (polling, webhook, WebSocket)

**When async works:**
- Long-running operations (embedding refresh, LLM batch processing)
- High-volume workloads that exceed single-server capacity
- Operations where the caller doesn't need an immediate result
- Fan-out patterns (one event triggers many independent workers)
- Retry-heavy workflows (external API calls with variable reliability)

---

## Real-World Tradeoffs

| Dimension | Synchronous | Asynchronous |
|-----------|-------------|--------------|
| **Latency** | Low for fast ops, high for slow ops | Consistent (queue adds ~10ms overhead) |
| **Throughput** | Limited by slowest component | Scales with worker count |
| **Reliability** | Single point of failure | Isolated failures, retryable |
| **Scalability** | Vertical (bigger server) | Horizontal (more workers) |
| **Complexity** | Low | Medium–High |
| **Debugging** | Easy (linear stack) | Harder (distributed trace) |
| **Result delivery** | Immediate | Polling / callback / WebSocket |
| **Backpressure** | Caller blocks | Queue absorbs, workers drain |

### The Key Insight

Sync and async are not alternatives — they're **complementary patterns** for different parts of the same system:

```
User query → [SYNC] → immediate response (< 200ms)
                │
                └── [ASYNC] → background enrichment, re-embedding, alerts
```

The user gets an immediate response. The heavy work happens in the background.

---

## What is Backpressure?

Backpressure is what happens when a downstream system cannot process work as fast as an upstream system produces it.

### Queue Buildup

```
Producer rate:  1,000 tasks/second
Worker rate:    800 tasks/second
Queue growth:   +200 tasks/second

After 60 seconds: 12,000 tasks in queue
After 5 minutes:  60,000 tasks in queue
After 1 hour:     720,000 tasks in queue → queue full → tasks dropped
```

### Downstream Slowdown

A slow downstream component (LLM API, vector store) causes workers to hold tasks longer. This reduces effective worker throughput, which causes the queue to grow, which causes more workers to be needed.

```
Normal:   Worker processes task in 100ms → 10 tasks/sec/worker
Slow LLM: Worker processes task in 800ms → 1.25 tasks/sec/worker
          → Need 8x more workers to maintain throughput
          → Or queue grows until LLM recovers
```

### Cascading Latency

In a sync system, backpressure cascades upstream:
```
LLM slow → Retrieval layer waits → API waits → Client waits → Timeout
```

In an async system, backpressure is absorbed by the queue:
```
LLM slow → Workers slow → Queue grows → Producer still responds fast
         → Alert fires when queue depth > threshold
         → Scale workers or throttle producer
```

### Handling Backpressure

1. **Queue depth monitoring** — alert when queue depth exceeds threshold
2. **Worker autoscaling** — add workers when queue grows
3. **Producer throttling** — slow down production when queue is full
4. **Priority queues** — process high-priority tasks first
5. **Dead letter queues** — move permanently failed tasks out of the main queue

---

## Retry Systems

### Why Retries Are Necessary

External systems fail transiently. The OpenAI API returns a 429 (rate limit). The Qdrant connection times out. The Pinot broker restarts. These are not permanent failures — they resolve within seconds or minutes. Retrying handles them automatically.

### Exponential Backoff

Retry immediately after the first failure, then wait progressively longer:

```
Attempt 1: fails → wait 1s
Attempt 2: fails → wait 2s
Attempt 3: fails → wait 4s
Attempt 4: fails → wait 8s
Attempt 5: fails → dead letter queue
```

Why exponential? If many workers are hitting the same failing service, immediate retries create a thundering herd — all workers retry simultaneously, overwhelming the recovering service. Exponential backoff spreads retries over time.

### Jitter

Add random jitter to backoff to prevent synchronized retries:
```python
delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
```

### Dead Letter Queues

Tasks that fail after all retries go to a dead letter queue (DLQ). The DLQ:
- Prevents failed tasks from blocking the main queue
- Stores failed tasks for manual investigation
- Can be replayed after the root cause is fixed

### Idempotency

Retried tasks must be safe to re-execute. If a task partially succeeded before failing, re-running it should not create duplicates.

```python
# Non-idempotent (dangerous to retry):
def insert_embedding(doc_id, vector):
    db.insert({"id": doc_id, "vector": vector})  # fails if doc_id exists

# Idempotent (safe to retry):
def upsert_embedding(doc_id, vector):
    db.upsert({"id": doc_id, "vector": vector})  # insert or update
```

---

## Where This Fits in AI Systems

### Embedding Refresh Jobs
**Pattern:** Async
**Why:** Embedding 10,000 documents takes minutes. The caller (Airflow scheduler) doesn't need to wait. Workers process batches independently. Failures are retried per-batch.

### Retrieval Workflows
**Pattern:** Sync for user-facing queries, Async for background enrichment
**Why:** A support agent needs a response in < 1 second (sync). Re-embedding updated documents can happen in the background (async).

### Agent Orchestration
**Pattern:** Async for long-running agents
**Why:** A root cause analysis agent may take 30+ seconds. The API returns a job ID immediately. The client polls for results or receives a webhook when done.

### Long-Running Reasoning Tasks
**Pattern:** Async with result store
**Why:** Batch LLM analysis of 1,000 users cannot be done synchronously. Tasks are queued, workers process them, results are stored. The caller retrieves results when ready.

---

## Real-World Example — Retention Analysis Workflow

**Scenario:** Support team requests a retention analysis for all at-risk users.

### Synchronous Approach (fails at scale)
```
POST /analyze-retention
  → Query Pinot (50ms)
  → For each of 1,653 at-risk users:
      → Search vectors (50ms)
      → Call LLM (500ms)
  → Return results

Total time: 1,653 × 550ms = ~15 minutes
Client timeout: 30 seconds
Result: 504 Gateway Timeout
```

### Asynchronous Approach (production pattern)
```
POST /analyze-retention
  → Validate request
  → Enqueue job: {type: "retention_analysis", user_count: 1653}
  → Return: {job_id: "job_001", status: "queued", poll_url: "/jobs/job_001"}
  Response time: ~50ms

[Background workers]
  Worker 1: process users 1–100 (55s)
  Worker 2: process users 101–200 (55s)
  ...
  Worker 16: process users 1601–1653 (30s)
  Total wall time: ~60 seconds (16 parallel workers)

GET /jobs/job_001
  → {status: "completed", results_url: "/results/job_001"}
```

The client gets an immediate response. The work happens in parallel. The total wall time is 60 seconds instead of 15 minutes.

---

## Common Mistakes

### 1. Everything Synchronous
```
❌ Route all operations through sync API, including batch LLM calls
✅ Identify which operations need immediate response vs can be deferred
   User queries: sync. Batch analysis: async.
```

### 2. Infinite Retries
```
❌ Retry forever until success
✅ Set max_retries=5. After that, dead letter queue + alert.
   Infinite retries mask permanent failures and fill queues.
```

### 3. No Queue Monitoring
```
❌ Deploy async workers with no queue depth monitoring
✅ Alert when queue depth > threshold (e.g., > 10,000 tasks)
   A growing queue is the first sign of a downstream problem.
```

### 4. No Backpressure Handling
```
❌ Producer publishes at full speed regardless of queue depth
✅ Implement producer throttling when queue depth exceeds limit
   Or use Kafka consumer lag as a signal to slow down producers.
```

### 5. Non-Idempotent Tasks
```
❌ Tasks that insert (not upsert) — duplicates on retry
✅ All async tasks must be idempotent. Use upsert semantics.
   Assume every task will be retried at least once.
```

---

## Key Takeaways

1. **Sync is simple, async is scalable.** Use sync for user-facing queries that need immediate responses. Use async for heavy background work.

2. **Queues absorb traffic spikes.** A queue between producer and consumer means neither blocks the other. The queue grows during spikes and drains when load decreases.

3. **Backpressure is a signal, not a failure.** A growing queue means downstream is slower than upstream. Monitor it, alert on it, and scale workers in response.

4. **Retries with exponential backoff handle transient failures.** Add jitter to prevent thundering herd. Set a max retry limit. Use dead letter queues for permanent failures.

5. **All async tasks must be idempotent.** Assume every task will be retried. Use upsert semantics. Never assume a task ran exactly once.

6. **The pattern is: sync for the response, async for the work.** Return a job ID immediately. Process in the background. Deliver results via polling or webhook.

---

## What's Next

**Day 22** — Failure Modes: cataloging how AI data systems fail and designing for graceful degradation.

---

*Part of the [AI Systems for Data Engineers](../../README.md) — 28-Day Roadmap*
