"""
Multi-Agent Workflow
Simulates agents with adaptive reasoning and coordination overhead.
"""
import asyncio
import time
import random

async def agent_think(name, complexity):
    latency = random.uniform(0.2, 0.4) * complexity
    await asyncio.sleep(latency)
    return f"[{name}] Completed thought process."

async def research_agent(task):
    print(f"[Research Agent] Planning strategy for: {task}")
    await agent_think("Research Agent", complexity=2)
    return "Research findings data"

async def synthesis_agent(data):
    print(f"[Synthesis Agent] Synthesizing data...")
    await agent_think("Synthesis Agent", complexity=3)
    return "Final synthesized report"

async def coordinator_agent(request):
    print(f"[Coordinator Agent] Analyzing request: {request}")
    start = time.time()
    
    # Adaptive reasoning simulation (dynamic dispatch)
    await agent_think("Coordinator Agent", complexity=1)
    
    research_result = await research_agent(request)
    print(f"[Coordinator Agent] Received research results.")
    
    # Coordination overhead
    await asyncio.sleep(0.1) 
    
    final_result = await synthesis_agent(research_result)
    print(f"[Coordinator Agent] Received final synthesis.")
    
    duration = time.time() - start
    print(f"[Coordinator Agent] Task finished in {duration:.2f}s")
    return final_result

if __name__ == "__main__":
    asyncio.run(coordinator_agent("Analyze Q3 metrics"))
