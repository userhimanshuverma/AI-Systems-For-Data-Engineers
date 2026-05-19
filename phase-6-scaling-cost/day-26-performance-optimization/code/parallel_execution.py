import asyncio
import time
import random

async def fetch_postgres():
    """Simulate fetching user profile from SQL."""
    await asyncio.sleep(0.3)  # 300ms network/query latency
    return {"user_id": "U123", "tier": "enterprise"}

async def fetch_vector_db():
    """Simulate retrieving context from Pinecone/Milvus."""
    await asyncio.sleep(0.4)  # 400ms embedding + search latency
    return ["Doc1: User complained about latency.", "Doc2: Contract up for renewal."]

async def fetch_external_crm():
    """Simulate hitting Salesforce API."""
    await asyncio.sleep(0.6)  # 600ms slow external API
    return {"last_contact": "2023-10-01", "sentiment": "neutral"}

def run_sequential():
    """Anti-pattern: Running independent I/O tasks sequentially."""
    print("Starting Sequential Execution...")
    start = time.perf_counter()
    
    # Simulating blocking synchronous calls
    time.sleep(0.3) # pg
    time.sleep(0.4) # vector
    time.sleep(0.6) # crm
    
    end = time.perf_counter()
    print(f"Sequential Execution Time: {end - start:.2f} seconds\n")

async def run_parallel():
    """Optimized: Running independent tasks concurrently."""
    print("Starting Parallel Execution...")
    start = time.perf_counter()
    
    # Gather runs tasks concurrently and waits for all to finish
    results = await asyncio.gather(
        fetch_postgres(),
        fetch_vector_db(),
        fetch_external_crm()
    )
    
    end = time.perf_counter()
    print(f"Parallel Execution Time: {end - start:.2f} seconds")
    print("Data retrieved:", results)

if __name__ == "__main__":
    # The total time will be roughly the max of the individual latencies (0.6s)
    # compared to the sum in sequential (1.3s)
    run_sequential()
    asyncio.run(run_parallel())
