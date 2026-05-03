"""
Context Builder — Day 10: What LLMs Actually Need
===================================================
Transforms structured data from Pinot and semantic events from
the vector store into optimized natural language context for the LLM.

Three steps:
  1. Signal selection  — pick only fields relevant to the query
  2. Text transformation — convert structured data to natural language
  3. Prompt assembly   — combine system prompt + context + query + format

This is the bridge between your data infrastructure and the LLM.
The quality of this transformation determines the quality of AI responses.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from raw_input_llm import get_raw_pinot_result


# ── SIGNAL SELECTION ──────────────────────────────────────────────────────────

# Fields relevant to each query intent
SIGNAL_MAP = {
    "churn_investigation": [
        "plan", "segment", "session_errors", "error_rate",
        "churn_risk", "pricing_visits", "intent_score",
    ],
    "error_investigation": [
        "plan", "segment", "session_events", "session_errors",
        "error_rate", "churn_risk",
    ],
    "upgrade_investigation": [
        "plan", "segment", "pricing_visits", "intent_score",
        "session_errors",
    ],
    "general": [
        "plan", "segment", "session_errors", "error_rate",
        "churn_risk", "intent_score",
    ],
}

def detect_intent(query: str) -> str:
    """Simple intent detection from query text."""
    q = query.lower()
    if any(w in q for w in ["churn", "cancel", "leave", "risk", "struggling"]):
        return "churn_investigation"
    if any(w in q for w in ["error", "fail", "broken", "issue", "problem"]):
        return "error_investigation"
    if any(w in q for w in ["upgrade", "convert", "buy", "purchase", "plan"]):
        return "upgrade_investigation"
    return "general"

def select_signals(row: dict, intent: str) -> dict:
    """Returns only the fields relevant to the query intent."""
    relevant_fields = SIGNAL_MAP.get(intent, SIGNAL_MAP["general"])
    return {k: v for k, v in row.items() if k in relevant_fields}


# ── TEXT TRANSFORMATION ───────────────────────────────────────────────────────

def metrics_to_text(user_id: str, metrics: dict, intent: str) -> str:
    """
    Converts a metrics dict to a natural language description.
    This is the core transformation — structured → semantic.
    """
    lines = []

    # User identity
    plan    = metrics.get("plan", "unknown")
    segment = metrics.get("segment", "unknown")
    lines.append(f"User {user_id} is on the {plan} plan ({segment} segment).")

    # Error signals
    errors = metrics.get("session_errors", 0)
    rate   = metrics.get("error_rate", 0.0)
    events = metrics.get("session_events", 0)

    if errors > 0:
        rate_pct = f"{rate:.0%}"
        if events > 0:
            lines.append(
                f"In the current session: {events} events, {errors} errors "
                f"({rate_pct} error rate)."
            )
        else:
            lines.append(f"Experienced {errors} errors ({rate_pct} error rate).")

    # Intent signals
    pricing = metrics.get("pricing_visits", 0)
    intent_score = metrics.get("intent_score", 0.0)
    if pricing > 0:
        intent_label = "HIGH" if intent_score > 0.6 else "MODERATE" if intent_score > 0.3 else "LOW"
        lines.append(
            f"Visited /pricing {pricing} time{'s' if pricing > 1 else ''} "
            f"without converting (upgrade intent: {intent_label}, score: {intent_score:.2f})."
        )

    # Risk signals
    churn = metrics.get("churn_risk", False)
    if churn:
        lines.append("Churn risk flag is TRUE (high error rate on free plan).")
    elif intent == "churn_investigation":
        lines.append("Churn risk flag is FALSE.")

    return "\n".join(lines)


def events_to_text(events: list[dict]) -> str:
    """
    Converts a list of event dicts to a natural language timeline.
    Only the most relevant events — not all of them.
    """
    if not events:
        return ""

    lines = ["Recent activity (most recent first):"]
    for e in events[:4]:  # top-4 only
        etype = e.get("event_type", "unknown")
        page  = e.get("page", "")
        ts    = e.get("ts", "")[:16].replace("T", " ") if e.get("ts") else ""
        code  = e.get("error_code")

        if "error" in etype and code:
            lines.append(f"  - {code} error on {page} at {ts} UTC")
        elif "button_click" in etype:
            element = e.get("element_text", e.get("element_id", "button"))
            lines.append(f"  - Clicked '{element}' on {page} at {ts} UTC")
        elif "page_view" in etype:
            lines.append(f"  - Viewed {page} at {ts} UTC")
        else:
            lines.append(f"  - {etype} on {page} at {ts} UTC")

    return "\n".join(lines)


def semantic_chunks_to_text(chunks: list[str]) -> str:
    """
    Formats vector store retrieval results as context.
    These are pre-embedded event descriptions.
    """
    if not chunks:
        return ""
    lines = ["Relevant context from event history:"]
    for chunk in chunks[:3]:
        lines.append(f"  - {chunk}")
    return "\n".join(lines)


# ── PROMPT ASSEMBLY ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a data analyst assistant for a SaaS platform.
Answer questions about user behavior using ONLY the provided context.
Do not invent data. If context is insufficient, say so.
Cite specific evidence from the context in your response.
Respond in JSON with exactly these keys:
  summary    (string): 1-2 sentence explanation
  action     (string): recommended next action
  confidence (float):  0.0 to 1.0
  evidence   (list):   2-4 specific facts from context"""

def assemble_prompt(
    user_id: str,
    query: str,
    metrics_text: str,
    events_text: str,
    semantic_text: str,
) -> dict:
    """
    Assembles the full prompt for the LLM.
    Returns a dict with system and user messages (chat format).
    """
    context_parts = [metrics_text]
    if events_text:
        context_parts.append(events_text)
    if semantic_text:
        context_parts.append(semantic_text)

    context = "\n\n".join(context_parts)

    user_message = f"""Context about user {user_id}:
{context}

Question: {query}"""

    return {
        "system": SYSTEM_PROMPT,
        "user":   user_message,
    }

def count_tokens_approx(text: str) -> int:
    return len(text) // 4


# ── FULL CONTEXT BUILDER ──────────────────────────────────────────────────────

class ContextBuilder:
    """
    Orchestrates the full context engineering pipeline:
    Pinot data + vector chunks → optimized LLM prompt.
    """
    def build(
        self,
        user_id: str,
        query: str,
        pinot_rows: list[dict],
        semantic_chunks: list[str] | None = None,
    ) -> dict:
        """
        Builds an optimized context prompt from raw data.
        Returns the assembled prompt and metadata.
        """
        # Step 1: Detect intent
        intent = detect_intent(query)

        # Step 2: Select relevant signals from latest row
        latest_row = pinot_rows[-1] if pinot_rows else {}
        signals    = select_signals(latest_row, intent)

        # Step 3: Transform to natural language
        metrics_text  = metrics_to_text(user_id, signals, intent)
        events_text   = events_to_text(pinot_rows)
        semantic_text = semantic_chunks_to_text(semantic_chunks or [])

        # Step 4: Assemble prompt
        prompt = assemble_prompt(
            user_id, query, metrics_text, events_text, semantic_text
        )

        # Metadata
        full_text  = prompt["system"] + prompt["user"]
        raw_tokens = count_tokens_approx(
            "\n".join(str(v) for row in pinot_rows for v in row.values())
        )
        ctx_tokens = count_tokens_approx(full_text)

        return {
            "prompt":        prompt,
            "intent":        intent,
            "signals_used":  list(signals.keys()),
            "token_count":   ctx_tokens,
            "raw_tokens":    raw_tokens,
            "token_savings": f"{(1 - ctx_tokens/max(raw_tokens,1)):.0%}",
        }


# ── DEMO ──────────────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 65)
    print("CONTEXT BUILDER — Transforming data into LLM-ready context")
    print("=" * 65)

    user_id = "u_4821"
    query   = "Why is this user at risk of churning?"
    rows    = get_raw_pinot_result(user_id)

    # Simulated vector store results
    semantic_chunks = [
        "User u_4821 hit 500 error on /checkout at 14:32 UTC",
        "User u_4821 clicked 'Upgrade to Pro' on /pricing at 14:38 UTC",
        "User u_4821 submitted support ticket: 'checkout keeps failing'",
    ]

    builder = ContextBuilder()
    result  = builder.build(user_id, query, rows, semantic_chunks)

    print(f"\n[QUERY]   \"{query}\"")
    print(f"[INTENT]  {result['intent']}")
    print(f"\n[SIGNAL SELECTION]")
    print(f"  Raw columns available: {len(rows[0])}")
    print(f"  Signals selected:      {len(result['signals_used'])}")
    print(f"  Selected: {result['signals_used']}")

    print(f"\n[TOKEN COMPARISON]")
    print(f"  Raw data tokens:     ~{result['raw_tokens']}")
    print(f"  Context tokens:      ~{result['token_count']}")
    print(f"  Token reduction:     {result['token_savings']}")

    print(f"\n[ASSEMBLED PROMPT]")
    print(f"  System: {result['prompt']['system'][:100]}...")
    print(f"\n  User message:")
    print(f"  {result['prompt']['user']}")

    return result


if __name__ == "__main__":
    run()
