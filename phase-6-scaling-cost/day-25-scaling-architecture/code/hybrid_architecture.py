"""
Hybrid Architecture
Agents handle adaptive reasoning, microservices handle deterministic tasks.
"""
import asyncio
import time

# --- Microservices (Deterministic) ---
async def vector_retrieval_service(query):
    await asyncio.sleep(0.1) # Fast, scalable DB lookup
    return f"Vector docs for {query}"

async def calculation_service(data):
    await asyncio.sleep(0.05) # Fast compute
    return f"Computed stats for {data}"

# --- Agents (Adaptive) ---
async def analyst_agent(request):
    print(f"[Analyst Agent] Decomposing request: {request}")
    
    # Agent calls deterministic microservices directly (bounded scope)
    print(f"[Analyst Agent] Dispatching vector retrieval...")
    docs = await vector_retrieval_service(request)
    print(f"[Analyst Agent] Got docs: {docs}")
    
    print(f"[Analyst Agent] Dispatching stats calculation...")
    stats = await calculation_service(docs)
    print(f"[Analyst Agent] Got stats: {stats}")
    
    print(f"[Analyst Agent] Synthesizing final response...")
    await asyncio.sleep(0.3) # LLM synthesis latency
    
    return f"Hybrid report combining {docs} and {stats}"

async def main():
    start = time.time()
    result = await analyst_agent("Enterprise retention trend")
    duration = time.time() - start
    print(f"[Result] {result} \n(Total Time: {duration:.2f}s)")

if __name__ == "__main__":
    asyncio.run(main())
