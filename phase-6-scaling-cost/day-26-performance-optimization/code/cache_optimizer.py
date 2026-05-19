import hashlib
import time

class CacheOptimizer:
    def __init__(self):
        # In memory store simulating Redis or GPTCache
        self.exact_cache = {}
        self.semantic_cache_embeddings = []  # List of tuples: (embedding, response)

    def hash_query(self, query: str) -> str:
        """Create an MD5 hash for exact matching."""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    def check_exact_cache(self, query: str):
        """O(1) lookup for exact string matches."""
        q_hash = self.hash_query(query)
        if q_hash in self.exact_cache:
            print(f"[CACHE HIT - EXACT] Query: '{query}'")
            return self.exact_cache[q_hash]
        return None

    def check_semantic_cache(self, query: str):
        """
        O(N) simulated lookup for semantic similarity.
        In production, this would be a vector DB query (e.g., Pinecone/Milvus)
        using Cosine Similarity on embeddings.
        """
        # Simulating a slow vector generation + search
        time.sleep(0.05) 
        
        # Simple string matching to simulate semantic matching for this demo
        for cached_query, response in self.semantic_cache_embeddings:
            # If 80% of words overlap, call it a semantic match
            words_query = set(query.lower().split())
            words_cached = set(cached_query.lower().split())
            overlap = len(words_query.intersection(words_cached)) / max(len(words_query), 1)
            
            if overlap > 0.8:
                print(f"[CACHE HIT - SEMANTIC] Query: '{query}' matched with '{cached_query}'")
                return response
        return None

    def execute_query(self, query: str):
        """Simulate LLM Execution with Caching."""
        start = time.perf_counter()
        
        # 1. Try Exact Cache (0ms latency)
        result = self.check_exact_cache(query)
        if result:
            latency = time.perf_counter() - start
            return result, latency

        # 2. Try Semantic Cache (50ms latency)
        result = self.check_semantic_cache(query)
        if result:
            latency = time.perf_counter() - start
            return result, latency

        # 3. Cache Miss: Run actual LLM (Simulated 2000ms latency)
        print(f"[CACHE MISS] Executing LLM generation for: '{query}'")
        time.sleep(2.0)  # Simulate API latency
        result = f"Simulated AI Response for: {query}"
        
        # Store in both caches
        self.exact_cache[self.hash_query(query)] = result
        self.semantic_cache_embeddings.append((query, result))
        
        latency = time.perf_counter() - start
        return result, latency

if __name__ == "__main__":
    optimizer = CacheOptimizer()
    
    print("--- First Run (Miss expected) ---")
    res, t = optimizer.execute_query("What is the churn rate in Q3?")
    print(f"Time: {t:.4f}s | Response: {res}\n")
    
    print("--- Second Run: Exact Match ---")
    res, t = optimizer.execute_query("What is the churn rate in Q3?")
    print(f"Time: {t:.4f}s | Response: {res}\n")
    
    print("--- Third Run: Semantic Match ---")
    res, t = optimizer.execute_query("What was the churn rate in Q3?")
    print(f"Time: {t:.4f}s | Response: {res}\n")
