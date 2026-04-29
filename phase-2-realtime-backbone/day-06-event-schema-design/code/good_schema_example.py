"""
Good Schema Example — Day 06: Event Schema Design
===================================================
Demonstrates production-quality event schemas: context-rich,
consistently named, versioned, and AI-ready.

Every field has a purpose. Every event tells a story.
Run this to see what strong events look like — and what they
produce when converted to text for embedding.
"""

import uuid
import random
from datetime import datetime, timezone


# ── CANONICAL SCHEMA BUILDER ──────────────────────────────────────────────────

def make_event(
    event_type: str,
    user_id: str,
    session_id: str,
    context: dict,
    device: dict,
    user_properties: dict,
    domain_data: dict | None = None,
    schema_version: str = "1.0",
) -> dict:
    """
    Canonical event factory. Every event produced by this system
    goes through this function — ensuring structural consistency.

    In production: this lives in a shared SDK imported by all services.
    Schema is enforced by schema_validator.py before publishing to Kafka.
    """
    event = {
        "event_id":       str(uuid.uuid4()),
        "schema_version": schema_version,
        "event_type":     event_type,
        "user_id":        user_id,
        "session_id":     session_id,
        "ts":             datetime.now(timezone.utc).isoformat(),
        "context":        context,
        "device":         device,
        "user_properties": user_properties,
    }
    if domain_data:
        event["data"] = domain_data
    return event


# ── DEVICE PROFILES (simulated) ───────────────────────────────────────────────

DEVICES = [
    {"type": "mobile",  "os": "iOS 17",      "browser": "Safari"},
    {"type": "mobile",  "os": "Android 14",  "browser": "Chrome"},
    {"type": "desktop", "os": "macOS 14",    "browser": "Chrome"},
    {"type": "desktop", "os": "Windows 11",  "browser": "Edge"},
]

USER_PROFILES = {
    "u_001": {"plan": "free",       "country": "US", "signup_days_ago": 45,  "segment": "at_risk"},
    "u_002": {"plan": "pro",        "country": "UK", "signup_days_ago": 12,  "segment": "active"},
    "u_003": {"plan": "free",       "country": "DE", "signup_days_ago": 3,   "segment": "new"},
    "u_004": {"plan": "enterprise", "country": "SG", "signup_days_ago": 180, "segment": "champion"},
}

SESSIONS = {uid: f"sess_{uuid.uuid4().hex[:8]}" for uid in USER_PROFILES}


# ── SPECIFIC EVENT PRODUCERS ──────────────────────────────────────────────────

def make_button_click(user_id: str, page: str, element_id: str,
                      element_text: str, referrer: str) -> dict:
    return make_event(
        event_type="ui.button_click",
        user_id=user_id,
        session_id=SESSIONS[user_id],
        context={
            "page":         page,
            "element_id":   element_id,
            "element_text": element_text,
            "referrer":     referrer,
        },
        device=random.choice(DEVICES),
        user_properties=USER_PROFILES[user_id],
    )

def make_page_view(user_id: str, page: str, referrer: str,
                   time_on_prev_page_s: int = 0) -> dict:
    return make_event(
        event_type="ui.page_view",
        user_id=user_id,
        session_id=SESSIONS[user_id],
        context={
            "page":                  page,
            "referrer":              referrer,
            "time_on_prev_page_s":   time_on_prev_page_s,
        },
        device=random.choice(DEVICES),
        user_properties=USER_PROFILES[user_id],
    )

def make_server_error(user_id: str, page: str, error_code: int,
                      trace_id: str) -> dict:
    return make_event(
        event_type="system.server_error",
        user_id=user_id,
        session_id=SESSIONS[user_id],
        context={
            "page":       page,
            "error_code": error_code,
            "trace_id":   trace_id,
        },
        device=random.choice(DEVICES),
        user_properties=USER_PROFILES[user_id],
        domain_data={"error_code": error_code, "trace_id": trace_id},
    )

def make_purchase(user_id: str, plan: str, amount_usd: float) -> dict:
    return make_event(
        event_type="commerce.purchase",
        user_id=user_id,
        session_id=SESSIONS[user_id],
        context={
            "page":    "/checkout",
            "referrer": "/pricing",
        },
        device=random.choice(DEVICES),
        user_properties=USER_PROFILES[user_id],
        domain_data={
            "plan":       plan,
            "amount_usd": amount_usd,
            "currency":   "USD",
        },
    )


# ── EVENT → TEXT (for embedding) ──────────────────────────────────────────────

def event_to_text(event: dict) -> str:
    """
    Converts a rich event to a natural language description.
    This text is what gets embedded and stored in the vector store.
    The quality of this text determines retrieval precision.
    """
    uid   = event["user_id"]
    etype = event["event_type"]
    ts    = event["ts"][:16].replace("T", " ")
    ctx   = event.get("context", {})
    dev   = event.get("device", {})
    props = event.get("user_properties", {})
    data  = event.get("data", {})

    base = (
        f"User {uid} ({props.get('plan','?')} plan, {props.get('country','?')}, "
        f"segment={props.get('segment','?')}, {dev.get('type','?')} {dev.get('os','')}) "
        f"performed '{etype}' at {ts} UTC."
    )

    if ctx.get("page"):
        base += f" Page: {ctx['page']}."
    if ctx.get("element_text"):
        base += f" Clicked: '{ctx['element_text']}'."
    if ctx.get("referrer"):
        base += f" Arrived from: {ctx['referrer']}."
    if ctx.get("error_code"):
        base += f" Error {ctx['error_code']} on {ctx.get('page','?')}."
    if data.get("plan"):
        base += f" Purchased plan: {data['plan']} (${data.get('amount_usd',0)})."

    return base


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> None:
    print("=" * 65)
    print("STRONG SCHEMA EVENTS — Production-quality, AI-ready")
    print("=" * 65)

    events = [
        make_page_view("u_001", "/pricing", "/home", time_on_prev_page_s=45),
        make_page_view("u_001", "/pricing", "/home", time_on_prev_page_s=12),
        make_server_error("u_001", "/checkout", 500, "trace_abc123"),
        make_button_click("u_001", "/pricing", "cta_upgrade_plan", "Upgrade to Pro", "/pricing"),
        make_server_error("u_001", "/checkout", 500, "trace_def456"),
        make_purchase("u_002", "pro", 49.00),
    ]

    print(f"\n[EVENTS LOGGED] {len(events)} events\n")
    for i, e in enumerate(events):
        print(f"  [{i+1}] event_type={e['event_type']}")
        print(f"       user_id={e['user_id']} | session={e['session_id'][:16]}...")
        print(f"       ts={e['ts'][:19]}Z")
        print(f"       context={e['context']}")
        if e.get('data'):
            print(f"       data={e['data']}")
        print()

    print("[SCHEMA VALIDATION]")
    required = {"event_id", "schema_version", "event_type", "user_id", "session_id", "ts"}
    for i, e in enumerate(events):
        missing = required - set(e.keys())
        status = "✅ PASS" if not missing else f"❌ FAIL — missing: {missing}"
        print(f"  [{i+1}] {e['event_type']:30s} {status}")

    print("\n[EMBEDDING TEXT — what the AI layer receives]")
    for i, e in enumerate(events):
        text = event_to_text(e)
        print(f"  [{i+1}] \"{text}\"")
        print()

    print("[AI QUERY RESULT]")
    print("  Query: 'Why is user u_001 at risk of churning?'")
    print("  LLM:   'User u_001 (free plan, US, at_risk segment) visited")
    print("          /pricing twice and clicked Upgrade to Pro, but hit")
    print("          2 checkout errors (500). Strong upgrade intent blocked")
    print("          by checkout failures. Recommend: fix checkout + send")
    print("          targeted upgrade offer with payment retry.'")
    print()
    print("  → Rich schema → rich embedding → precise retrieval → actionable LLM output.")


if __name__ == "__main__":
    random.seed(42)
    run()
