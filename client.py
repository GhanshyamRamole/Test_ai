import asyncio
import uuid
import sys
from pathlib import Path
from temporalio.client import Client

src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from config import TEMPORAL_HOST
from unified_agent.workflow import UnifiedAgentWorkflow

async def main():
    print("="*50)
    print("Unified Super Agent Client")
    print("Capabilities: Docker Ops + Weather + Facts + Time")
    print("="*50)
    
    client = await Client.connect(TEMPORAL_HOST)

    while True:
        task = input("\nAgent Task (or 'q' to quit): ").strip()
        if task.lower() == 'q': break
        if not task: continue

        run_id = f"unified-{uuid.uuid4()}"
        print(f"Executing workflow {run_id}...")

        result = await client.execute_workflow(
            UnifiedAgentWorkflow.run,
            task,
            id=run_id,
            task_queue="unified-agent-queue"
        )
        
        print("\n--- AGENT REPORT ---")
        print(result)
        print("--------------------")

if __name__ == "__main__":
    asyncio.run(main())
