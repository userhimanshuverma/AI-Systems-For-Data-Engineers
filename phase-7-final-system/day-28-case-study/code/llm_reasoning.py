"""
Day 28 — LLM Reasoning & Quality Verification Layer
===================================================
Simulates model routing, prompt templating, token counting, cost reporting,
and hallucination checks (fact validation).
Features:
1. Dynamic Model Router: Route queries to utility, standard, or premium tiers.
2. Token Cost Accountant: Tracks cost of input & output tokens in USD.
3. Chaos rate limits: Throws 429 errors when active to trigger retry loops.
4. Hallucination Verifier: Check generated output user IDs against retrieval context.
"""

import time
import random
import hashlib
import json
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

from observability import logger, metrics
from failure_simulator import chaos_injector


class ModelTier(Enum):
    UTILITY = "utility"   # gpt-4o-mini
    STANDARD = "standard"  # gpt-4o
    PREMIUM = "premium"    # o1 / gpt-4-turbo


@dataclass
class ModelConfig:
    name: str
    tier: ModelTier
    cost_per_1k_input: float
    cost_per_1k_output: float
    avg_latency_sec: float
    max_tokens: int


MODEL_CATALOG = {
    ModelTier.UTILITY: ModelConfig(
        name="gpt-4o-mini",
        tier=ModelTier.UTILITY,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.00060,
        avg_latency_sec=0.3,
        max_tokens=128000
    ),
    ModelTier.STANDARD: ModelConfig(
        name="gpt-4o",
        tier=ModelTier.STANDARD,
        cost_per_1k_input=0.00250,
        cost_per_1k_output=0.01000,
        avg_latency_sec=0.8,
        max_tokens=128000
    ),
    ModelTier.PREMIUM: ModelConfig(
        name="gpt-4-turbo",
        tier=ModelTier.PREMIUM,
        cost_per_1k_input=0.01000,
        cost_per_1k_output=0.03000,
        avg_latency_sec=2.0,
        max_tokens=128000
    )
}


PROMPT_TEMPLATES = {
    "churn_analysis": {
        "system": (
            "You are an expert customer intelligence analyst specializing in enterprise retention. "
            "Examine the provided customer activity telemetry and behavioral similarity vector clusters. "
            "Identify accounts at risk, calculate financial ARR exposures, and outline a priority remediation playbook. "
            "Always reference actual customer IDs present in the context and ground your calculations."
        ),
        "user_template": (
            "Query: {query}\n\n"
            "Retrieved Telemetry & User Patterns:\n{context}\n\n"
            "Deliver a detailed analysis detailing:\n"
            "1. Highest churn risk accounts\n"
            "2. Critical failure metrics (error rate, billing failure counts)\n"
            "3. Playbook recommendations"
        )
    },
    "general_overview": {
        "system": "You are a business intelligence assistant. Summarize user activity records.",
        "user_template": "Query: {query}\n\nContext:\n{context}"
    }
}


RESPONSE_TEXTS = {
    "churn_analysis": (
        "### Enterprise Churn Risk Intelligence Report\n\n"
        "#### 1. High Churn Risk Cohorts\n"
        "Based on hybrid Reciprocal Rank Fusion, **{risk_count} premium accounts** are at elevated churn risk. "
        "The total ARR exposure is **${revenue_impact:,.2f}**.\n\n"
        "#### 2. Key Telemetry Anomaly Flags\n"
        "- **Billing Friction**: Card payment failures detected across multiple enterprise subscriptions (e.g. {flagged_users}).\n"
        "- **Technical Degradation**: Rolling workspace error rates spiked to {error_rate}% average for top-priority cohorts.\n"
        "- **Frustrated Sentiment**: Average support ticket sentiment index dipped below -0.40.\n\n"
        "#### 3. Immediate Action Plan\n"
        "1. **CSM Outreach**: Initiate proactive outreach to the accounts listed above within 24 hours.\n"
        "2. **Billing Grace Period**: Contact billing leads for accounts showing payment failures to prevent automated card suspends.\n"
        "3. **Engineering Review**: Task API team to resolve high error rates on workspace export endpoints."
    ),
    "general_overview": (
        "### Platform Analytics Summary\n\n"
        "Analyzed **{user_count} premium users** across the system.\n"
        "Active user trends are **{trend}** with an average customer health rating of **{health_score}/100**.\n"
        "Recommended action: investigate support queues for billing errors."
    )
}


@dataclass
class LLMResponse:
    """Structure encapsulating LLM output, token usage, and cost tracking."""
    content: str
    model_used: str
    model_tier: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    hallucinated: bool = False
    fact_checked: bool = True
    cached: bool = False


class LLMReasoningEngine:
    """Simulates LLM inference, dynamic model routing, and cost bookkeeping."""

    def __init__(self):
        self.response_cache: Dict[str, Tuple[LLMResponse, float]] = {}
        self.cache_ttl = 180.0 # 3 minutes

    def execute_reasoning(self, query: str, context: Dict[str, Any], intent: str = "general_overview", 
                          use_cache: bool = True) -> LLMResponse:
        """Process context through the prompt template and execute inference."""
        metrics.increment("llm_calls_total")
        start_time = time.time()

        # Cache Lookup
        cache_key = hashlib.md5(f"{query}_{intent}_{str(context)}".encode()).hexdigest()
        if use_cache and cache_key in self.response_cache:
            cached_res, cached_time = self.response_cache[cache_key]
            if (time.time() - cached_time) < self.cache_ttl:
                metrics.increment("llm_cache_hits_total")
                cached_res.cached = True
                logger.info(f"LLM Response Cache Hit for query intent: {intent}")
                return cached_res

        # Dynamic Model Routing
        model_tier = self._route_query(query, context, intent)
        config = MODEL_CATALOG[model_tier]

        # Injected Rate Limit Check (Chaos HTTP 429)
        if chaos_injector.is_llm_rate_limited():
            metrics.increment("llm_rate_limits_total")
            logger.error("LLM Gateway Error: 429 Too Many Requests (Rate limit exceeded).")
            raise RuntimeError("LLM Gateway rate limit reached (HTTP 429). Retry after 2s.")

        # Simulate API network call time
        base_delay = chaos_injector.get_llm_base_latency(model_tier.value)
        time.sleep(base_delay)

        # Assemble and Token Estimate Prompt
        prompt = self._compile_prompt(query, context, intent)
        input_tokens = len(prompt["system"] + prompt["user"]) // 4
        output_tokens = random.randint(150, 450)

        # Cost Bookkeeping
        cost = (
            (input_tokens / 1000.0) * config.cost_per_1k_input + 
            (output_tokens / 1000.0) * config.cost_per_1k_output
        )

        raw_response = self._render_simulated_response(intent, context)

        # Observability Metrics
        metrics.increment("llm_tokens_total", input_tokens + output_tokens)
        metrics.increment("llm_cost_usd_total", cost)

        # Hallucination Checker (Fact Check)
        hallucinated = self._fact_check_response(raw_response, context)

        actual_latency_ms = (time.time() - start_time) * 1000
        metrics.observe("llm_latency_ms", actual_latency_ms)

        response = LLMResponse(
            content=raw_response,
            model_used=config.name,
            model_tier=model_tier.value,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            latency_ms=round(actual_latency_ms, 1),
            hallucinated=hallucinated,
            fact_checked=True,
            cached=False
        )

        self.response_cache[cache_key] = (response, time.time())
        return response

    def _route_query(self, query: str, context: Dict[str, Any], intent: str) -> ModelTier:
        """Route to model based on estimated context volume and complexity."""
        context_size = len(str(context))
        
        # Simple health checking or very small contexts -> Utility mini model
        if intent == "general_overview" or context_size < 1000:
            return ModelTier.UTILITY
        
        # Churn analysis or deep lookalike modeling -> Premium model
        if intent in ["churn_analysis", "similar_users"]:
            return ModelTier.PREMIUM

        return ModelTier.STANDARD

    def _compile_prompt(self, query: str, context: Dict[str, Any], intent: str) -> Dict[str, str]:
        template = PROMPT_TEMPLATES.get(intent, PROMPT_TEMPLATES["general_overview"])
        context_str = json.dumps(context, indent=2)
        return {
            "system": template["system"],
            "user": template["user_template"].format(query=query, context=context_str)
        }

    def _render_simulated_response(self, intent: str, context: Dict[str, Any]) -> str:
        """Produce highly detailed responses based on context data."""
        template = RESPONSE_TEXTS.get(intent, RESPONSE_TEXTS["general_overview"])

        # Pull facts from context
        structured_telemetry = context.get("structured_telemetry", [])
        
        user_ids = []
        for line in structured_telemetry:
            if "User " in line:
                part = line.split("User ")[1].split(":")[0]
                user_ids.append(part)

        risk_count = len(user_ids) if user_ids else random.randint(5, 15)
        revenue_impact = sum(random.choice([3600.0, 12000.0, 60000.0]) for _ in range(risk_count))
        
        # Randomly choose users for billing flag description
        flagged_users = ", ".join(user_ids[:2]) if user_ids else "usr_prem_0012, usr_prem_0088"
        error_rate = round(random.uniform(5.5, 14.8), 2)
        
        # 3% chance of generating a hallucinated User ID (not present in context) to test our checker
        if random.random() < 0.03:
            flagged_users += ", usr_prem_HALLUCINATED_9999"

        if intent == "churn_analysis":
            return template.format(
                risk_count=risk_count,
                revenue_impact=revenue_impact,
                flagged_users=flagged_users,
                error_rate=error_rate
            )
        else:
            return template.format(
                user_count=risk_count,
                trend=random.choice(["improving", "stable", "degrading"]),
                health_score=random.randint(62, 88)
            )

    def _fact_check_response(self, content: str, context: Dict[str, Any]) -> bool:
        """Validate if any usr_prem_XXXX tokens mentioned in output are missing from context."""
        import re
        # Find all user tags in content
        tags_in_content = re.findall(r"usr_prem_\w+", content)
        if not tags_in_content:
            return False

        # Flatten context to string
        flat_context = str(context)

        hallucination_found = False
        for tag in tags_in_content:
            if tag not in flat_context:
                metrics.increment("llm_hallucinations_detected_total")
                logger.error(f"HALLUCINATION ALERT: LLM mentioned user ID '{tag}' which was absent in context!")
                hallucination_found = True
        
        return hallucination_found


if __name__ == "__main__":
    print("Testing LLM Reasoning Engine...")
    engine = LLMReasoningEngine()
    
    mock_context = {
        "structured_telemetry": [
            "User usr_prem_0001: Risk=0.88 | ERR=12% | Billing Fails=1 | Sentiment=-0.5 | ARR=$60000",
            "User usr_prem_0002: Risk=0.74 | ERR=4% | Billing Fails=0 | Sentiment=-0.2 | ARR=$12000"
        ],
        "semantic_similarities": [
            "Similar behavior signature matching cluster 'payment_delinquency' (User usr_prem_0001, similarity=0.91)"
        ]
    }
    
    response = engine.execute_reasoning(
        query="Analyze premium account risks",
        context=mock_context,
        intent="churn_analysis"
    )
    print("Model:", response.model_used, f"({response.model_tier})")
    print("Tokens:", response.input_tokens, "in,", response.output_tokens, "out")
    print("Cost:", response.cost_usd, "USD")
    print("Content preview:")
    print(response.content[:200])
