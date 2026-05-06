"""
Freshness Monitor — Day 13: Data Freshness in RAG
===================================================
Tracks and reports on the freshness of a vector store index.

Monitors:
  - embedding_lag: time from event to embedded
  - stale_doc_ratio: % of docs older than their TTL
  - index_age_max: oldest document in the index
  - hash_mismatch_rate: % of docs where source has changed
  - retrieval_drift: change in top-k results over time

In production: these metrics feed into Prometheus/Grafana
and trigger PagerDuty alerts when thresholds are breached.
"""

import math
import random
import hashlib
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from collections import defaultdict


# ── MOCK EMBEDDING ────────────────────────────────────────────────────────────

def mock_embed(text: str, dim: int = 16) -> list[float]:
    random.seed(abs(hash(text)) % (2**32))
    v = [random.gauss(0, 1) for _ in range(dim)]
    n = math.sqrt(sum(x**2 for x in v))
    return [x/n for x in v]

def cosine(a, b):
    return round(sum(x*y for x,y in zip(a,b)), 4)

def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ── FRESHNESS CONFIG ──────────────────────────────────────────────────────────

# TTL per document type (seconds)
TTL_CONFIG = {
    "user_activity":    3600,    # 1 hour
    "support_ticket":   86400,   # 24 hours
    "product_catalog":  604800,  # 7 days
    "static_doc":       None,    # never expires
}

# Alert thresholds
ALERT_THRESHOLDS = {
    "embedding_lag_p99_s":  300,   # alert if P99 lag > 5 minutes
    "stale_doc_ratio":      0.05,  # alert if > 5% docs are stale
    "index_age_max_h":      24,    # alert if oldest doc > 24 hours
}


# ── DOCUMENT RECORD ───────────────────────────────────────────────────────────

@dataclass
class DocRecord:
    doc_id:       str
    text:         str
    doc_type:     str
    embedded_at:  datetime
    event_ts:     datetime       # when the original event occurred
    content_hash: str
    model_version:str = "text-embedding-3-small-2024-02"

    @property
    def embedding_lag_s(self) -> float:
        """Time from event occurrence to embedding (seconds)."""
        return (self.embedded_at - self.event_ts).total_seconds()

    @property
    def age_s(self) -> float:
        """Age of this embedding (seconds since embedded)."""
        return (datetime.now(timezone.utc) - self.embedded_at).total_seconds()

    @property
    def ttl(self) -> int | None:
        return TTL_CONFIG.get(self.doc_type)

    @property
    def is_stale(self) -> bool:
        if self.ttl is None:
            return False
        return self.age_s > self.ttl


# ── FRESHNESS MONITOR ─────────────────────────────────────────────────────────

class FreshnessMonitor:
    """
    Tracks freshness metrics for a vector store index.
    In production: exposes metrics via Prometheus client.
    """
    def __init__(self):
        self._docs:    dict[str, DocRecord] = {}
        self._lag_history: list[float]      = []
        self._alerts:  list[dict]           = []
        self._baseline_results: list[str]   = []

    def register(self, doc: DocRecord) -> None:
        self._docs[doc.doc_id] = doc
        self._lag_history.append(doc.embedding_lag_s)

    def compute_metrics(self) -> dict:
        if not self._docs:
            return {}

        docs = list(self._docs.values())
        lags = sorted(self._lag_history)
        ages = [d.age_s for d in docs]
        stale = [d for d in docs if d.is_stale]

        p50_idx = int(len(lags) * 0.50)
        p99_idx = int(len(lags) * 0.99)

        return {
            "total_docs":          len(docs),
            "embedding_lag_p50_s": round(lags[p50_idx] if lags else 0, 2),
            "embedding_lag_p99_s": round(lags[min(p99_idx, len(lags)-1)] if lags else 0, 2),
            "stale_doc_count":     len(stale),
            "stale_doc_ratio":     round(len(stale) / len(docs), 3),
            "index_age_avg_s":     round(sum(ages) / len(ages), 1),
            "index_age_max_s":     round(max(ages), 1),
            "index_age_max_h":     round(max(ages) / 3600, 2),
            "model_versions":      list(set(d.model_version for d in docs)),
        }

    def check_alerts(self, metrics: dict) -> list[dict]:
        alerts = []
        if metrics.get("embedding_lag_p99_s", 0) > ALERT_THRESHOLDS["embedding_lag_p99_s"]:
            alerts.append({
                "severity": "WARNING",
                "metric":   "embedding_lag_p99_s",
                "value":    metrics["embedding_lag_p99_s"],
                "threshold":ALERT_THRESHOLDS["embedding_lag_p99_s"],
                "message":  f"P99 embedding lag {metrics['embedding_lag_p99_s']}s > {ALERT_THRESHOLDS['embedding_lag_p99_s']}s threshold",
            })
        if metrics.get("stale_doc_ratio", 0) > ALERT_THRESHOLDS["stale_doc_ratio"]:
            alerts.append({
                "severity": "CRITICAL",
                "metric":   "stale_doc_ratio",
                "value":    metrics["stale_doc_ratio"],
                "threshold":ALERT_THRESHOLDS["stale_doc_ratio"],
                "message":  f"{metrics['stale_doc_ratio']:.0%} of docs are stale (threshold: {ALERT_THRESHOLDS['stale_doc_ratio']:.0%})",
            })
        if metrics.get("index_age_max_h", 0) > ALERT_THRESHOLDS["index_age_max_h"]:
            alerts.append({
                "severity": "WARNING",
                "metric":   "index_age_max_h",
                "value":    metrics["index_age_max_h"],
                "threshold":ALERT_THRESHOLDS["index_age_max_h"],
                "message":  f"Oldest doc is {metrics['index_age_max_h']:.1f}h old (threshold: {ALERT_THRESHOLDS['index_age_max_h']}h)",
            })
        self._alerts.extend(alerts)
        return alerts

    def check_hash_mismatches(self, source_texts: dict[str, str]) -> dict:
        """
        Compares stored content hashes against current source text.
        Returns docs that need re-embedding.
        """
        mismatches = {}
        for doc_id, current_text in source_texts.items():
            if doc_id in self._docs:
                stored_hash  = self._docs[doc_id].content_hash
                current_hash = content_hash(current_text)
                if stored_hash != current_hash:
                    mismatches[doc_id] = {
                        "stored_hash":  stored_hash,
                        "current_hash": current_hash,
                        "action":       "re-embed",
                    }
        return mismatches

    def detect_retrieval_drift(
        self, query: str, docs: list[dict], baseline: list[str] | None = None
    ) -> dict:
        """
        Detects if retrieval results have drifted from a baseline.
        High drift = index may be stale or corrupted.
        """
        qv = mock_embed(query)
        results = sorted(
            [{"id": d["doc_id"], "score": cosine(qv, mock_embed(d["text"]))} for d in docs],
            key=lambda x: x["score"], reverse=True
        )[:5]
        current_ids = [r["id"] for r in results]

        if baseline is None:
            self._baseline_results = current_ids
            return {"drift_score": 0.0, "status": "baseline_set"}

        overlap = len(set(current_ids) & set(baseline))
        drift   = round(1 - overlap / max(len(baseline), 1), 2)
        return {
            "drift_score": drift,
            "status":      "HIGH_DRIFT" if drift > 0.4 else "NORMAL",
            "overlap":     overlap,
            "current_top5": current_ids,
        }


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("FRESHNESS MONITOR — Tracking vector store health")
    print("=" * 65)

    monitor = FreshnessMonitor()
    now     = datetime.now(timezone.utc)

    # Simulate documents with varying ages and lag
    doc_specs = [
        # Fresh docs (event-driven, < 5s lag)
        ("evt_001", "User u_4821 hit 500 error on /checkout. Churn risk: TRUE.",
         "user_activity", now - timedelta(seconds=2), now - timedelta(seconds=5)),
        ("evt_002", "User u_4821 clicked Upgrade to Pro. Intent: 0.82.",
         "user_activity", now - timedelta(seconds=1), now - timedelta(seconds=3)),
        # Slightly stale (batch, 30min lag)
        ("evt_003", "User u_0012 purchased pro plan.",
         "user_activity", now - timedelta(minutes=30), now - timedelta(minutes=31)),
        # Stale docs (batch, 2h lag — exceeds 1h TTL)
        ("evt_004", "User u_7734 viewed /home. No issues.",
         "user_activity", now - timedelta(hours=2), now - timedelta(hours=2, minutes=5)),
        ("evt_005", "User u_9901 browsed documentation.",
         "user_activity", now - timedelta(hours=3), now - timedelta(hours=3, minutes=2)),
        # Support ticket (24h TTL — not stale yet)
        ("tkt_001", "Support ticket: checkout keeps failing for multiple users.",
         "support_ticket", now - timedelta(hours=12), now - timedelta(hours=12, minutes=1)),
        # Static doc (no TTL)
        ("doc_001", "Product documentation: how to upgrade your plan.",
         "static_doc", now - timedelta(days=30), now - timedelta(days=30, minutes=5)),
    ]

    for doc_id, text, doc_type, event_ts, embedded_at in doc_specs:
        doc = DocRecord(
            doc_id=doc_id, text=text, doc_type=doc_type,
            embedded_at=embedded_at, event_ts=event_ts,
            content_hash=content_hash(text),
        )
        monitor.register(doc)

    # Compute metrics
    print(f"\n[METRICS]")
    metrics = monitor.compute_metrics()
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    # Check alerts
    print(f"\n[ALERTS]")
    alerts = monitor.check_alerts(metrics)
    if alerts:
        for a in alerts:
            icon = "🔴" if a["severity"] == "CRITICAL" else "🟡"
            print(f"  {icon} [{a['severity']}] {a['message']}")
    else:
        print(f"  ✅ No alerts — all metrics within thresholds")

    # Hash mismatch check
    print(f"\n[HASH MISMATCH CHECK]")
    # Simulate that evt_004 source text has changed
    current_texts = {
        "evt_004": "User u_7734 (free plan) hit 3 checkout errors. Churn risk: TRUE.",  # changed!
        "evt_005": "User u_9901 browsed documentation.",  # unchanged
    }
    mismatches = monitor.check_hash_mismatches(current_texts)
    if mismatches:
        for doc_id, info in mismatches.items():
            print(f"  ⚠️  {doc_id}: hash changed → needs re-embedding")
            print(f"     stored={info['stored_hash']}  current={info['current_hash']}")
    else:
        print(f"  ✅ No hash mismatches")

    # Stale doc report
    print(f"\n[STALE DOCUMENTS]")
    stale = [d for d in monitor._docs.values() if d.is_stale]
    if stale:
        for d in stale:
            print(f"  ❌ {d.doc_id} ({d.doc_type}): {d.age_s/3600:.1f}h old (TTL={d.ttl/3600:.0f}h)")
    else:
        print(f"  ✅ No stale documents")

    # Embedding lag report
    print(f"\n[EMBEDDING LAG REPORT]")
    print(f"  P50 lag: {metrics['embedding_lag_p50_s']}s")
    print(f"  P99 lag: {metrics['embedding_lag_p99_s']}s")
    print(f"  Target:  < 5s for support tooling, < 300s for batch use cases")

    print(f"\n{'='*65}")
    print(f"  MONITORING SUMMARY")
    print(f"  Total docs:      {metrics['total_docs']}")
    print(f"  Stale docs:      {metrics['stale_doc_count']} ({metrics['stale_doc_ratio']:.0%})")
    print(f"  Alerts fired:    {len(alerts)}")
    print(f"  Hash mismatches: {len(mismatches)} (need re-embedding)")
    print(f"{'='*65}")


if __name__ == "__main__":
    run()
