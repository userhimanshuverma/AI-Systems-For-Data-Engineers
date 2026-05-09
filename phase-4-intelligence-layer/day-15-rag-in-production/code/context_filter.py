"""
Context Filter — Day 15: Production RAG
Selects and ranks the most relevant context for the LLM.

No external dependencies. Run standalone:
    python context_filter.py
"""

import math
import hashlib
import time
from typing import Optional


# ---------------------------------------------------------------------------
# Token counting (approximate)
# ---------------------------------------------------------------------------

def count_tokens(text: str) -> int:
    """
    Approximate token count for a text string.

    Rule of thumb: 1 token ≈ 4 characters for English text.
    This matches OpenAI's tokenizer closely enough for budget planning.

    In production: use tiktoken for exact counts.
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Mock embedding (same deterministic approach as hybrid_retrieval.py)
# ---------------------------------------------------------------------------

def _mock_embed(text: str) -> list:
    """Deterministic 16-dim unit vector from text. Same as hybrid_retrieval."""
    import re
    dim = 16
    vec = [0.0] * dim

    h = hashlib.md5(text.lower().encode()).digest()
    for i in range(dim):
        vec[i] += (h[i] - 128) / 128.0

    words = set(re.sub(r"[^a-z0-9\s]", "", text.lower()).split())
    for word in words:
        wh = hashlib.md5(word.encode()).digest()
        for i in range(dim):
            vec[i] += (wh[i % 16] - 128) / 512.0

    magnitude = math.sqrt(sum(x * x for x in vec))
    if magnitude > 0:
        vec = [x / magnitude for x in vec]
    return vec


def _cosine_similarity(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Chunk scoring
# ---------------------------------------------------------------------------

def _recency_score(ts_hours_ago: float) -> float:
    """
    Exponential decay recency score.

    Score = 1.0 at ts_hours_ago=0 (just happened)
    Score = 0.5 at ts_hours_ago=24 (one day ago)
    Score = 0.25 at ts_hours_ago=48 (two days ago)

    Formula: score = exp(-lambda * hours)
    where lambda = ln(2) / half_life_hours
    """
    half_life_hours = 24.0
    lam = math.log(2) / half_life_hours
    return math.exp(-lam * max(0.0, ts_hours_ago))


def _metadata_match_score(chunk_metadata: dict, query_entities: dict) -> float:
    """
    Score how well chunk metadata matches the query entities.

    Checks:
    - user_id match (weight: 0.5)
    - plan match (weight: 0.3)
    - event_type relevance (weight: 0.2)

    Returns a score in [0, 1].
    """
    score = 0.0
    checks = 0

    # User ID match
    if query_entities.get("user_id"):
        checks += 1
        if chunk_metadata.get("user_id") == query_entities["user_id"]:
            score += 0.5

    # Plan match
    if query_entities.get("plan_filter"):
        checks += 1
        if chunk_metadata.get("plan") == query_entities["plan_filter"]:
            score += 0.3

    # Event type relevance (based on intent)
    intent = query_entities.get("intent", "general")
    event_type = chunk_metadata.get("event_type", "")
    intent_event_map = {
        "churn_analysis":     {"churn_signal", "checkout_error", "inactivity", "support_ticket"},
        "error_investigation": {"checkout_error", "support_ticket"},
        "upgrade_analysis":   {"upgrade_intent", "feature_limit"},
        "retention_analysis": {"engagement", "upgrade_intent"},
    }
    relevant_types = intent_event_map.get(intent, set())
    if relevant_types:
        checks += 1
        if event_type in relevant_types:
            score += 0.2

    # If no entity filters were specified, return neutral score
    if checks == 0:
        return 0.5

    return min(1.0, score)


def score_chunk(
    chunk: dict,
    query: str,
    query_entities: Optional[dict] = None,
    recency_weight: float = 0.3,
    similarity_weight: float = 0.5,
    metadata_weight: float = 0.2,
) -> float:
    """
    Score a retrieved chunk for relevance to the query.

    Combines three signals:
        similarity_score  — cosine similarity between query and chunk text
        recency_score     — exponential decay based on ts_hours_ago
        metadata_score    — how well chunk metadata matches query entities

    Args:
        chunk:            Dict with keys: text, metadata (including ts_hours_ago)
        query:            Original query string
        query_entities:   Extracted entities from query_understanding (optional)
        recency_weight:   Weight for recency signal (default: 0.3)
        similarity_weight: Weight for semantic similarity (default: 0.5)
        metadata_weight:  Weight for metadata match (default: 0.2)

    Returns:
        Float in [0, 1]. Higher = more relevant.
    """
    if not (0.99 <= similarity_weight + recency_weight + metadata_weight <= 1.01):
        raise ValueError("Weights must sum to 1.0")

    # Semantic similarity
    query_vec = _mock_embed(query)
    chunk_vec = _mock_embed(chunk.get("text", ""))
    sim = _cosine_similarity(query_vec, chunk_vec)
    # Normalize from [-1,1] to [0,1]
    sim_normalized = (sim + 1.0) / 2.0

    # Recency
    ts_hours_ago = chunk.get("metadata", {}).get("ts_hours_ago", 24.0)
    recency = _recency_score(ts_hours_ago)

    # Metadata match
    meta = _metadata_match_score(
        chunk.get("metadata", {}),
        query_entities or {},
    )

    score = (
        similarity_weight * sim_normalized +
        recency_weight    * recency         +
        metadata_weight   * meta
    )
    return round(min(1.0, max(0.0, score)), 4)


# ---------------------------------------------------------------------------
# Context filtering
# ---------------------------------------------------------------------------

def filter_context(
    structured_metrics: list,
    semantic_chunks: list,
    query: str,
    query_entities: Optional[dict] = None,
    max_tokens: int = 400,
    min_relevance_score: float = 0.30,
) -> dict:
    """
    Select and rank the most relevant context for the LLM.

    Strategy:
    1. Format structured metrics (Pinot rows) as compact text — always included
       up to their token cost.
    2. Score all semantic chunks.
    3. Drop chunks below min_relevance_score.
    4. Deduplicate by event_id.
    5. Fill remaining token budget with highest-scored chunks.
    6. Order: structured metrics first, then semantic chunks by score DESC.

    Args:
        structured_metrics:  List of Pinot result rows (dicts).
        semantic_chunks:     List of vector search results (dicts with text, metadata, score).
        query:               Original query string.
        query_entities:      Extracted entities (optional, improves scoring).
        max_tokens:          Hard token budget for total context.
        min_relevance_score: Drop chunks below this threshold.

    Returns:
        {
            structured_text:   str  — formatted structured metrics
            semantic_selected: list — selected semantic chunks with scores
            total_tokens:      int  — total token count of selected context
            dropped_count:     int  — number of chunks dropped
            budget_remaining:  int  — unused token budget
        }
    """
    # --- Step 1: Format structured metrics ---
    structured_text = _format_structured_metrics(structured_metrics)
    structured_tokens = count_tokens(structured_text)

    remaining_budget = max_tokens - structured_tokens
    if remaining_budget < 0:
        # Structured metrics alone exceed budget — truncate
        structured_text = structured_text[:max_tokens * 4]  # rough char limit
        structured_tokens = count_tokens(structured_text)
        remaining_budget = 0

    # --- Step 2: Score all semantic chunks ---
    scored_chunks = []
    seen_event_ids = set()

    for chunk in semantic_chunks:
        event_id = chunk.get("event_id", "")

        # Deduplicate
        if event_id and event_id in seen_event_ids:
            continue
        if event_id:
            seen_event_ids.add(event_id)

        relevance = score_chunk(chunk, query, query_entities)
        scored_chunks.append({
            **chunk,
            "relevance_score": relevance,
        })

    # --- Step 3: Filter below threshold ---
    before_filter = len(scored_chunks)
    scored_chunks = [c for c in scored_chunks if c["relevance_score"] >= min_relevance_score]
    dropped_by_threshold = before_filter - len(scored_chunks)

    # --- Step 4: Sort by relevance DESC, recency as tiebreaker ---
    scored_chunks.sort(
        key=lambda c: (
            -c["relevance_score"],
            c.get("metadata", {}).get("ts_hours_ago", 999),
        )
    )

    # --- Step 5: Fill token budget ---
    selected = []
    tokens_used = 0
    dropped_by_budget = 0

    for chunk in scored_chunks:
        chunk_tokens = count_tokens(chunk.get("text", ""))
        if tokens_used + chunk_tokens <= remaining_budget:
            selected.append(chunk)
            tokens_used += chunk_tokens
        else:
            dropped_by_budget += 1

    total_tokens = structured_tokens + tokens_used

    return {
        "structured_text":   structured_text,
        "semantic_selected": selected,
        "total_tokens":      total_tokens,
        "dropped_count":     dropped_by_threshold + dropped_by_budget,
        "budget_remaining":  max_tokens - total_tokens,
    }


def _format_structured_metrics(metrics: list) -> str:
    """Format Pinot rows as compact natural language for LLM context."""
    if not metrics:
        return ""

    lines = ["STRUCTURED METRICS (from Pinot):"]
    for row in metrics:
        uid = row.get("user_id", "unknown")
        plan = row.get("plan", "?")
        churn = row.get("churn_risk_score", 0)
        errors = row.get("error_rate", 0)
        sessions = row.get("session_count", 0)
        last_active = row.get("last_active_hours_ago", "?")
        checkout_err = row.get("checkout_errors", 0)
        tickets = row.get("support_tickets", 0)

        line = (
            f"  {uid} ({plan}): churn_risk={churn:.2f}, "
            f"error_rate={errors:.2f}, sessions={sessions}, "
            f"last_active={last_active}h ago"
        )
        if checkout_err > 0:
            line += f", checkout_errors={checkout_err}"
        if tickets > 0:
            line += f", support_tickets={tickets}"
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Context formatting for LLM
# ---------------------------------------------------------------------------

def format_context(filtered: dict) -> str:
    """
    Convert filtered context into a natural language string for the LLM prompt.

    Args:
        filtered: Output of filter_context().

    Returns:
        Formatted context string ready to insert into LLM prompt.
    """
    parts = []

    if filtered.get("structured_text"):
        parts.append(filtered["structured_text"])

    if filtered.get("semantic_selected"):
        parts.append("\nBEHAVIORAL CONTEXT (from Vector Store):")
        for i, chunk in enumerate(filtered["semantic_selected"], 1):
            uid = chunk.get("metadata", {}).get("user_id", "unknown")
            event_type = chunk.get("metadata", {}).get("event_type", "event")
            score = chunk.get("relevance_score", 0)
            text = chunk.get("text", "")
            parts.append(
                f"  [{i}] [{uid}] [{event_type}] (relevance={score:.2f})\n"
                f"      {text}"
            )

    if not parts:
        return "No relevant context found."

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  Context Filter — Day 15: Production RAG")
    print("=" * 70)

    # Simulate 10 chunks coming from vector search
    raw_chunks = [
        {
            "event_id": "evt_001",
            "text": "User u_4821 (free plan) hit checkout error: payment gateway timeout. "
                    "Third occurrence in 2 hours. User viewed /pricing page after error.",
            "metadata": {"user_id": "u_4821", "event_type": "checkout_error",
                         "ts_hours_ago": 1.5, "plan": "free"},
            "score": 0.91,
        },
        {
            "event_id": "evt_002",
            "text": "User u_4821 submitted support ticket: 'Cannot complete purchase, "
                    "keeps failing at payment step.' Severity: high.",
            "metadata": {"user_id": "u_4821", "event_type": "support_ticket",
                         "ts_hours_ago": 1.0, "plan": "free"},
            "score": 0.87,
        },
        {
            "event_id": "evt_003",
            "text": "User u_3302 (free plan) reached feature limit on data exports. "
                    "Viewed /upgrade page for 4 minutes but did not convert.",
            "metadata": {"user_id": "u_3302", "event_type": "feature_limit",
                         "ts_hours_ago": 3.0, "plan": "free"},
            "score": 0.74,
        },
        {
            "event_id": "evt_004",
            "text": "User u_3302 hit checkout error during upgrade attempt. "
                    "Payment declined. User abandoned session.",
            "metadata": {"user_id": "u_3302", "event_type": "checkout_error",
                         "ts_hours_ago": 2.5, "plan": "free"},
            "score": 0.71,
        },
        {
            "event_id": "evt_005",
            "text": "User u_9901 (free plan) has 4 checkout errors and 3 support tickets "
                    "in the last 72 hours. Last session: 3 days ago. High churn risk.",
            "metadata": {"user_id": "u_9901", "event_type": "churn_signal",
                         "ts_hours_ago": 4.0, "plan": "free"},
            "score": 0.68,
        },
        {
            "event_id": "evt_006",
            "text": "User u_7741 (free plan) has been inactive for 42 hours. "
                    "Last action: viewed /features comparison page. No errors recorded.",
            "metadata": {"user_id": "u_7741", "event_type": "inactivity",
                         "ts_hours_ago": 42.0, "plan": "free"},
            "score": 0.55,
        },
        {
            "event_id": "evt_007",
            "text": "User u_8812 (pro plan) completed 22 sessions this week. "
                    "Heavy API usage, no errors. Engaged with advanced analytics features.",
            "metadata": {"user_id": "u_8812", "event_type": "engagement",
                         "ts_hours_ago": 0.5, "plan": "pro"},
            "score": 0.42,
        },
        {
            "event_id": "evt_008",
            "text": "User u_2244 (pro plan) hit 2 checkout errors when attempting to "
                    "add team members. Submitted support ticket about billing issue.",
            "metadata": {"user_id": "u_2244", "event_type": "checkout_error",
                         "ts_hours_ago": 6.0, "plan": "pro"},
            "score": 0.38,
        },
        {
            "event_id": "evt_009",
            "text": "User u_1190 (free plan) has 7 sessions this week with 44 page views. "
                    "Consistently views /pricing and /compare pages. Upgrade intent signal.",
            "metadata": {"user_id": "u_1190", "event_type": "upgrade_intent",
                         "ts_hours_ago": 2.0, "plan": "free"},
            "score": 0.35,
        },
        {
            "event_id": "evt_010",
            "text": "User u_5503 (free plan) is highly active: 12 sessions, 67 page views. "
                    "No errors. Engages with collaboration features daily. Low churn risk.",
            "metadata": {"user_id": "u_5503", "event_type": "engagement",
                         "ts_hours_ago": 1.0, "plan": "free"},
            "score": 0.22,   # below threshold — should be dropped
        },
    ]

    # Simulate structured metrics from Pinot
    structured_metrics = [
        {
            "user_id": "u_4821", "plan": "free", "error_rate": 0.34,
            "session_count": 2, "last_active_hours_ago": 18,
            "churn_risk_score": 0.91, "checkout_errors": 3, "support_tickets": 2,
        },
        {
            "user_id": "u_3302", "plan": "free", "error_rate": 0.21,
            "session_count": 4, "last_active_hours_ago": 6,
            "churn_risk_score": 0.78, "checkout_errors": 1, "support_tickets": 1,
        },
        {
            "user_id": "u_9901", "plan": "free", "error_rate": 0.44,
            "session_count": 1, "last_active_hours_ago": 72,
            "churn_risk_score": 0.88, "checkout_errors": 4, "support_tickets": 3,
        },
    ]

    query = "Which free-plan users are most at risk this week and why?"
    query_entities = {
        "intent":         "churn_analysis",
        "user_id":        None,
        "plan_filter":    "free",
        "time_range_hours": 168,
    }

    print(f"\n  Query: {query}")
    print(f"  Input: {len(raw_chunks)} semantic chunks + {len(structured_metrics)} Pinot rows")
    print(f"  Token budget: 400 tokens")

    # --- Score individual chunks ---
    print(f"\n{'─'*70}")
    print("  Individual chunk scores:")
    for chunk in raw_chunks:
        s = score_chunk(chunk, query, query_entities)
        status = "✓" if s >= 0.30 else "✗ (dropped)"
        print(f"    [{chunk['event_id']}] relevance={s:.3f} {status} | "
              f"{chunk['text'][:55]}...")

    # --- Filter context ---
    print(f"\n{'─'*70}")
    t0 = time.perf_counter()
    filtered = filter_context(
        structured_metrics=structured_metrics,
        semantic_chunks=raw_chunks,
        query=query,
        query_entities=query_entities,
        max_tokens=400,
        min_relevance_score=0.30,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"\n  Filter results:")
    print(f"    Input chunks:    {len(raw_chunks)}")
    print(f"    Selected chunks: {len(filtered['semantic_selected'])}")
    print(f"    Dropped chunks:  {filtered['dropped_count']}")
    print(f"    Total tokens:    {filtered['total_tokens']} / 400")
    print(f"    Budget remaining:{filtered['budget_remaining']} tokens")
    print(f"    Filter time:     {elapsed_ms:.2f}ms")

    # --- Format for LLM ---
    print(f"\n{'─'*70}")
    print("  Formatted context for LLM:")
    print()
    formatted = format_context(filtered)
    for line in formatted.split("\n"):
        print(f"    {line}")

    # Assertions
    assert filtered["total_tokens"] <= 400, \
        f"Token budget exceeded: {filtered['total_tokens']} > 400"
    assert len(filtered["semantic_selected"]) < len(raw_chunks), \
        "Expected filtering to reduce chunk count"
    assert len(filtered["semantic_selected"]) >= 1, \
        "Expected at least 1 chunk to be selected"
    assert filtered["dropped_count"] > 0, \
        "Expected at least 1 chunk to be dropped"
    assert "STRUCTURED METRICS" in formatted, \
        "Expected structured metrics in formatted output"
    assert "BEHAVIORAL CONTEXT" in formatted, \
        "Expected behavioral context in formatted output"

    print(f"\n{'─'*70}")
    print(f"  ✓ All assertions passed")
    print(f"  ✓ Reduced {len(raw_chunks)} chunks → {len(filtered['semantic_selected'])} "
          f"(dropped {filtered['dropped_count']})")
    print("=" * 70)
