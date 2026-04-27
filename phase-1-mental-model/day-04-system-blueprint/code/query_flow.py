"""
Query Flow — Day 04: System Blueprint
=======================================
Demonstrates the full read path of the system blueprint:

  User Query → API → Query Parser → [Pinot SQL + Vector Search]
             → Context Assembly → LLM → Structured Response

This is the intelligence half of the system. A natural language question
enters here and a grounded, evidence-backed answer comes out.

Run this to see the query path end-to-end.
"""

import math
import json
import random
import time
from datetime import datetime, timedelta


# ── MOCK EMBEDDING ────────────────────────────────────────────────────────────

def embed(text: str, dim: int = 24) -> list[float]:
    random.seed(hash(text) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

def cosine(a, b):
    return round(sum(x*y for x,y in zip(a,b)), 4)


# ── VECTOR STORE ──────────────────────────────────────────────────────────────

class VectorStore:
    def __init__(self):
        self._docs: list[dict] = []

    def upsert(self, doc_id: str, text: str, meta: dict):
        self._docs.append({"id": doc_id, "text": text, "vec": embed(text), "meta": meta})

    def query(self, q: str, top_k: int = 4, uid: str = None) -> list[dict]:
        qv = embed(q)
        results = [
            {**d, "score": cosine(qv, d["vec"])}
            for d in self._docs
            if uid is None or d["meta"].get("user_id") == uid
        ]
        return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]

    def __len__(self): return len(self._docs)


# ── PINOT STORE (simulated) ───────────────────────────────────────────────────

PINOT_DATA = {
    "u_001": {"page_views_7d": 14, "errors_7d": 5, "purchases_7d": 0,
              "plan": "free",  "churn_risk": "high",   "last_active": "2h ago",
              "top_error_page": "/checkout", "sessions_7d": 6},
    "u_002": {"page_views_7d": 42, "errors_7d": 0, "purchases_7d": 2,
              "plan": "pro",   "churn_risk": "low",    "last_active": "10m ago",
              "top_error_page": None, "sessions_7d": 18},
    "u_003": {"page_views_7d": 5,  "errors_7d": 1, "purchases_7d": 0,
              "plan": "free",  "churn_risk": "medium", "last_active": "1d ago",
              "top_error_page": "/settings", "sessions_7d": 2},
}

def pinot_query(user_id: str) -> dict | None:
    """
    Simulates: SELECT * FROM user_metrics_7d WHERE user_id = :uid
    In production: HTTP to Pinot broker, returns in <100ms.
    """
    time.sleep(0.07)  # simulate 70ms query latency
    return PINOT_DATA.get(user_id)


# ── SEED VECTOR STORE ─────────────────────────────────────────────────────────

def seed(store: VectorStore) -> None:
    now = datetime.now()
    events = [
        ("u_001", "page_view",   "/pricing",  now - timedelta(days=1, hours=3)),
        ("u_001", "page_view",   "/pricing",  now - timedelta(days=1, hours=1)),
        ("u_001", "error",       "/checkout", now - timedelta(hours=22)),
        ("u_001", "error",       "/checkout", now - timedelta(hours=20)),
        ("u_001", "error",       "/checkout", now - timedelta(hours=18)),
        ("u_001", "support_msg", "Checkout keeps failing with 500 error. Very frustrated.", now - timedelta(hours=16)),
        ("u_001", "page_view",   "/home",     now - timedelta(hours=8)),
        ("u_002", "purchase",    "/checkout", now - timedelta(days=2)),
        ("u_002", "click",       "cta_upgrade", now - timedelta(hours=3)),
        ("u_003", "signup",      "/register", now - timedelta(days=3)),
        ("u_003", "error",       "/settings", now - timedelta(hours=30)),
    ]
    for i, (uid, etype, detail, ts) in enumerate(events):
        text = f"User {uid} performed '{etype}' on '{detail}' at {ts.strftime('%Y-%m-%d %H:%M')}."
        store.upsert(f"doc_{i:03d}", text, {"user_id": uid, "event_type": etype})


# ── QUERY PARSER ──────────────────────────────────────────────────────────────

def parse(query: str) -> dict:
    q = query.lower()
    uid = next((u for u in ["u_001","u_002","u_003"] if u in q), None)
    intent = "general"
    if any(w in q for w in ["error","fail","broken","checkout","issue","problem"]):
        intent = "error_investigation"
    elif any(w in q for w in ["churn","cancel","leave","risk","struggling"]):
        intent = "churn_investigation"
    elif any(w in q for w in ["upgrade","convert","purchase","buy"]):
        intent = "conversion"
    return {"query": query, "user_id": uid, "intent": intent}


# ── CONTEXT ASSEMBLY ──────────────────────────────────────────────────────────

def assemble(parsed: dict, store: VectorStore) -> dict:
    uid = parsed["user_id"]
    chunks  = store.query(parsed["query"], top_k=4, uid=uid)
    metrics = pinot_query(uid) if uid else None
    return {
        "query":   parsed["query"],
        "intent":  parsed["intent"],
        "user_id": uid,
        "chunks":  [{"text": c["text"], "score": c["score"]} for c in chunks],
        "metrics": metrics,
    }


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def llm_call(ctx: dict) -> dict:
    """
    Mocks an LLM API call.
    In production: openai.chat.completions.create(model="gpt-4o", messages=[...])
    """
    time.sleep(0.48)  # simulate ~480ms LLM latency
    m = ctx["metrics"] or {}
    chunks = [c["text"] for c in ctx["chunks"]]
    intent = ctx["intent"]
    uid    = ctx["user_id"] or "unknown"

    has_error    = any("error" in c for c in chunks)
    has_checkout = any("checkout" in c for c in chunks)
    has_support  = any("support_msg" in c for c in chunks)
    has_pricing  = any("pricing" in c for c in chunks)

    churn  = m.get("churn_risk", "unknown")
    errors = m.get("errors_7d", 0)
    pvs    = m.get("page_views_7d", 0)
    plan   = m.get("plan", "unknown")

    if intent == "error_investigation":
        summary = (
            f"User {uid} has experienced {errors} errors in the last 7 days"
            + (f", primarily on {m.get('top_error_page','/checkout')}." if m.get("top_error_page") else ".")
        )
        if has_support:
            summary += " They submitted a support message describing a 500 error and expressed frustration."
        summary += f" Churn risk: {churn.upper()}."
        action, confidence = "escalate_to_engineering", 0.92

    elif intent == "churn_investigation":
        summary = f"User {uid} ({plan} plan): {pvs} page views, {errors} errors in 7 days."
        if has_pricing:
            summary += " Visited /pricing multiple times — evaluating cost."
        summary += f" Churn risk: {churn.upper()}."
        action = "trigger_retention_workflow" if churn in ("high","medium") else "no_action"
        confidence = 0.87

    elif intent == "conversion":
        purchases = m.get("purchases_7d", 0)
        summary = f"User {uid} ({plan} plan): {purchases} purchases in 7 days."
        action, confidence = ("send_upgrade_offer" if purchases > 0 else "nurture_sequence"), 0.79

    else:
        summary = f"User {uid}: {pvs} page views, {errors} errors, plan={plan}, churn_risk={churn}."
        action, confidence = "no_action", 0.65

    return {
        "summary":    summary,
        "action":     action,
        "confidence": confidence,
        "evidence":   [c["text"][:80] for c in ctx["chunks"][:2]],
        "grounded":   True,
    }


# ── QUERY PATH RUNNER ─────────────────────────────────────────────────────────

def run_query(query: str) -> None:
    store = VectorStore()
    seed(store)

    print(f"\n{'='*60}")
    print(f"[QUERY PATH] \"{query}\"")
    print(f"{'='*60}")

    t0 = time.time()

    # 1. Parse
    parsed = parse(query)
    print(f"[PARSE]    intent={parsed['intent']} | user_id={parsed['user_id']}  ({int((time.time()-t0)*1000)}ms)")

    # 2. Retrieve (parallel in production)
    ctx = assemble(parsed, store)
    print(f"[RETRIEVE] {len(ctx['chunks'])} vector chunks + structured metrics  ({int((time.time()-t0)*1000)}ms)")
    for i, c in enumerate(ctx["chunks"]):
        print(f"  [{i+1}] score={c['score']:.4f}  {c['text'][:65]}...")
    print(f"[PINOT]    {ctx['metrics']}")

    # 3. LLM
    print(f"[LLM]      Reasoning over context...  ({int((time.time()-t0)*1000)}ms)")
    result = llm_call(ctx)
    elapsed = int((time.time()-t0)*1000)

    # 4. Output
    print(f"\n[OUTPUT]   ({elapsed}ms total)")
    print(f"{'─'*60}")
    print(f"  Summary:    {result['summary']}")
    print(f"  Action:     {result['action']}")
    print(f"  Confidence: {result['confidence']:.0%}")
    print(f"  Evidence:   {result['evidence'][0][:70]}...")
    print(f"{'─'*60}")
    print(f"  [NOTE] Metrics computed by Pinot. LLM only interpreted them.")


if __name__ == "__main__":
    run_query("Why is user u_001 struggling with checkout?")
    run_query("Is user u_001 at risk of churning?")
    run_query("Is user u_002 likely to upgrade?")
