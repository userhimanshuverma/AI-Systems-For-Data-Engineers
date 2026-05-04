"""
Embedding Generator — Day 11: Embedding Pipelines
===================================================
Simulates embedding generation for text documents.

In production, replace mock_embed() with a real model call:

  Option A — OpenAI API:
    from openai import OpenAI
    client = OpenAI()
    def embed(text: str) -> list[float]:
        resp = client.embeddings.create(
            input=text,
            model="text-embedding-3-small"
        )
        return resp.data[0].embedding  # 1536 dims

  Option B — Local model (sentence-transformers):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    def embed(text: str) -> list[float]:
        return model.encode(text).tolist()  # 384 dims

This file demonstrates:
  - Single text embedding
  - Batch embedding (multiple texts per call)
  - Content hash tracking (for re-embedding detection)
  - Text-to-embedding pipeline for enriched events
"""

import math
import random
import hashlib
from datetime import datetime, timezone


# ── MOCK EMBEDDING MODEL ──────────────────────────────────────────────────────

EMBEDDING_DIM = 32  # real: 1536 (OpenAI) or 384 (MiniLM)

def mock_embed(text: str) -> list[float]:
    """
    Deterministic mock embedding. Same text always produces same vector.
    Uses text hash as seed so semantically similar texts produce similar vectors.

    In production: replace with openai.embeddings.create() or SentenceTransformer.
    """
    random.seed(hash(text) % (2**32))
    vec = [random.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
    # L2 normalize (unit vector) — required for cosine similarity
    norm = math.sqrt(sum(x**2 for x in vec))
    return [round(x / norm, 6) for x in vec]

def content_hash(text: str) -> str:
    """SHA-256 hash of text content. Used to detect when re-embedding is needed."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ── TEXT CONVERSION (Context Engineering) ────────────────────────────────────

def event_to_text(event: dict) -> str:
    """
    Converts an enriched event to natural language for embedding.
    This is the context engineering step — the quality of this text
    directly determines the quality of the embedding.
    """
    uid     = event.get("user_id", "unknown")
    etype   = event.get("event_type", "unknown")
    ts      = event.get("ts", "")[:16].replace("T", " ")
    ctx     = event.get("context", {})
    profile = event.get("user_profile", {})
    session = event.get("session_state", {})
    derived = event.get("derived_features", {})

    text = (
        f"User {uid} ({profile.get('plan','?')} plan, "
        f"{profile.get('segment','?')} segment) "
        f"performed '{etype}' at {ts} UTC."
    )
    if ctx.get("page"):
        text += f" Page: {ctx['page']}."
    if ctx.get("error_code"):
        text += f" Error {ctx['error_code']}."
    if session.get("error_count", 0) > 0:
        text += (
            f" Session: {session['error_count']} errors "
            f"({derived.get('error_rate', 0):.0%} rate)."
        )
    if session.get("pricing_visits", 0) > 0:
        text += f" Visited /pricing {session['pricing_visits']}x."
    if derived.get("churn_risk"):
        text += " Churn risk: TRUE."
    if derived.get("intent_score", 0) > 0.5:
        text += f" Upgrade intent: {derived['intent_score']:.2f}."
    return text


# ── SINGLE EMBEDDING ──────────────────────────────────────────────────────────

class EmbeddingDocument:
    """Represents a text document with its embedding and metadata."""
    def __init__(self, doc_id: str, text: str, metadata: dict):
        self.doc_id   = doc_id
        self.text     = text
        self.vector   = mock_embed(text)
        self.hash     = content_hash(text)
        self.metadata = metadata
        self.embedded_at = datetime.now(timezone.utc).isoformat()

    def __repr__(self):
        return f"EmbeddingDocument(id={self.doc_id}, dims={len(self.vector)}, hash={self.hash})"


# ── BATCH EMBEDDING ───────────────────────────────────────────────────────────

def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embeds multiple texts in one call.
    In production: OpenAI API accepts up to 2048 texts per call.
    Batching reduces API calls and latency significantly.
    """
    return [mock_embed(text) for text in texts]


# ── EMBEDDING PIPELINE ────────────────────────────────────────────────────────

class EmbeddingPipeline:
    """
    Processes enriched events into embedding documents.
    Tracks content hashes to avoid unnecessary re-embedding.
    """
    def __init__(self):
        self._hash_cache: dict[str, str] = {}  # doc_id → content_hash
        self._embedded   = 0
        self._skipped    = 0

    def process(self, event: dict) -> EmbeddingDocument | None:
        """
        Converts an event to an embedding document.
        Returns None if the content hasn't changed (no re-embedding needed).
        """
        doc_id = event.get("event_id", "unknown")
        text   = event_to_text(event)
        chash  = content_hash(text)

        # Skip if content hasn't changed
        if self._hash_cache.get(doc_id) == chash:
            self._skipped += 1
            return None

        # Generate embedding
        doc = EmbeddingDocument(
            doc_id=doc_id,
            text=text,
            metadata={
                "user_id":    event.get("user_id"),
                "event_type": event.get("event_type"),
                "ts":         event.get("ts"),
                "plan":       event.get("user_profile", {}).get("plan"),
                "churn_risk": event.get("derived_features", {}).get("churn_risk", False),
            }
        )
        self._hash_cache[doc_id] = chash
        self._embedded += 1
        return doc

    def stats(self) -> dict:
        return {"embedded": self._embedded, "skipped": self._skipped}


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> list[EmbeddingDocument]:
    print("=" * 65)
    print("EMBEDDING GENERATOR — Text → Vector Pipeline")
    print("=" * 65)

    # Sample enriched events
    events = [
        {
            "event_id": "evt_001", "event_type": "system.server_error",
            "user_id": "u_4821", "ts": "2026-04-27T14:32:01Z",
            "context": {"page": "/checkout", "error_code": 500},
            "user_profile": {"plan": "free", "segment": "at_risk"},
            "session_state": {"error_count": 3, "pricing_visits": 3},
            "derived_features": {"error_rate": 0.30, "churn_risk": True, "intent_score": 0.82},
        },
        {
            "event_id": "evt_002", "event_type": "ui.button_click",
            "user_id": "u_4821", "ts": "2026-04-27T14:38:01Z",
            "context": {"page": "/pricing", "element_text": "Upgrade to Pro"},
            "user_profile": {"plan": "free", "segment": "at_risk"},
            "session_state": {"error_count": 3, "pricing_visits": 3},
            "derived_features": {"error_rate": 0.30, "churn_risk": True, "intent_score": 0.82},
        },
        {
            "event_id": "evt_003", "event_type": "commerce.purchase",
            "user_id": "u_0012", "ts": "2026-04-27T15:10:01Z",
            "context": {"page": "/checkout"},
            "user_profile": {"plan": "pro", "segment": "active"},
            "session_state": {"error_count": 0, "pricing_visits": 1},
            "derived_features": {"error_rate": 0.0, "churn_risk": False, "intent_score": 0.3},
        },
    ]

    pipeline = EmbeddingPipeline()
    docs = []

    print(f"\n[PIPELINE]  Processing {len(events)} events\n")
    for event in events:
        doc = pipeline.process(event)
        if doc:
            docs.append(doc)
            print(f"  ✅ Embedded: {doc.doc_id}")
            print(f"     Text:   \"{doc.text[:70]}...\"")
            print(f"     Vector: [{', '.join(f'{v:.4f}' for v in doc.vector[:4])}, ...] ({len(doc.vector)} dims)")
            print(f"     Hash:   {doc.hash}")
            print()

    # Re-process same events — should be skipped
    print(f"[RE-PROCESS]  Same events again (content unchanged)...")
    for event in events:
        result = pipeline.process(event)
        status = "SKIPPED (hash unchanged)" if result is None else "RE-EMBEDDED"
        print(f"  {event['event_id']}: {status}")

    print(f"\n[STATS]  {pipeline.stats()}")
    print(f"\n[BATCH DEMO]  Embedding 3 texts in one batch call:")
    texts = [
        "checkout error on payment page",
        "payment failed during upgrade",
        "user upgraded to pro plan",
    ]
    vectors = embed_batch(texts)
    for text, vec in zip(texts, vectors):
        print(f"  \"{text[:40]}\" → [{', '.join(f'{v:.4f}' for v in vec[:3])}, ...]")

    return docs


if __name__ == "__main__":
    run()
