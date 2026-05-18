"""
Microservice Simulation
Simulates deterministic workflows with independent services.
"""
import asyncio
import time
import random

async def retrieval_service(query):
    await asyncio.sleep(random.uniform(0.1, 0.2)) # DB latency
    return f"Retrieved docs for {query}"

async def generation_service(context):
    await asyncio.sleep(random.uniform(0.3, 0.5)) # LLM latency
    return f"Generated response based on {context}"

async def api_gateway(request):
    print(f"[API Gateway] Received request: {request}")
    start = time.time()
    
    # Deterministic sequence
    context = await retrieval_service(request)
    print(f"[Microservice] Context retrieved: {context}")
    
    response = await generation_service(context)
    print(f"[Microservice] Response generated: {response}")
    
    duration = time.time() - start
    print(f"[API Gateway] Completed in {duration:.2f}s")
    return response

if __name__ == "__main__":
    asyncio.run(api_gateway("User churn data"))
