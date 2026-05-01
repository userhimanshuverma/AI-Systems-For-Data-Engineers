"""
Raw Stream — Day 07: Stream Processing
========================================
Simulates raw events arriving from Kafka with no enrichment.
Demonstrates what downstream systems receive without a stream
processing layer — and why it's insufficient for AI systems.

Run this first, then compare with enrichment_processor.py.
"""

import uuid
import random
from datetime import datetime, timezone


# ── RAW EVENT FACTORY ─────────────────────────────────────────────────────────

def make_raw_event(user_id: str, event_type: str, context: dict) -> dict:
    """
    Produces a raw event exactly as the application would publish it.
    Contains only what the app knows at the moment of the action.
    No user profile, no session history, no derived signals.
    """
    return {
        "event_id":       str(uuid.uuid4()),
        "schema_version": "1.0",
        "event_type":     event_type,
        "user_id":        user_id,
        "session_id":     f"sess_{user_id[-3:]}x8y",
        "ts":             datetime.now(timezone.utc).isoformat(),
        "context":        context,
    }


# ── SIMULATED EVENT STREAM ────────────────────────────────────────────────────

def generate_raw_stream(user_id: str = "u_4821") -> list[dict]:
    """
    Simulates a sequence of raw events for a single user session.
    This is what Kafka receives from the web app.
    """
    return [
        make_raw_event(user_id, "ui.page_view",      {"page": "/home",     "referrer": "google"}),
        make_raw_event(user_id, "ui.page_view",      {"page": "/pricing",  "referrer": "/home"}),
        make_raw_event(user_id, "ui.page_view",      {"page": "/checkout", "referrer": "/pricing"}),
        make_raw_event(user_id, "system.server_error",{"page": "/checkout", "error_code": 500}),
        make_raw_event(user_id, "ui.page_view",      {"page": "/pricing",  "referrer": "/checkout"}),
        make_raw_event(user_id, "system.server_error",{"page": "/checkout", "error_code": 500}),
        make_raw_event(user_id, "ui.page_view",      {"page": "/pricing",  "referrer": "/checkout"}),
        make_raw_event(user_id, "ui.button_click",   {"page": "/pricing",  "element_id": "cta_upgrade", "element_text": "Upgrade to Pro"}),
        make_raw_event(user_id, "system.server_error",{"page": "/checkout", "error_code": 500}),
        make_raw_event(user_id, "ui.page_view",      {"page": "/home",     "referrer": "/checkout"}),
    ]


# ── WHAT RAW EVENTS PRODUCE DOWNSTREAM ───────────────────────────────────────

def event_to_text_raw(event: dict) -> str:
    """
    Converts a raw event to text for embedding.
    Without enrichment, this text is thin and generic.
    """
    uid   = event["user_id"]
    etype = event["event_type"]
    ts    = event["ts"][:16].replace("T", " ")
    page  = event.get("context", {}).get("page", "")
    return f"User {uid} performed '{etype}' at {ts} UTC." + (f" Page: {page}." if page else "")


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("RAW STREAM — No enrichment, no context")
    print("=" * 65)

    events = generate_raw_stream("u_4821")

    print(f"\n[KAFKA]  {len(events)} raw events received\n")
    for i, e in enumerate(events):
        print(f"  [{i+1:02d}] {e['event_type']:30s}  page={e['context'].get('page','')}")

    print(f"\n[PINOT]  Columns available without enrichment:")
    print(f"  event_id | event_type | user_id | session_id | ts | page | error_code")
    print(f"  (7 columns — no plan, no segment, no session state, no derived signals)")

    print(f"\n[EMBEDDING TEXT]  What the vector store receives:")
    for i, e in enumerate(events[:4]):
        print(f"  [{i+1}] \"{event_to_text_raw(e)}\"")
    print(f"  ... (all equally thin)")

    print(f"\n[LLM QUERY]  'Why is user u_4821 at risk of churning?'")
    print(f"[LLM OUTPUT] 'Insufficient context. Available data shows page views")
    print(f"              and errors but no user state or behavioral patterns.'")
    print(f"\n  → The raw stream is the bottleneck. Run enrichment_processor.py to fix this.")


if __name__ == "__main__":
    run()
