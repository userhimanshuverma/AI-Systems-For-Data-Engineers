"""
LLM Pipeline — Day 03: The New Stack
=======================================
The reasoning layer. Takes assembled context from the retrieval pipeline
and generates a structured response.

Flow:
  query → parse → retrieve (calls retrieval_pipeline) → assemble prompt → LLM → validate → output

Key design rules enforced here:
  1. LLM receives ONLY retrieved context — never raw data
  2. Numbers/metrics come from Pinot (computed) — LLM only interprets them
  3. Output is validated before being returned to the caller
  4. System prompt constrains the LLM to stay grounded in context

In production: replace mock_llm_call() with openai/anthropic SDK call.
"""

import json
import sys
import os

# Import retrieval pipeline from same directory
sys.path.insert(0, os.path.dirname(__file__))
from retrieval_pipeline import VectorStore, seed_store, retrieve


# ── PROMPT BUILDER ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a data analyst assistant for a SaaS platform.
Answer questions about user behavior using ONLY the provided context.
Do not invent data. If the context is insufficient, say so.
When citing evidence, reference specific events from the context.
Keep responses concise and actionable."""

def build_prompt(ctx: dict) -> dict:
    """
    Assembles the full prompt sent to the LLM.
    In production: this is the messages array for chat completions API.
    """
    context_str = "\n".join(
        f"  [{i+1}] (relevance={c['score']:.2f}) {c['text']}"
        for i, c in enumerate(ctx["chunks"])
    )
    metrics_str = json.dumps(ctx["metrics"], indent=2) if ctx["metrics"] else "No structured metrics available."

    user_message = f"""Context — Recent Events:
{context_str}

Context — Structured Metrics (computed by data pipeline, not by you):
{metrics_str}

Question: {ctx['query']}"""

    return {
        "system": SYSTEM_PROMPT,
        "user":   user_message,
    }


# ── MOCK LLM CALL ─────────────────────────────────────────────────────────────

def mock_llm_call(prompt: dict, ctx: dict) -> dict:
    """
    Mocks an LLM API call. Returns a structured response.

    In production:
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user",   "content": prompt["user"]},
            ]
        )
        return json.loads(response.choices[0].message.content)
    """
    chunks  = [c["text"] for c in ctx["chunks"]]
    metrics = ctx["metrics"] or {}
    query   = ctx["query"].lower()

    # Derive answer from context (deterministic mock — real LLM is probabilistic)
    has_errors   = any("error" in c for c in chunks)
    has_checkout = any("checkout" in c for c in chunks)
    has_support  = any("support_msg" in c for c in chunks)
    has_purchase = any("purchase" in c for c in chunks)
    has_pricing  = any("pricing" in c for c in chunks)

    churn_risk  = metrics.get("churn_risk", "unknown")
    errors_7d   = metrics.get("errors_7d", 0)
    pv_7d       = metrics.get("page_views_7d", 0)
    purchases   = metrics.get("purchases_7d", 0)
    plan        = metrics.get("plan", "unknown")

    # Route by query intent
    if any(w in query for w in ["error", "fail", "broken", "issue", "checkout"]):
        summary = (
            f"User {ctx['user_id']} has experienced {errors_7d} errors in the last 7 days, "
            f"primarily on /checkout. "
        )
        if has_support:
            summary += "They submitted a support message describing a 500 error on checkout. "
        summary += f"Churn risk is {churn_risk.upper()}. Recommend escalating to engineering."
        action = "escalate_to_engineering"
        confidence = 0.91

    elif any(w in query for w in ["churn", "cancel", "leave", "risk"]):
        summary = (
            f"User {ctx['user_id']} ({plan} plan) has {pv_7d} page views and "
            f"{purchases} purchases in the last 7 days. "
        )
        if has_pricing:
            summary += "They visited /pricing multiple times, suggesting price evaluation. "
        summary += f"Churn risk score: {churn_risk.upper()}."
        action = "trigger_retention_workflow" if churn_risk in ("high", "medium") else "no_action"
        confidence = 0.85

    elif any(w in query for w in ["upgrade", "convert", "purchase", "plan"]):
        summary = (
            f"User {ctx['user_id']} has made {purchases} purchases in the last 7 days "
            f"and is on the {plan} plan. "
        )
        if has_purchase:
            summary += "Recent purchase activity detected in context. "
        action = "send_upgrade_offer" if purchases > 0 else "nurture_sequence"
        confidence = 0.78

    else:
        summary = (
            f"User {ctx['user_id']}: {pv_7d} page views, {errors_7d} errors, "
            f"{purchases} purchases in last 7 days. Plan: {plan}. Churn risk: {churn_risk}."
        )
        action = "no_action"
        confidence = 0.70

    return {
        "summary":    summary,
        "action":     action,
        "confidence": confidence,
        "evidence":   [c["text"][:80] for c in ctx["chunks"][:2]],
        "grounded":   True,  # all claims traceable to context
    }


# ── OUTPUT VALIDATOR ──────────────────────────────────────────────────────────

def validate_output(output: dict) -> bool:
    """
    Basic validation before acting on LLM output.
    In production: use Pydantic model or JSON schema validation.
    """
    required = {"summary", "action", "confidence", "evidence", "grounded"}
    if not required.issubset(output.keys()):
        return False
    if not isinstance(output["confidence"], float) or not (0 <= output["confidence"] <= 1):
        return False
    if output["confidence"] < 0.6:
        print(f"  [WARN] Low confidence ({output['confidence']:.0%}) — flagging for human review")
    return True


# ── FULL PIPELINE ─────────────────────────────────────────────────────────────

def run_pipeline(query: str, user_id: str) -> dict | None:
    print(f"\n{'='*60}")
    print(f"[LLM PIPELINE] Query: \"{query}\"")
    print(f"[LLM PIPELINE] User: {user_id}")

    # Step 1: Retrieve context
    store = VectorStore(name="user_events")
    seed_store(store)
    ctx = retrieve(query, user_id, store)
    print(f"[RETRIEVE]     {ctx['chunk_count']} chunks + structured metrics assembled")

    # Step 2: Build prompt
    prompt = build_prompt(ctx)
    print(f"[PROMPT]       System + {len(prompt['user'])} chars of context")

    # Step 3: LLM call
    print(f"[LLM]          Calling model (mock)...")
    output = mock_llm_call(prompt, ctx)

    # Step 4: Validate
    if not validate_output(output):
        print(f"[VALIDATE]     Output validation failed — discarding response")
        return None

    # Step 5: Return
    print(f"\n[OUTPUT]")
    print(f"{'─'*60}")
    print(f"  Summary:    {output['summary']}")
    print(f"  Action:     {output['action']}")
    print(f"  Confidence: {output['confidence']:.0%}")
    print(f"  Evidence:   {output['evidence'][0][:70]}...")
    print(f"{'─'*60}")
    print(f"\n[NOTE] Metrics came from Pinot (computed). LLM only interpreted them.")

    return output


if __name__ == "__main__":
    run_pipeline("What checkout errors has this user experienced?", "u_001")
    run_pipeline("Is this user at risk of churning?", "u_001")
    run_pipeline("Is this user likely to upgrade?", "u_002")
