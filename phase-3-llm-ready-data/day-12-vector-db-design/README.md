# Day 12 — Vector Storage Design

> Phase 3 — Making Data LLM-Ready

## Introduction

Vector storage design determines retrieval quality. A poorly designed vector store returns irrelevant chunks. A well-designed one returns exactly the right context for the LLM.

This is not a theoretical concern. In production RAG systems, the difference between a 512-token chunk with 50-token overlap and a naive 1024-token chunk can mean the difference between a support assistant that resolves tickets and one that hallucinates answers. Every design decision — chunk size, index type, update strategy — has a measurable impact on what the LLM sees.

---

## What is Vector Storage?

A vector database stores dense numerical vectors (embeddings) alongside metadata and enables retrieval by semantic similarity rather than keyword matching.

**Core components:**
- **Vectors**: Dense float arrays (e.g., 1536 dimensions for OpenAI `text-embedding-3-small`) representing the semantic meaning of a text chunk
- **Metadata**: Structured fields stored alongside each vector — `user_id`, `event_type`, `timestamp`, `source_doc_id`
- **Index**: A data structure that enables fast approximate nearest neighbor (ANN) search over millions of vectors
- **Payload filtering**: Pre-filter vectors by metadata before running similarity search

**Role in AI systems:**

```
User Query → Embedding Model → Query Vector
                                    ↓
                            Vector Store (ANN Search)
                                    ↓
                         Top-K Relevant Chunks
                                    ↓
                              LLM Context Window
                                    ↓
                              Generated Answer
```

The vector store is the retrieval layer between your data and the LLM. It answers the question: *"Given this query, which pieces of stored knowledge are most relevant?"*

**Common production options:**

| System | Type | Best For |
|--------|------|----------|
| Qdrant | Dedicated vector DB | Production RAG, filtering |
| Pinecone | Managed cloud | Serverless, low ops overhead |
| Weaviate | Vector DB + graph | Multi-modal, hybrid search |
| pgvector | PostgreSQL extension | Existing Postgres stack |
| Chroma | Embedded / local | Development, prototyping |

---

## Chunking Strategy

### Why Chunking is Needed

LLMs have context window limits. GPT-4 Turbo supports 128K tokens, but you cannot stuff an entire knowledge base into every prompt — it would be prohibitively expensive and would dilute the relevant signal. Instead:

1. Documents are split into smaller **chunks** at index time
2. Each chunk gets its own embedding vector
3. At query time, only the most relevant chunks are retrieved
4. Those chunks fill the LLM's context window

The chunking strategy determines what semantic unit each embedding represents. Get it wrong and your embeddings represent incoherent fragments.

---

### Fixed-Size Chunking

Split text every N tokens regardless of content boundaries.

```
Input: "User clicked checkout. Payment failed. Error code 402. User retried..."
Chunk 1 (512 tok): "User clicked checkout. Payment failed. Error code 402. User retried..."
Chunk 2 (512 tok): "...retried three times. Session expired. User contacted support..."
```

**Pros:**
- Simple to implement
- Predictable chunk sizes
- Easy to reason about cost (tokens per chunk × number of chunks)

**Cons:**
- Splits mid-sentence, destroying semantic coherence
- Context lost at chunk boundaries

**Solution — overlap:** Include the last N tokens of the previous chunk at the start of the next chunk. This ensures boundary context is preserved.

```
Chunk 1: [tokens 0–511]
Chunk 2: [tokens 462–973]   ← 50-token overlap with chunk 1
Chunk 3: [tokens 924–1435]  ← 50-token overlap with chunk 2
```

---

### Semantic Chunking

Split at natural language boundaries: paragraph breaks, section headers, sentence endings.

```
Input: "User clicked checkout.\n\nPayment failed with error 402.\n\nUser contacted support."
Chunk 1: "User clicked checkout."
Chunk 2: "Payment failed with error 402."
Chunk 3: "User contacted support."
```

**Pros:**
- Each chunk contains a complete semantic unit
- Better embedding quality — the model encodes coherent meaning
- Higher retrieval precision for structured documents

**Cons:**
- Variable chunk sizes (some chunks may be very short or very long)
- More complex to implement
- Requires document structure awareness

**Best for:** Support tickets, articles, documentation, structured reports.

---

### Chunk Size Tradeoffs

| Chunk Size | Precision | Recall | Cost | Use Case |
|------------|-----------|--------|------|----------|
| Small (128 tok) | High | Low | High | Specific fact lookup, Q&A |
| Medium (512 tok) | Balanced | Balanced | Medium | General RAG, support assistants |
| Large (1024 tok) | Low | High | Low | Broad context, summarization |

**Precision** = the retrieved chunk contains exactly the answer  
**Recall** = the answer is somewhere in the retrieved chunks  
**Cost** = number of chunks × embedding API calls

**Rule of thumb for this series:**
- User event streams: each event is its own "chunk" — no splitting needed. Events are already atomic semantic units.
- Support tickets and articles: use 512-token chunks with 50-token overlap.
- Long-form documents (runbooks, wikis): use semantic chunking at paragraph boundaries.

---

## Indexing Strategy

### Why Indexing is Needed

Without an index, finding the nearest neighbor to a query vector requires computing cosine similarity against every stored vector — brute-force search.

**Brute-force cost:**
- 1M vectors × 1536 dimensions = 1.536 billion float multiplications per query
- At ~10 GFLOPS: ~150ms per query (single-threaded)
- Unacceptable for interactive applications

**ANN indexes** trade a small accuracy loss for orders-of-magnitude speed improvement by pre-building a navigable data structure.

---

### HNSW (Hierarchical Navigable Small World)

HNSW is the dominant ANN algorithm in production vector databases. Qdrant, Pinecone, Weaviate, and Chroma all use it by default.

**How it works:**

HNSW builds a multi-layer graph:
- **Layer 0**: All nodes, densely connected to nearest neighbors
- **Layer 1**: A subset of nodes, sparser connections
- **Layer 2+**: Progressively fewer nodes, long-range connections

```
Layer 2:  A ————————————————— F
Layer 1:  A ——— C ——— E ——— F
Layer 0:  A — B — C — D — E — F — G
```

**Search algorithm:**
1. Enter at the top layer at a random entry point
2. Greedily navigate toward the query vector
3. Drop to the next layer and repeat
4. At layer 0, perform a local beam search to find top-K neighbors

**Complexity:** O(log N) per query vs O(N) for brute force.

---

### Index Parameters

| Parameter | Effect | Typical Value |
|-----------|--------|---------------|
| `ef_construction` | Build quality vs build speed. Higher = better index, slower build | 128–256 |
| `m` (connections per node) | Memory usage vs search accuracy. Higher = more memory, better recall | 16–32 |
| `ef` (search beam width) | Query quality vs query speed. Higher = better recall, slower search | 64–128 |

**Tuning guidance:**
- Start with `m=16`, `ef_construction=128`, `ef=64`
- If recall is too low, increase `ef` first (no rebuild needed)
- If build time is too slow, decrease `ef_construction`
- If memory is constrained, decrease `m`

---

### Impact on Performance

| Scenario | Vectors | Dimensions | Latency |
|----------|---------|------------|---------|
| Brute force | 1M | 1536 | ~6,000ms |
| HNSW (m=16, ef=64) | 1M | 1536 | ~5ms |
| HNSW (m=32, ef=128) | 1M | 1536 | ~12ms |

**Tradeoff:** ~5% accuracy loss (recall@10 drops from 100% to ~95%) for a 1,200x speed improvement.

For most RAG applications, 95% recall is acceptable — the LLM can handle minor retrieval imperfections. The 5ms latency is not negotiable for interactive systems.

---

## Update Strategy

### Why Embeddings Become Stale

Embeddings are not static. They become stale when:

1. **User behavior changes** — a user who previously had `churn_risk: low` now has `churn_risk: high`. Their embedding should reflect the updated enrichment.
2. **Enrichment data changes** — the feature engineering pipeline produces new values for `session_count`, `error_rate`, `plan_tier`.
3. **Embedding model is upgraded** — switching from `text-embedding-ada-002` to `text-embedding-3-small` changes the vector space entirely. All vectors must be regenerated.
4. **Context engineering logic changes** — if you change how events are serialized to text before embedding, existing vectors represent a different format than new ones.

Stale embeddings are dangerous because they fail silently. The system continues to return results — just wrong ones.

---

### Full Re-embedding

Delete all vectors and regenerate from scratch.

```
1. Spin up new collection (blue/green)
2. Re-embed all documents with new model/logic
3. Swap traffic to new collection
4. Delete old collection
```

**When to use:**
- Embedding model upgrade
- Major schema change in the text serialization format
- Corruption detected in existing vectors

**Cost:** High — proportional to total collection size. For 10M events at $0.0001/1K tokens, a full reindex costs ~$1,000.

**Downtime:** Requires blue/green deployment to avoid serving stale vectors during reindex.

---

### Incremental Updates

Track a `content_hash` (MD5 or SHA-256) for each document. Re-embed only when the hash changes.

```python
content_hash = md5(serialize_event(event))
if stored_hash != content_hash:
    new_vector = embed(serialize_event(event))
    vector_store.upsert(doc_id, new_vector, metadata)
    hash_store.update(doc_id, content_hash)
else:
    skip()  # Vector is still valid
```

**When to use:**
- Individual document updates (enrichment field changes)
- Nightly batch refresh of changed records

**Cost:** Low — only changed documents are re-embedded. In practice, 1–5% of documents change per day.

---

### Event-Driven Updates

A Kafka consumer triggers re-embedding whenever a new or updated event arrives.

```
Kafka Topic: user-events
    ↓
Consumer: check content_hash
    ↓ (changed)
Embedding Service: generate new vector
    ↓
Vector Store: upsert
```

**When to use:**
- Streaming event data where freshness matters
- Near real-time RAG (support assistant needs current user state)

**Latency:** Seconds from event production to vector availability.

---

## Real-World Example: SaaS Support Assistant

### Collection Design

```python
collection = {
    "name": "user_behavior_v2",
    "vector_size": 1536,          # text-embedding-3-small
    "distance": "Cosine",
    "hnsw_config": {
        "m": 16,
        "ef_construction": 128,
        "ef": 64
    }
}
```

### Chunk Strategy

**User events** (atomic, no splitting):
```python
event_text = f"""
user_id: {event['user_id']}
event_type: {event['event_type']}
timestamp: {event['timestamp']}
properties: {json.dumps(event['properties'])}
enrichment: plan={event['plan_tier']}, churn_risk={event['churn_risk']}
"""
# Each event → 1 chunk → 1 embedding
```

**Support tickets** (512-token chunks, 50-token overlap):
```python
chunks = fixed_size_chunk(ticket_text, chunk_size=512, overlap=50)
for i, chunk in enumerate(chunks):
    vector_store.upsert(
        doc_id=f"{ticket_id}_chunk_{i}",
        vector=embed(chunk),
        metadata={"ticket_id": ticket_id, "chunk_index": i, "user_id": user_id}
    )
```

### Index Configuration

```python
# Qdrant example
client.create_collection(
    collection_name="user_behavior_v2",
    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
    hnsw_config=HnswConfigDiff(m=16, ef_construct=128, on_disk=False)
)
```

### Update Triggers

| Trigger | Strategy | Frequency |
|---------|----------|-----------|
| New user event | Event-driven (Kafka) | Real-time |
| Enrichment update | Incremental (hash check) | Hourly batch |
| Model upgrade | Full reindex (blue/green) | Quarterly |
| Schema change | Full reindex (blue/green) | As needed |

---

## Common Mistakes

**1. Random chunking — splitting mid-sentence**  
Splitting at fixed byte offsets or character counts without respecting token or sentence boundaries destroys semantic coherence. The embedding model encodes a fragment that means nothing in isolation. Always split at token boundaries at minimum; prefer sentence or paragraph boundaries.

**2. No update pipeline — stale embeddings**  
Embedding once at ingest and never updating is the most common production mistake. User behavior changes, enrichment data changes, and the embedding model gets upgraded. Without an update pipeline, your vector store silently drifts from reality. Implement hash-based change detection from day one.

**3. Ignoring index configuration — default settings**  
Default HNSW settings (`m=16`, `ef_construction=100`) are reasonable starting points but may not suit your data distribution. High-dimensional sparse data benefits from higher `m`. Low-latency requirements need lower `ef`. Always benchmark with your actual data before going to production.

**4. Mixing embedding models**  
Query vectors and document vectors must be generated by the same model. If you upgrade the embedding model for new documents but leave old documents with vectors from the previous model, similarity scores become meaningless — you're comparing vectors in different geometric spaces. Full reindex is mandatory on model upgrades.

**5. No metadata filtering — searching all vectors**  
Searching all 10M vectors when you only need results for `user_id=abc123` wastes compute and degrades precision. Always add metadata filters to scope the search. In Qdrant: `filter=Filter(must=[FieldCondition(key="user_id", match=MatchValue(value="abc123"))])`.

**6. Chunk size mismatch between index and query**  
If documents are chunked at 512 tokens but queries are short (10–20 tokens), the embedding spaces may not align well. Consider using asymmetric embedding models (e.g., `e5-large`) that are trained with different encoders for queries vs documents.

---

## Key Takeaways

1. **Chunking strategy directly determines retrieval quality.** Semantic chunking at natural boundaries outperforms fixed-size chunking for structured documents. For event streams, each event is already an atomic chunk.

2. **HNSW gives you 1,000x speed improvement with ~5% accuracy loss.** For interactive RAG systems, this tradeoff is always worth taking. Tune `ef` at query time to balance recall vs latency without rebuilding the index.

3. **Embeddings become stale.** Implement content hash tracking from day one. Re-embed on change, not on schedule. Full reindex is only needed for model upgrades and major schema changes.

4. **Metadata filtering is not optional.** In multi-tenant systems, always filter by `user_id` or `tenant_id` before similarity search. It improves both precision and security.

5. **The embedding model is a contract.** Query vectors and document vectors must use the same model. Treat a model upgrade as a breaking schema change — it requires a full reindex with blue/green deployment.

6. **Design for the update pipeline before you design the index.** The hardest part of vector storage in production is not the initial indexing — it's keeping vectors fresh as data changes. Plan your update strategy before you write the first embedding.

---

## What's Next

**Day 13 — Data Freshness in RAG Systems**

We'll go deeper on the update problem: how to detect staleness, how to build a freshness SLA, and how to design a pipeline that keeps your vector store synchronized with your operational data in near real-time.

Topics: change data capture (CDC) for vector updates, freshness metrics, staleness detection, the dual-write pattern, and handling embedding model migrations without downtime.
