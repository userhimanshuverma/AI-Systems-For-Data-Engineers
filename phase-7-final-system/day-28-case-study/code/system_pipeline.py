"""
Day 28 — End-to-End System Pipeline & Chaos Simulation
=======================================================
Wires together the asynchronous data path (Kafka Ingestion + Flink Processing)
and the synchronous real-time query path (Pinot/Vector DB Retrieval + Agent 
Orchestration + LLM Reasoning) under telemetry span tracking.

Demonstrates 4 chaos failure scenarios:
1. Normal Operations (Low-latency SLAs)
2. Pinot Analytics Index Degradation (Injected Latency Spike -> Circuit Tripping)
3. Vector DB Ingestion Outage (Injected connection exception -> Fallback Routing)
4. LLM API Rate Limiting (Injected 429 Throttle -> Jittered Backoff Retries)
"""

import json
import time
from typing import Dict, List, Any, Optional

# Import system layers
from observability import logger, metrics, Trace
from failure_simulator import chaos_injector
from event_stream import KafkaEventStream, UserEvent
from stream_processor import FlinkStreamProcessor, EnrichedRecord, SinkType
from retrieval_engine import HybridRetrievalEngine
from agent_orchestrator import AgentOrchestrator, ToolStatus
from llm_reasoning import LLMReasoningEngine, LLMResponse


class EnterpriseIntelligencePipeline:
    """Consolidated pipeline for background events and user-facing reasoning queries."""

    def __init__(self):
        # Data Path
        self.kafka = KafkaEventStream(topic="user-analytics-stream", num_partitions=12)
        self.processor = FlinkStreamProcessor()

        # Query Path
        self.retrieval = HybridRetrievalEngine()
        self.orchestrator = AgentOrchestrator(self.retrieval)
        self.llm = LLMReasoningEngine()

    # ── Background Data Path ───────────────────────────────────────────────

    def ingest_background_traffic(self, count: int = 50) -> Dict[str, Any]:
        """Simulates background client events feeding into Kafka -> Flink -> Sinks."""
        print(f"\n[Data Path] Ingesting {count} customer activity events into Kafka...")
        start_time = time.time()

        raw_events = self.kafka.produce_batch(count)
        processed_records = []
        dlq_records = []

        for record in raw_events:
            event_dict = {
                "event_id": record["event"].event_id,
                "event_type": record["event"].event_type,
                "user_id": record["event"].user_id,
                "session_id": record["event"].session_id,
                "timestamp": record["event"].timestamp,
                "properties": record["event"].properties,
                "metadata": record["event"].metadata
            }
            # Flink Enrichment and Routing
            enriched = self.processor.process_event(event_dict)
            processed_records.append(enriched)
            
            if SinkType.DEAD_LETTER_QUEUE.value in enriched.sinks:
                dlq_records.append(enriched)

        elapsed = (time.time() - start_time) * 1000
        metrics.observe("data_path_batch_duration_ms", elapsed)

        print(f"[Data Path Success] Batch processed in {elapsed:.1f}ms. "
              f"Enriched: {len(processed_records) - len(dlq_records)} | DLQ: {len(dlq_records)}")

        return {
            "batch_size": count,
            "latency_ms": elapsed,
            "dlq_count": len(dlq_records)
        }

    # ── Real-Time Query Path ────────────────────────────────────────────────

    def execute_intelligence_query(self, query: str, budget_ms: float = 1500.0) -> Trace:
        """Process natural language analytical query under nested distributed tracing."""
        # Create distributed trace context
        trace = Trace(name="IntelligenceQueryFlow")
        trace.start_span("QueryUnderstandingIntent")
        trace.finish_span("SUCCESS")

        # Span 1: Hybrid Context Retrieval & Agent Orchestration
        trace.start_span("AgentOrchestrationAndRetrieval")
        orchestration_trace = self.orchestrator.orchestrate_query(query, budget_ms=budget_ms)
        
        # Pull details of tools called
        tool_details = []
        for call in orchestration_trace.tool_calls:
            tool_details.append({
                "tool": call.tool_name,
                "status": call.status.value,
                "latency_ms": round(call.latency_ms, 2)
            })

        trace.finish_span(
            status="SUCCESS" if orchestration_trace.status == "completed" else "DEGRADED",
            metadata={
                "orchestrator_status": orchestration_trace.status,
                "tools_triggered": tool_details
            }
        )

        # Span 2: LLM Reasoning
        trace.start_span("LLMReasoningAndVerification")
        
        # Decide query intent for template selection
        req = self.retrieval.parser.parse_query(query)
        
        response_obj: Optional[LLMResponse] = None
        error_msg = None
        
        try:
            response_obj = self.llm.execute_reasoning(
                query=query,
                context=orchestration_trace.context_assembled,
                intent=req.intent
            )
            trace.finish_span(
                status="SUCCESS",
                metadata={
                    "model": response_obj.model_used,
                    "tier": response_obj.model_tier,
                    "cost_usd": response_obj.cost_usd,
                    "tokens_input": response_obj.input_tokens,
                    "tokens_output": response_obj.output_tokens,
                    "hallucinated": response_obj.hallucinated,
                    "cached": response_obj.cached
                }
            )
        except Exception as e:
            error_msg = f"LLM Inference Failure: {e}"
            trace.finish_span("FAILURE", {"error": error_msg})
            # Core fallback response for UI stability
            response_obj = LLMResponse(
                content="[SLA VIOLATION ERROR] Intelligence Engine is temporarily degraded. "
                        "Our engineers have been paged. Pre-computed metrics show high ARR accounts are currently stable.",
                model_used="none",
                model_tier="none",
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=0.0,
                hallucinated=False,
                fact_checked=True
            )

        # Complete trace
        trace.finish(
            status="SUCCESS" if error_msg is None else "FAILURE",
            response_preview=response_obj.content[:150].replace("\n", " ") + "..."
        )

        # Print trace outcome to console in structured format
        print(f"\n[Query Path] Trace ID: {trace.trace_id} | Status: {trace.status} | Latency: {trace.total_latency_ms:.1f}ms")
        print(f"  +- Query: '{query}'")
        for span in trace.spans:
            print(f"  |-- Span: {span.name:<30s} | Status: {span.status:<10s} | Latency: {span.latency_ms:6.1f}ms")
            if span.metadata:
                print(f"     +- Meta: {span.metadata}")
        
        print(f"  +- LLM Model: {response_obj.model_used} | Cost: ${response_obj.cost_usd:.6f}")
        print(f"  +- Hallucination Flagged: {response_obj.hallucinated}")
        print(f"  +- Response Preview: {response_obj.content[:160].strip()}...")

        return trace


# ---------------------------------------------------------------------------
# Chaos Walkthrough Execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 80)
    print("  PRODUCTION DATA PIPELINE Chaos Simulation Framework")
    print("  Target System: User Activity Intelligence Platform")
    print("=" * 80)

    pipeline = EnterpriseIntelligencePipeline()

    # Step 1: Pre-populate background events
    pipeline.ingest_background_traffic(count=30)

    # ────── SCENARIO 1: NORMAL CONDITIONS ──────
    print("\n" + "=" * 80)
    print("  SCENARIO 1: NORMAL OPERATIONS (Healthy SLA)")
    print("=" * 80)
    chaos_injector.reset()
    
    # Process healthy analytical queries
    pipeline.execute_intelligence_query("Which enterprise users are at risk of churning?")
    # Second query for cache hit
    pipeline.execute_intelligence_query("Which enterprise users are at risk of churning?")

    # ────── SCENARIO 2: PINOT LATENCY SPIKE ──────
    print("\n" + "=" * 80)
    print("  SCENARIO 2: PINOT INDEX DEGRADATION (Analytical Table Scan Latency Spike)")
    print("=" * 80)
    chaos_injector.reset()
    chaos_injector.pinot_latency_spike = True # Inject query latency spike (Pinot SLA is 300ms, calls will take >1.2s)
    
    # Executing query under Pinot spike. The circuit breaker will try, detect SLA timeout, and trip.
    # Subsequent calls will fast-fail and route straight to pre-computed cached fallbacks.
    pipeline.execute_intelligence_query("Which enterprise users are at risk of churning?", budget_ms=1000.0)
    pipeline.execute_intelligence_query("Which enterprise users are at risk of churning?", budget_ms=1000.0)
    
    # ────── SCENARIO 3: VECTOR DB OUTAGE ──────
    print("\n" + "=" * 80)
    print("  SCENARIO 3: VECTOR DATABASE OUTAGE (Tripped Connection Failures)")
    print("=" * 80)
    chaos_injector.reset()
    chaos_injector.vector_db_outage = True # Simulates Vector DB 500 Outage
    
    # Semantic search throws exception. Orchestrator catches it, records failure, and degrades to keyword fallbacks.
    pipeline.execute_intelligence_query("Show me users similar to usr_prem_0042 in behavior patterns")
    pipeline.execute_intelligence_query("Show me users similar to usr_prem_0042 in behavior patterns")

    # ────── SCENARIO 4: LLM GATEWAY RATE LIMITS ──────
    print("\n" + "=" * 80)
    print("  SCENARIO 4: LLM GATEWAY RATE LIMIT STORM (HTTP 429 Throttle & Recovery)")
    print("=" * 80)
    chaos_injector.reset()
    chaos_injector.llm_rate_limit_active = True # 50% chance of throwing 429
    chaos_injector.retry_storm_active = True    # API congestion queue delay
    
    # Will trigger exponential retries with jitter and recover, or fall back if retries exceed limits
    pipeline.execute_intelligence_query("Which enterprise users are at risk of churning?")

    # ────── PROMETHEUS TELEMETRY REPORT ──────
    print("\n" + "=" * 80)
    print("  PROMETHEUS-STYLE TELEMETRY REPORT (Metrics Aggregator)")
    print("=" * 80)
    
    summary = metrics.get_metric_summary()
    
    print("\n[Metrics Counters]")
    for k, v in sorted(summary["counters"].items()):
        print(f"  {k:<55s} : {v}")

    print("\n[Metrics Latency Histograms]")
    for k, v in sorted(summary["histograms"].items()):
        print(f"  {k}:")
        print(f"    Count: {v['count']:<3d} | Avg: {v['avg']:6.2f}ms | P50: {v['p50']:6.2f}ms | P95: {v['p95']:6.2f}ms | P99: {v['p99']:6.2f}ms")
        print(f"    Range: {v['min']}ms - {v['max']}ms")

    print("\n" + "=" * 80)
    print("  Chaos Simulation complete.")
    print("=" * 80)
