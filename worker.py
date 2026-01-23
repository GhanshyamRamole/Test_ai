import asyncio
import sys
from pathlib import Path
from temporalio.client import Client
from temporalio.worker import Worker

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import TEMPORAL_HOST
from unified_agent.workflow import UnifiedAgentWorkflow, unified_orchestrator_activity

# Import all underlying activities

from providers.infra_monitor.docker_temporal_agent import (
    get_container_status_activity,
    check_container_health_activity,
    get_container_logs_activity,
    restart_container_activity
)
from providers.utility.temporal_agent import(
    get_time_activity,
    get_weather_activity,
    get_fact_activity
)

async def main():
    print("Starting Unified Super Agent Worker...")
    client = await Client.connect(TEMPORAL_HOST)
    
    worker = Worker(
        client,
        task_queue="unified-agent-queue",
        workflows=[UnifiedAgentWorkflow],
        activities=[
            # Orchestrator
            unified_orchestrator_activity,
            # Docker Domain
            get_container_status_activity,
            check_container_health_activity,
            get_container_logs_activity,
            restart_container_activity,
            # Utility Domain
            get_time_activity,
            get_weather_activity,
            get_fact_activity
        ]
    )
    
    print("Worker running. Press Ctrl+C to stop.")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
