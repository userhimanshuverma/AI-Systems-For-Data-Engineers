import time
from functools import wraps

def track_latency(component_name: str):
    """
    A decorator to measure and log the execution time of a function.
    Essential for identifying bottlenecks in the AI pipeline.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            result = func(*args, **kwargs)
            end_time = time.perf_counter()
            
            latency_ms = (end_time - start_time) * 1000
            print(f"[{component_name}] Latency: {latency_ms:.2f} ms")
            return result
        return wrapper
    return decorator

class PipelineObserver:
    """Context manager to track blocks of code execution."""
    def __init__(self, block_name: str):
        self.block_name = block_name
        
    def __enter__(self):
        self.start = time.perf_counter()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        latency_ms = (time.perf_counter() - self.start) * 1000
        print(f"[Block: {self.block_name}] Latency: {latency_ms:.2f} ms")

# --- Demo Usage ---

@track_latency("Vector Search")
def mock_vector_search():
    time.sleep(0.2)  # 200ms latency

@track_latency("LLM Inference")
def mock_llm_call():
    time.sleep(1.5)  # 1500ms latency

def execute_pipeline():
    print("Executing full pipeline...")
    
    # Track specific blocks
    with PipelineObserver("Pre-processing"):
        time.sleep(0.05) # 50ms latency
        
    mock_vector_search()
    
    with PipelineObserver("Prompt Formatting"):
        time.sleep(0.02) # 20ms
        
    mock_llm_call()

if __name__ == "__main__":
    with PipelineObserver("TOTAL PIPELINE"):
        execute_pipeline()
