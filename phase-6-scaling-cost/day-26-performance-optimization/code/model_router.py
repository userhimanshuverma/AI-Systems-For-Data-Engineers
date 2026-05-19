import time

class ModelRouter:
    """
    Routes queries to different LLMs based on query complexity.
    Saves time and money on simple queries while preserving reasoning capability.
    """
    
    def __init__(self):
        # Simulated model latency/cost profiles
        self.models = {
            "fast_small": {"name": "Llama-3-8B", "latency": 0.5, "cost": 0.001},
            "medium": {"name": "GPT-4o-mini", "latency": 1.2, "cost": 0.005},
            "heavy_reasoning": {"name": "Claude-3.5-Sonnet", "latency": 5.5, "cost": 0.03}
        }

    def classify_complexity(self, query: str) -> str:
        """
        Fast heuristic or small-model classifier to determine task complexity.
        Takes ~10ms.
        """
        query_len = len(query.split())
        keywords = ["analyze", "compare", "why", "reason", "synthesize"]
        
        # If query asks for deep reasoning
        if any(kw in query.lower() for kw in keywords) or query_len > 30:
            return "heavy_reasoning"
            
        # If query needs some extraction or structure
        elif "summarize" in query.lower() or "extract" in query.lower():
            return "medium"
            
        # Default fast path (e.g., formatting, greeting, basic retrieval QA)
        else:
            return "fast_small"

    def execute_request(self, query: str):
        """Route the query to the appropriate model."""
        start_time = time.perf_counter()
        
        # 1. Routing phase
        route = self.classify_complexity(query)
        model = self.models[route]
        
        print(f"Routing '{query[:30]}...' -> {model['name']}")
        
        # 2. Simulated Generation phase
        time.sleep(model["latency"])
        
        total_time = time.perf_counter() - start_time
        
        return {
            "model_used": model["name"],
            "latency_seconds": round(total_time, 2),
            "estimated_cost": model["cost"]
        }

if __name__ == "__main__":
    router = ModelRouter()
    
    queries = [
        "Hello, what is your name?",  # Simple
        "Extract the date from this sentence: The contract was signed on Oct 5th.",  # Medium
        "Analyze the provided 5-page legal contract and compare it with our standard terms, explaining why the liability clause might be risky."  # Complex
    ]
    
    for q in queries:
        print(f"Query: {q}")
        result = router.execute_request(q)
        print(f"Result: {result}\n")
