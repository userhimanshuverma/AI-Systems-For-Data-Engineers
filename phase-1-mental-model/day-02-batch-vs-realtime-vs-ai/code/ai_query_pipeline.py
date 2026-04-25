"""
AI Query Pipeline — Day 02
============================
Demonstrates the AI system paradigm: query → retrieval → LLM reasoning.

Pattern:
  - A natural language query arrives (from a user or agent)
  - Query is parsed for intent and entities
  - Relevant context is retrieved from two sources:
      1. Vector store (semantic similarity over event descriptions)
      2. Structured store (recent metrics from Pinot/SQL — simulated)
  - Context is assembled into a prompt
  - LLM reasons over the context and generates a response

Key property: probabilistic. The LLM does NOT compute — it reasons.
Never ask an LLM to aggregate numbers. Always compute first, then reason.
"""

import math
import random
from datetime import datetime, timedelta


# ── MOCK EMBEDDING ────────────────────────────────────────────────────────────

def embed(text: str) -> list[float]:
    """
    Mocks a text embedding model (e.g., text-embedding-3-small).
    In production: openai.embeddings.create(input=text, model="text-embedding-3-small")
    Uses a seeded random for reproducibility in this demo.
    """
    random.seed(hash(text) % (2 ** 32))
    vec = [random.gauss(0, 1) for _ in range(16)]
    norm = math.sqrt(sum(x ** 2 for x in vec))
    return [x / norm for x in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # pre-normalized


# ── IN-MEMORY VECTOR STORE ────────────────────────────────────────────────────

class VectorStore:
    """
    Minimal in-memory vector store.
    In production: Pinecone, Qdrant, Weaviate, or pgvector.
    """
    def __init__(self):
        self._docs: list[dict] = []

    def upsert(self, doc_id: str, text: str, metadata: dict) -> None:
        self._docs.append({
            "id": doc_id,
            "text": text,
            "vector": embed(text),
            "metadata": metadata,
        })

    def query(self, query_text: str, top_k: int = 4,
              filter_fn=None) -> list[dict]:
        qv = embed(query_text)
        results = []
        for doc in self._docs:
            if filter_fn and not filter_fn(doc["metadata"]):
                continue
            score = cosine_similarity(qv, doc["vector"])
            results.append({**doc, "score": round(score, 4)})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


# ── SIMULATED STRUCTURED STORE (Pinot / SQL) ──────────────────────────────────

STRUCTURED_METRICS = {
    "u_001": {"page_views_7d": 14, "errors_7d": 3, "purchases_7d": 0, "plan": "free",  "churn_risk": "high"},
    "u_002": {"page_views_7d": 42, "errors_7d": 0, "purchases_7d": 2, "plan": "pro",   "churn_risk": "low"},
    "u_003": {"page_views_7d": 5,  "errors_7d": 1, "purchases_7d": 0, "plan": "free",  "churn_risk": "medium"},
}

def query_structured_store(user_id: str) -> dict | None:
    """
    Fetches pre-computed metrics for a user.
    In production: SELECT * FROM pinot.user_metrics_7d WHERE user_id = :uid
    This is computed by the batch/real-time layer — NOT by the LLM.
    """
    return STRUCTURED_METRICS.get(user_id)


# ── SEED VECTOR STORE WITH EVENTS ─────────────────────────────────────────────

def seed_vector_store(store: VectorStore) -> None:
    """
    Populates the vector store with event descriptions.
    In production: this runs as an embedding pipeline triggered by new events.
    """
    now = datetime.now()
    events = [
        ("u_001", "page_view",    "/pricing",  now - timedelta(days=1, hours=2)),
        ("u_001", "page_view",    "/pricing",  now - timedelta(days=1, hours=1)),
        ("u_001", "error",        "/checkout", now - timedelta(hours=20)),
        ("u_001", "error",        "/checkout", now - timedelta(hours=18)),
        ("u_001", "support_msg",  "Your checkout keeps failing with a 500 error.", now - timedelta(hours=16)),
        ("u_001", "page_view",    "/home",     now - timedelta(hours=10)),
        ("u_002", "purchase",     "/checkout", now - timedelta(days=2)),
        ("u_002", "page_view",    "/docs",     now - timedelta(hours=5)),
        ("u_003", "signup",       "/register", now - timedelta(days=3)),
        ("u_003", "page_view",    "/home",     now - timedelta(hours=30)),
    ]

    for i, (uid, etype, detail, ts) in enumerate(events):
        text = (
            f"User {uid} performed '{etype}' "
            f"on '{detail}' at {ts.strftime('%Y-%m-%d %H:%M')} UTC."
        )
        store.upsert(
            doc_id=f"evt_{i:03d}",
            text=text,
            metadata={"user_id": uid, "event_type": etype},
        )


# ── QUERY PARSER ──────────────────────────────────────────────────────────────

def parse_query(query: str) -> dict:
    """
    Extracts intent and entities from a natural language query.
    In production: use an LLM or a lightweight NER model for this step.
    Here we use simple keyword matching for clarity.
    """
    query_lower = query.lower()
    user_id = None
    for uid in ["u_001", "u_002", "u_003"]:
        if uid in query_lower:
            user_id = uid
            break

    intent = "general"
    if any(w in query_lower for w in ["error", "fail", "broken", "issue", "problem"]):
        intent = "error_investigation"
    elif any(w in query_lower for w in ["churn", "cancel", "leave", "quit"]):
        intent = "churn_investigation"
    elif any(w in query_lower for w in ["purchase", "buy", "paid", "convert"]):
        intent = "conversion_investigation"

    return {"user_id": user_id, "intent": intent, "raw": query}


# ── CONTEXT ASSEMBLY ──────────────────────────────────────────────────────────

def assemble_context(parsed: dict, store: VectorStore) -> dict:
    """
    Retrieves relevant context from both vector store and structured store.
    The LLM will only see this assembled context — never raw data directly.
    """
    uid = parsed["user_id"]

    # Vector retrieval: semantic search filtered to this user
    vector_results = store.query(
        query_text=parsed["raw"],
        top_k=4,
        filter_fn=(lambda m: m["user_id"] == uid) if uid else None,
    )

    # Structured retrieval: pre-computed metrics (computed by batch/RT layer)
    structured = query_structured_store(uid) if uid else None

    return {
        "query": parsed["raw"],
        "intent": parsed["intent"],
        "user_id": uid,
        "vector_chunks": [r["text"] for r in vector_results],
        "structured_metrics": structured,
    }


# ── LLM REASONING (mocked) ────────────────────────────────────────────────────

def llm_reason(context: dict) -> str:
    """
    Mocks an LLM call with assembled context.

    In production:
        from openai import OpenAI
        client = OpenAI()
        system = "You are a data analyst. Answer only from the provided context. Do not invent data."
        user_msg = f\"\"\"
        Context:
        {chr(10).join(context['vector_chunks'])}

        Metrics: {context['structured_metrics']}

        Question: {context['query']}
        \"\"\"
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role":"system","content":system},{"role":"user","content":user_msg}]
        )
        return resp.choices[0].message.content
    """
    chunks = context["vector_chunks"]
    metrics = context["structured_metrics"] or {}
    intent = context["intent"]
    uid = context["user_id"] or "unknown user"

    has_errors   = any("error" in c for c in chunks)
    has_checkout = any("checkout" in c for c in chunks)
    has_support  = any("support_msg" in c for c in chunks)
    error_count  = metrics.get("errors_7d", 0)
    churn_risk   = metrics.get("churn_risk", "unknown")

    lines = [f"Analysis for {uid} (intent: {intent}):"]

    if intent == "error_investigation":
        if has_errors and has_checkout:
            lines.append(f"  • User encountered repeated errors on /checkout ({error_count} errors in last 7 days).")
        if has_support:
            lines.append("  • User submitted a support message describing a 500 error on checkout.")
        lines.append(f"  • Churn risk is currently: {churn_risk.upper()}.")
        lines.append("  Recommendation: escalate to engineering — checkout errors are directly blocking conversion.")
    elif intent == "churn_investigation":
        lines.append(f"  • {metrics.get('page_views_7d', 0)} page views in last 7 days — engagement is declining.")
        lines.append(f"  • {metrics.get('purchases_7d', 0)} purchases in last 7 days.")
        lines.append(f"  • Churn risk score: {churn_risk.upper()}.")
        lines.append("  Recommendation: trigger a retention workflow — offer a plan upgrade or support outreach.")
    else:
        lines.append(f"  • {metrics.get('page_views_7d', 0)} page views, {metrics.get('purchases_7d', 0)} purchases in last 7 days.")
        lines.append(f"  • Plan: {metrics.get('plan', 'unknown')}. Churn risk: {churn_risk}.")
        lines.append("  No specific anomaly detected in the retrieved context.")

    return "\n".join(lines)


# ── PIPELINE RUNNER ───────────────────────────────────────────────────────────

def run(query: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"[AI PIPELINE] Query: \"{query}\"")
    print(f"{'=' * 60}")

    # Step 1: Seed vector store (in production this is pre-populated)
    store = VectorStore()
    seed_vector_store(store)
    print(f"[VECTOR STORE] {len(store._docs)} documents indexed")

    # Step 2: Parse query
    parsed = parse_query(query)
    print(f"[PARSE] intent={parsed['intent']} | user_id={parsed['user_id']}")

    # Step 3: Assemble context
    ctx = assemble_context(parsed, store)
    print(f"[RETRIEVE] {len(ctx['vector_chunks'])} vector chunks retrieved")
    print(f"[RETRIEVE] Structured metrics: {ctx['structured_metrics']}")

    # Step 4: LLM reasoning
    print(f"\n[LLM] Reasoning over context...")
    print(f"[LLM] Context chunks passed:")
    for i, chunk in enumerate(ctx["vector_chunks"]):
        print(f"  [{i+1}] {chunk}")

    response = llm_reason(ctx)

    print(f"\n[OUTPUT]")
    print(f"{'─' * 60}")
    print(response)
    print(f"{'─' * 60}")
    print("\n[AI PIPELINE] Complete.")
    print("[NOTE] Numbers came from the structured store (batch/RT layer).")
    print("[NOTE] The LLM only reasoned — it did not compute anything.")


if __name__ == "__main__":
    # Run two different queries to show intent routing
    run("What errors has user u_001 been experiencing this week?")
    run("Is user u_003 at risk of churning?")
