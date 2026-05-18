"""
Scaling Comparison
Simulates how different architectures handle concurrent load.
"""
import asyncio
import time
import random

async def simulate_architecture(name, concurrent_requests, base_latency, overhead_factor):
    """
    Simulate processing concurrent requests.
    - `overhead_factor` simulates how much the latency degrades as load increases.
      Highly coordinated systems (Multi-Agent) degrade faster.
    """
    async def request(i):
        # As load increases, overhead grows non-linearly for highly coordinated systems
        load_penalty = (concurrent_requests / 10) * overhead_factor
        latency = base_latency + load_penalty + random.uniform(0, 0.1)
        await asyncio.sleep(latency)
        return latency

    start = time.time()
    latencies = await asyncio.gather(*(request(i) for i in range(concurrent_requests)))
    duration = time.time() - start
    
    avg_latency = sum(latencies) / len(latencies)
    print(f"{name:15} | Requests: {concurrent_requests:4} | Total Time: {duration:.2f}s | Avg Latency: {avg_latency:.2f}s")

async def main():
    print("--- Scaling Architecture Simulation ---")
    loads = [10, 50, 200]
    
    for load in loads:
        print(f"\n[ Load: {load} concurrent requests ]")
        
        # Microservices: Low overhead factor (highly independent, easily scaled)
        await simulate_architecture("Microservices", load, base_latency=0.5, overhead_factor=0.01)
        
        # Multi-Agent: High overhead factor (coordination bottlenecks, token sync)
        await simulate_architecture("Multi-Agent", load, base_latency=0.8, overhead_factor=0.1)
        
        # Hybrid: Balanced (Adaptive logic isolated, heavy lifting delegated)
        await simulate_architecture("Hybrid", load, base_latency=0.6, overhead_factor=0.03)

if __name__ == "__main__":
    asyncio.run(main())
