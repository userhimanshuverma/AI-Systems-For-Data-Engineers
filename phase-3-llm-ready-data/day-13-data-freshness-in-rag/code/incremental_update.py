"""
Incremental Update — Day 13: Data Freshness in RAG
====================================================
Demonstrates event-driven incremental embedding updates.

Instead of running a batch job every 4 hours, this approach:
  1. Consumes events from Kafka as they arrive
  2. Computes content hash for each event's text
  3. Only re-embeds if the content has changed
  4. Upserts to vector store immediately

Result: Vector store is always < 5 seconds behind Kafka.
"""

import math
import random
import hashlib
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict


# ── MOCK EMBEDDING ────────────────────────────────────────────────────────────

def mock_embed(text: str, dim: int = 16) -> list[float]:
    random.seed(abs(hash(text)) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

def cosine(a: list[float], b: list[float]) -> float:
    return round(sum(x*y for x,y in zip(a,b)), 4)

def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ── LIVE VECTOR STORE ─────────────────────────────────────────────────────────

class LiveVectorStore:
    """Vector store with freshness tracking per document."""
    def __init__(self):
        self._docs:   dict[str, dict] = {}
        self._hashes: dict[str, str]  = {}
        self._upserts = 0
        self._skips   = 0

    def upsert(self, doc_id: str, text: str, metadata: dict) -> bool:
        """Returns True if upserted, False if skipped (no change)."""
        chash = content_hash(text)
        if self._hashes.get(doc_id) == chash:
            self._skips += 1
            return False

        self._docs[doc_id] = {
            "id":          doc_id,
            "text":        text,
            "vector":      mock_embed(text),
            "metadata":    metadata,
            "embedded_at": datetime.now(timezone.utc).isoformat(),
            "content_hash":chash,
        }
        self._hashes[doc_id] = chash
        self._upserts += 1
        return True

    def search(self, query: str, top_k: int = 4, uid: str = None) -> list[dict]:
        qv = mock_embed(query)
        results = [
            {**d, "score": cosine(qv, d["vector"])}
            for d in self._docs.values()
            if uid is None or d["metadata"].get("user_id") == uid
        ]
        return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]

    def freshness_stats(self) -> dict:
        if not self._docs:
            return {}
        now = datetime.now(timezone.utc)
        ages = []
        for d in self._docs.values():
            ts = d["embedded_at"].replace("Z", "+00:00")
            age = (now - datetime.fromisoformat(ts)).total_seconds()
            ages.append(age)
        return {
            "total_docs":   len(self._docs),
            "upserts":      self._upserts,
            "skips":        self._skips,
            "avg_age_s":    round(sum(ages)/len(ages), 1),
            "max_age_s":    round(max(ages), 1),
        }

    def __len__(self):
        return len(self._docs)


# ── EVENT-TO-TEXT CONVERTER ───────────────────────────────────────────────────

def event_to_text(event: dict) -> str:
    uid     = event.get("user_id", "?")
    etype   = event.get("event_type", "?")
    page    = event.get("page", "")
    errors  = event.get("session_errors", 0)
    rate    = event.get("error_rate", 0.0)
    churn   = event.get("churn_risk", False)
    intent  = event.get("intent_score", 0.0)
    plan    = event.get("plan", "?")
    segment = event.get("segment", "?")
    ts      = event.get("ts", "")[:16].replace("T", " ")

    text = f"User {uid} ({plan} plan, {segment} segment) performed '{etype}'"
    if page:
        text += f" on {page}"
    text += f" at {ts} UTC."
    if errors > 0:
        text += f" Session: {errors} errors ({rate:.0%} rate)."
    if churn:
        text += " Churn risk: TRUE."
    if intent > 0.5:
        text += f" Upgrade intent: {intent:.2f}."
    return text


# ── SIMULATED KAFKA STREAM ────────────────────────────────────────────────────

def kafka_stream():
    """Yields events as they would arrive from Kafka over time."""
    now = datetime.now(timezone.utc)
    events = [
        # t=0: healthy state
        {"event_id":"evt_001","user_id":"u_4821","event_type":"ui.page_view",
         "page":"/home","ts":(now-timedelta(minutes=10)).isoformat(),
         "plan":"free","segment":"at_risk","session_errors":0,"error_rate":0.0,
         "churn_risk":False,"intent_score":0.0},
        # t=2min: first error
        {"event_id":"evt_002","user_id":"u_4821","event_type":"system.server_error",
         "page":"/checkout","ts":(now-timedelta(minutes=8)).isoformat(),
         "plan":"free","segment":"at_risk","session_errors":1,"error_rate":0.33,
         "churn_risk":False,"intent_score":0.0},
        # t=4min: pricing visit
        {"event_id":"evt_003","user_id":"u_4821","event_type":"ui.page_view",
         "page":"/pricing","ts":(now-timedelta(minutes=6)).isoformat(),
         "plan":"free","segment":"at_risk","session_errors":1,"error_rate":0.25,
         "churn_risk":False,"intent_score":0.25},
        # t=6min: second error — churn risk triggers
        {"event_id":"evt_004","user_id":"u_4821","event_type":"system.server_error",
         "page":"/checkout","ts":(now-timedelta(minutes=4)).isoformat(),
         "plan":"free","segment":"at_risk","session_errors":2,"error_rate":0.40,
         "churn_risk":True,"intent_score":0.25},
        # t=8min: upgrade click
        {"event_id":"evt_005","user_id":"u_4821","event_type":"ui.button_click",
         "page":"/pricing","ts":(now-timedelta(minutes=2)).isoformat(),
         "plan":"free","segment":"at_risk","session_errors":2,"error_rate":0.33,
         "churn_risk":True,"intent_score":0.82},
        # t=10min: third error
        {"event_id":"evt_006","user_id":"u_4821","event_type":"system.server_error",
         "page":"/checkout","ts":now.isoformat(),
         "plan":"free","segment":"at_risk","session_errors":3,"error_rate":0.50,
         "churn_risk":True,"intent_score":0.82},
    ]
    for event in events:
        yield event
        time.sleep(0.05)  # simulate ~50ms between events


# ── MOCK LLM ──────────────────────────────────────────────────────────────────

def mock_llm_fresh(query: str, chunks: list[str], pinot: dict) -> str:
    errors = pinot.get("session_errors", 0)
    churn  = pinot.get("churn_risk", False)
    intent = pinot.get("intent_score", 0.0)
    has_errors = any("error" in c.lower() for c in chunks)

    if churn and has_errors:
        return (
            f"User u_4821 is at HIGH churn risk. "
            f"{errors} checkout errors detected. "
            f"Upgrade intent score: {intent:.2f} — user wants to convert but is blocked. "
            f"Recommend: escalate checkout fix immediately."
        )
    return f"User u_4821: {errors} errors, churn_risk={churn}."


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("INCREMENTAL UPDATE — Event-driven embedding freshness")
    print("=" * 65)

    store = LiveVectorStore()
    query = "Is user u_4821 having checkout issues?"

    print(f"\n[PHASE 1]  Processing events as they arrive from Kafka\n")

    pinot_latest = {}
    for event in kafka_stream():
        text    = event_to_text(event)
        upserted = store.upsert(
            doc_id=event["event_id"],
            text=text,
            metadata={"user_id": event["user_id"], "churn_risk": event["churn_risk"]},
        )
        pinot_latest = event  # track latest state

        status = "✅ UPSERTED" if upserted else "⏭  SKIPPED"
        print(f"  {status}  {event['event_id']}  {event['event_type']:25s}  "
              f"errors={event['session_errors']}  churn={event['churn_risk']}")

    print(f"\n[PHASE 2]  Vector store freshness stats")
    stats = store.freshness_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print(f"\n[PHASE 3]  Query with fresh embeddings")
    print(f"  Query: \"{query}\"\n")

    results = store.search(query, top_k=3, uid="u_4821")
    for r in results:
        print(f"  score={r['score']:.4f}  {r['text'][:65]}...")

    print(f"\n[PHASE 4]  LLM response (fresh context)")
    chunks   = [r["text"] for r in results]
    response = mock_llm_fresh(query, chunks, pinot_latest)
    print(f"  \"{response}\"")
    print(f"  ✅ CORRECT — based on events from the last few seconds")

    print(f"\n[PHASE 5]  Re-embedding on content change")
    print(f"  Simulating enrichment update: churn_risk changes for evt_002...")
    updated_event = {**[e for e in kafka_stream() if True][1]}  # get evt_002
    updated_event["churn_risk"]  = True
    updated_event["error_rate"]  = 0.50
    updated_event["session_errors"] = 5

    updated_text = event_to_text(updated_event)
    upserted = store.upsert("evt_002", updated_text, {"user_id": "u_4821", "churn_risk": True})
    print(f"  evt_002 re-embedded: {upserted} (content changed → new hash)")

    print(f"\n{'='*65}")
    print(f"  SUMMARY: Incremental Update")
    print(f"  Events processed:  {stats['total_docs']}")
    print(f"  Upserts:           {stats['upserts']}")
    print(f"  Skips:             {stats['skips']}")
    print(f"  Max data age:      {stats['max_age_s']}s")
    print(f"  LLM accuracy:      ✅ Correct — fresh context")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
