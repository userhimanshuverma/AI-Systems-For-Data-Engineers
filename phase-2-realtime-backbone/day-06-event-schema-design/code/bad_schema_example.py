"""
Bad Schema Example — Day 06: Event Schema Design
==================================================
Demonstrates what most teams log when they start: minimal events
with no context, inconsistent naming, and no structure.

This is NOT how to design events for AI systems.
Run this to see what weak events look like — and what they produce
when converted to text for embedding.
"""

import time
import random
from datetime import datetime


# ── WEAK EVENT PRODUCERS ──────────────────────────────────────────────────────
# These represent common anti-patterns seen in real codebases.

def log_click(user_id: str) -> dict:
    """Anti-pattern: logs that a click happened, nothing more."""
    return {
        "uid": user_id,          # ❌ inconsistent name (should be user_id)
        "evt": "click",          # ❌ too vague — click on what?
        "t":   int(time.time()), # ❌ Unix timestamp, no timezone
    }

def log_error(user_id: str, code: int) -> dict:
    """Anti-pattern: logs an error with minimal context."""
    return {
        "user": user_id,         # ❌ different name again (uid vs user vs user_id)
        "type": "error",         # ❌ conflicts with Python built-in 'type'
        "code": code,            # ❌ no page, no trace, no session
        "time": datetime.now().strftime("%d/%m/%Y %H:%M"), # ❌ non-standard format
    }

def log_purchase(user_id: str, amount: float) -> dict:
    """Anti-pattern: logs a purchase with no product or plan context."""
    return {
        "userId": user_id,       # ❌ camelCase — inconsistent with other events
        "action": "buy",         # ❌ "buy" vs "purchase" — no standardization
        "amt":    amount,        # ❌ abbreviated field name
        # ❌ no product, no plan, no device, no session
    }


# ── WHAT THESE EVENTS PRODUCE DOWNSTREAM ─────────────────────────────────────

def event_to_text_weak(event: dict) -> str:
    """
    Converts a weak event to text for embedding.
    This is what the embedding pipeline receives.
    The resulting text is vague and produces a generic vector.
    """
    uid   = event.get("uid") or event.get("user") or event.get("userId") or "unknown"
    etype = event.get("evt") or event.get("type") or event.get("action") or "unknown"
    ts    = event.get("t") or event.get("time") or "unknown"
    return f"User {uid} performed '{etype}' at {ts}."


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 60)
    print("WEAK SCHEMA EVENTS — What most teams log")
    print("=" * 60)

    users = ["u_001", "u_002", "u_003"]
    events = [
        log_click(random.choice(users)),
        log_error(random.choice(users), 500),
        log_purchase(random.choice(users), 49.99),
        log_click(random.choice(users)),
        log_error(random.choice(users), 404),
    ]

    print("\n[EVENTS LOGGED]")
    for i, e in enumerate(events):
        print(f"  [{i+1}] {e}")

    print("\n[PROBLEMS DETECTED]")
    field_names = set()
    for e in events:
        for k in e.keys():
            if k in field_names and k not in ("code", "t", "time"):
                pass
            field_names.add(k)

    user_fields = [k for k in field_names if "user" in k.lower() or k in ("uid",)]
    print(f"  ❌ Inconsistent user identifier fields: {user_fields}")
    print(f"  ❌ No page context in any event")
    print(f"  ❌ No session_id in any event")
    print(f"  ❌ No schema_version in any event")
    print(f"  ❌ Mixed timestamp formats")

    print("\n[EMBEDDING TEXT — what the AI layer receives]")
    for i, e in enumerate(events):
        text = event_to_text_weak(e)
        print(f"  [{i+1}] \"{text}\"")

    print("\n[AI QUERY RESULT]")
    print("  Query: 'Why is user u_001 at risk of churning?'")
    print("  LLM:   'Insufficient context. Available data only shows")
    print("          generic actions with no behavioral detail.'")
    print()
    print("  → The schema is the bottleneck. Not the LLM.")


if __name__ == "__main__":
    random.seed(42)
    run()
