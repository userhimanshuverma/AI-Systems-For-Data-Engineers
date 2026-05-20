"""
Day 27 — LLM Reasoning Layer (Simulation)
==========================================
Simulates the LLM reasoning tier that converts retrieved context
into actionable insights, explanations, and recommendations.

Architecture Role:
    The LLM is the LAST mile — it receives assembled context from the
    agent orchestrator and generates human-readable analysis. It does
    NOT retrieve data or make decisions about what to fetch.

Key Design Principles:
    1. LLM receives PRE-ASSEMBLED context — never raw data
    2. Prompt templates are versioned and A/B tested
    3. Model routing: cheap model for simple queries, premium for complex
    4. Response quality is validated before delivery
    5. Cost tracking per query for budget management

Production Considerations:
    - Prompt engineering: structured templates with system/user/context sections
    - Model selection: GPT-4o for complex reasoning, GPT-4o-mini for summaries
    - Token budget management: context window optimization
    - Streaming: SSE for real-time response delivery
    - Guardrails: output validation, hallucination detection
"""

import time
import random
import hashlib
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ModelTier(Enum):
    FAST = "fast"          # GPT-4o-mini, Claude Haiku — simple queries
    STANDARD = "standard"  # GPT-4o, Claude Sonnet — most queries
    PREMIUM = "premium"    # GPT-4, Claude Opus — complex reasoning


@dataclass
class ModelConfig:
    name: str
    tier: ModelTier
    cost_per_1k_input: float   # USD per 1K input tokens
    cost_per_1k_output: float  # USD per 1K output tokens
    avg_latency_ms: float
    max_context_tokens: int
    quality_score: float       # 0-1, relative quality


# Model catalog
MODEL_CATALOG = {
    ModelTier.FAST: ModelConfig(
        name="gpt-4o-mini",
        tier=ModelTier.FAST,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        avg_latency_ms=300,
        max_context_tokens=128000,
        quality_score=0.75,
    ),
    ModelTier.STANDARD: ModelConfig(
        name="gpt-4o",
        tier=ModelTier.STANDARD,
        cost_per_1k_input=0.0025,
        cost_per_1k_output=0.01,
        avg_latency_ms=800,
        max_context_tokens=128000,
        quality_score=0.90,
    ),
    ModelTier.PREMIUM: ModelConfig(
        name="gpt-4-turbo",
        tier=ModelTier.PREMIUM,
        cost_per_1k_input=0.01,
        cost_per_1k_output=0.03,
        avg_latency_ms=2000,
        max_context_tokens=128000,
        quality_score=0.98,
    ),
}


# ---------------------------------------------------------------------------
# Prompt Templates
# ---------------------------------------------------------------------------

PROMPT_TEMPLATES = {
    "churn_analysis": {
        "system": (
            "You are an expert customer intelligence analyst. Analyze the provided "
            "data to identify churn risks, root causes, and actionable retention strategies. "
            "Be specific with metrics and recommendations. Always ground your analysis "
            "in the provided data — never fabricate numbers."
        ),
        "user_template": (
            "## Query\n{query}\n\n"
            "## Retrieved Context\n{context}\n\n"
            "## Instructions\n"
            "1. Identify the top churn risk factors from the data\n"
            "2. Quantify revenue impact\n"
            "3. Recommend specific retention actions\n"
            "4. Prioritize by impact and feasibility"
        ),
    },
    "usage_analysis": {
        "system": (
            "You are a product analytics expert. Analyze usage patterns to identify "
            "engagement trends, feature adoption gaps, and growth opportunities."
        ),
        "user_template": (
            "## Query\n{query}\n\n"
            "## Retrieved Context\n{context}\n\n"
            "## Instructions\n"
            "1. Summarize key usage trends\n"
            "2. Identify under-utilized features\n"
            "3. Highlight engagement anomalies\n"
            "4. Suggest product improvements"
        ),
    },
    "general": {
        "system": (
            "You are an AI-powered business intelligence assistant. Provide clear, "
            "data-driven analysis based on the retrieved context."
        ),
        "user_template": (
            "## Query\n{query}\n\n"
            "## Retrieved Context\n{context}\n\n"
            "Provide a comprehensive analysis with actionable insights."
        ),
    },
}


# ---------------------------------------------------------------------------
# Response Generation (Simulated)
# ---------------------------------------------------------------------------

RESPONSE_TEMPLATES = {
    "churn_analysis": [
        (
            "## Churn Risk Analysis\n\n"
            "### Key Findings\n"
            "Based on the retrieved data, **{risk_count} users** are flagged as high churn risk, "
            "representing **${revenue_impact:,.0f}** in potential annual revenue loss.\n\n"
            "### Risk Factors\n"
            "1. **Declining Engagement**: {engagement_pct}% of at-risk users show >40% drop in "
            "weekly active sessions over the past 30 days\n"
            "2. **Support Friction**: Average of {ticket_count} support tickets per at-risk user "
            "(3.2x above healthy baseline)\n"
            "3. **Feature Abandonment**: Core feature adoption dropped to {adoption_rate}% "
            "from 78% in the prior quarter\n\n"
            "### Recommended Actions\n"
            "| Priority | Action | Expected Impact | Timeline |\n"
            "|----------|--------|-----------------|----------|\n"
            "| P0 | Proactive outreach to top 10 enterprise accounts | Retain ${p0_impact:,.0f} ARR | This week |\n"
            "| P1 | Fix onboarding flow for new feature | +15% adoption rate | 2 weeks |\n"
            "| P2 | Launch re-engagement email campaign | ~8% reactivation | 1 week |\n"
        ),
    ],
    "usage_analysis": [
        (
            "## Usage Pattern Analysis\n\n"
            "### Engagement Overview\n"
            "Active user engagement is trending **{trend}** with {active_users} daily active "
            "users across the platform. Average session duration: **{session_min} minutes**.\n\n"
            "### Feature Adoption\n"
            "- **High adoption**: Dashboard views (92%), Report generation (78%)\n"
            "- **Low adoption**: API integration ({api_pct}%), Webhook setup ({webhook_pct}%)\n"
            "- **Declining**: CSV export (down 23% MoM)\n\n"
            "### Recommendations\n"
            "1. Invest in API documentation and developer onboarding\n"
            "2. Add in-app tutorials for webhook configuration\n"
            "3. Investigate CSV export decline — may indicate competing workflow\n"
        ),
    ],
    "general": [
        (
            "## Analysis Summary\n\n"
            "Based on the available data across {source_count} sources:\n\n"
            "### Key Metrics\n"
            "- Users analyzed: **{user_count}**\n"
            "- Average health score: **{health_score}/100**\n"
            "- Revenue at risk: **${revenue:,.0f}**\n\n"
            "### Insights\n"
            "The data indicates {insight}. "
            "Recommend focusing on {recommendation} as the highest-leverage intervention.\n"
        ),
    ],
}


@dataclass
class LLMResponse:
    """Structured response from the LLM reasoning layer."""
    content: str = ""
    model_used: str = ""
    model_tier: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    prompt_version: str = "v1.0"
    quality_score: float = 0.0
    cached: bool = False


# ---------------------------------------------------------------------------
# LLM Reasoning Engine
# ---------------------------------------------------------------------------

class LLMReasoningEngine:
    """
    Manages prompt construction, model routing, response generation,
    and cost tracking for the reasoning layer.
    """

    def __init__(self):
        self.response_cache: Dict[str, LLMResponse] = {}
        self.cache_ttl = 300.0  # 5 minutes
        self.stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": 0.0,
            "model_usage": {tier.value: 0 for tier in ModelTier},
            "avg_latency_ms": 0.0,
            "_latency_sum": 0.0,
        }

    def reason(self, query: str, context: Dict, intent: str = "general") -> LLMResponse:
        """
        Generate a reasoned response for the given query and context.
        """
        self.stats["total_requests"] += 1

        # Check cache
        cache_key = hashlib.md5(f"{query}:{intent}".encode()).hexdigest()
        if cache_key in self.response_cache:
            cached = self.response_cache[cache_key]
            cached.cached = True
            self.stats["cache_hits"] += 1
            return cached

        # Route to appropriate model
        model_tier = self._route_model(query, context, intent)
        model = MODEL_CATALOG[model_tier]

        # Construct prompt
        prompt = self._build_prompt(query, context, intent)

        # Generate response (simulated)
        response = self._generate(prompt, model, intent)

        # Cache response
        self.response_cache[cache_key] = response

        # Update stats
        self.stats["total_input_tokens"] += response.input_tokens
        self.stats["total_output_tokens"] += response.output_tokens
        self.stats["total_cost_usd"] += response.cost_usd
        self.stats["model_usage"][model_tier.value] += 1
        self.stats["_latency_sum"] += response.latency_ms
        self.stats["avg_latency_ms"] = round(
            self.stats["_latency_sum"] / self.stats["total_requests"], 1
        )

        return response

    def _route_model(self, query: str, context: Dict, intent: str) -> ModelTier:
        """
        Intelligent model routing based on query complexity.

        Routing Rules:
            - Simple summaries / status checks → FAST (cheap, quick)
            - Standard analysis with moderate context → STANDARD
            - Complex multi-source reasoning → PREMIUM (expensive, thorough)
        """
        context_size = len(str(context))

        # Token estimate
        estimated_tokens = context_size // 4

        if intent in ("health_check",) and estimated_tokens < 1000:
            return ModelTier.FAST
        elif intent in ("churn_analysis", "similar_users") or estimated_tokens > 3000:
            return ModelTier.PREMIUM
        else:
            return ModelTier.STANDARD

    def _build_prompt(self, query: str, context: Dict, intent: str) -> Dict:
        """
        Construct a structured prompt from templates and context.
        """
        template = PROMPT_TEMPLATES.get(intent, PROMPT_TEMPLATES["general"])

        # Format context for injection
        context_str = self._format_context(context)

        return {
            "system": template["system"],
            "user": template["user_template"].format(
                query=query,
                context=context_str,
            ),
        }

    def _format_context(self, context: Dict) -> str:
        """Format assembled context into a clean string for the prompt."""
        parts = []
        for key, value in context.items():
            if isinstance(value, list):
                for item in value:
                    parts.append(str(item))
            elif isinstance(value, dict):
                for k, v in value.items():
                    parts.append(f"- {k}: {v}")
            else:
                parts.append(f"- {key}: {value}")
        return "\n".join(parts) if parts else "No additional context available."

    def _generate(self, prompt: Dict, model: ModelConfig, intent: str) -> LLMResponse:
        """
        Simulate LLM response generation.
        In production: API call to OpenAI/Anthropic with streaming.
        """
        start = time.time()

        # Simulate latency
        latency = model.avg_latency_ms + random.uniform(-200, 400)
        time.sleep(max(latency / 1000, 0.05))

        # Token estimation
        input_tokens = len(prompt["system"] + prompt["user"]) // 4
        output_tokens = random.randint(200, 800)

        # Cost calculation
        cost = (
            (input_tokens / 1000) * model.cost_per_1k_input +
            (output_tokens / 1000) * model.cost_per_1k_output
        )

        # Generate response from templates
        content = self._render_response(intent)

        actual_latency = (time.time() - start) * 1000

        return LLMResponse(
            content=content,
            model_used=model.name,
            model_tier=model.tier.value,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            latency_ms=round(actual_latency, 1),
            quality_score=model.quality_score,
        )

    def _render_response(self, intent: str) -> str:
        """Render a simulated response from templates."""
        templates = RESPONSE_TEMPLATES.get(intent, RESPONSE_TEMPLATES["general"])
        template = random.choice(templates)

        # Fill in template variables with realistic values
        try:
            return template.format(
                risk_count=random.randint(8, 45),
                revenue_impact=random.uniform(50000, 500000),
                engagement_pct=random.randint(55, 85),
                ticket_count=random.randint(3, 12),
                adoption_rate=random.randint(35, 65),
                p0_impact=random.uniform(100000, 800000),
                trend=random.choice(["upward", "stable", "downward"]),
                active_users=random.randint(500, 5000),
                session_min=round(random.uniform(5, 35), 1),
                api_pct=random.randint(15, 40),
                webhook_pct=random.randint(8, 25),
                source_count=random.randint(2, 5),
                user_count=random.randint(50, 500),
                health_score=random.randint(45, 85),
                revenue=random.uniform(10000, 200000),
                insight="a correlation between declining feature adoption and increased support volume",
                recommendation="proactive customer success outreach for the enterprise segment",
            )
        except (KeyError, IndexError):
            return template

    def get_metrics(self) -> Dict:
        total = self.stats["total_requests"]
        return {
            "total_requests": total,
            "cache_hits": self.stats["cache_hits"],
            "cache_hit_rate": round(self.stats["cache_hits"] / max(total, 1), 3),
            "total_input_tokens": self.stats["total_input_tokens"],
            "total_output_tokens": self.stats["total_output_tokens"],
            "total_tokens": self.stats["total_input_tokens"] + self.stats["total_output_tokens"],
            "total_cost_usd": round(self.stats["total_cost_usd"], 4),
            "avg_cost_per_query": round(self.stats["total_cost_usd"] / max(total, 1), 6),
            "model_usage": self.stats["model_usage"],
            "avg_latency_ms": self.stats["avg_latency_ms"],
        }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  LLM REASONING ENGINE — Intelligence Layer")
    print("=" * 70)

    engine = LLMReasoningEngine()

    test_cases = [
        {
            "query": "Which enterprise users are at risk of churning?",
            "intent": "churn_analysis",
            "context": {
                "structured_retrieval": {"users_at_risk": 23, "avg_churn_score": 0.72},
                "semantic_retrieval": {"patterns": ["declining_engagement", "support_heavy"]},
                "feature_lookup": {"user_0042": {"health_score": 32.1, "events_24h": 2}},
            },
        },
        {
            "query": "Show me usage trends for the professional tier",
            "intent": "usage_analysis",
            "context": {
                "structured_retrieval": {"active_users": 1240, "avg_sessions": 4.2},
            },
        },
        {
            "query": "Quick health check for user_0042",
            "intent": "health_check",
            "context": {
                "feature_lookup": {"user_0042": {"health_score": 82.5}},
            },
        },
    ]

    for tc in test_cases:
        print(f"\n{'─' * 60}")
        print(f"  Query  : {tc['query']}")
        print(f"  Intent : {tc['intent']}")
        print(f"{'─' * 60}")

        response = engine.reason(tc["query"], tc["context"], tc["intent"])

        print(f"  Model      : {response.model_used} ({response.model_tier})")
        print(f"  Tokens     : {response.input_tokens} in / {response.output_tokens} out")
        print(f"  Cost       : ${response.cost_usd:.6f}")
        print(f"  Latency    : {response.latency_ms:.0f} ms")
        print(f"  Quality    : {response.quality_score:.0%}")
        print(f"  Cached     : {response.cached}")
        print(f"\n  Response Preview:")
        # Show first 3 lines
        for line in response.content.strip().split("\n")[:5]:
            print(f"    {line}")
        print(f"    ...")

    # Metrics
    metrics = engine.get_metrics()
    print(f"\n{'═' * 70}")
    print("  LLM METRICS")
    print(f"{'═' * 70}")
    print(f"  Total Requests   : {metrics['total_requests']}")
    print(f"  Cache Hit Rate   : {metrics['cache_hit_rate']:.0%}")
    print(f"  Total Tokens     : {metrics['total_tokens']:,}")
    print(f"  Total Cost       : ${metrics['total_cost_usd']:.4f}")
    print(f"  Avg Cost/Query   : ${metrics['avg_cost_per_query']:.6f}")
    print(f"  Avg Latency      : {metrics['avg_latency_ms']:.0f} ms")
    print(f"  Model Usage      : {metrics['model_usage']}")

    print("\n✓ LLM reasoning demo complete.")
