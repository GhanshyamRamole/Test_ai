import sys
from pathlib import Path
import logging
from datetime import timedelta
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# Add parent dir to path to import config and docker_monitor
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import AWS_REGION, BEDROCK_MODEL_ID

# --- Import Activities from your existing modules ---
# We reuse the logic you already have to avoid duplication
from docker_monitor.docker_temporal_agent import (
    get_container_status_activity,
    check_container_health_activity,
    get_container_logs_activity,
    restart_container_activity
)
from simple_agent.temporal_agent import (
    get_time_activity,
    get_weather_activity,
    get_fact_activity
)

logger = logging.getLogger(__name__)

@activity.defn
async def unified_orchestrator_activity(task: str) -> str:
    """
    The 'Brain': Analyzes natural language and plans a sequence of actions 
    combining Docker ops and General utility tools.
    """
    from strands import Agent
    from strands.models import BedrockModel

    # Combined System Prompt handling both domains
    system_prompt = """You are a Super DevOps Agent. Analyze the user request and return a comma-separated list of operations.

    Available Docker Operations:
    - status[:filter]       -> Get container status
    - health[:container]    -> Check health 
    - logs:container[:lines]-> Get logs
    - restart:container     -> Restart container

    Available Utility Operations:
    - time                  -> Get current server time
    - weather:city          -> Get weather
    - fact:topic            -> Get an interesting fact

    Examples:
    "restart nginx and check weather in London" -> "restart:nginx, weather:London"
    "is redis healthy?"                         -> "health:redis"
    "what time is it and show logs for api"     -> "time, logs:api"

    Return ONLY the comma-separated plan. No explanations."""

    agent = Agent(
        model=BedrockModel(
            model_id=BEDROCK_MODEL_ID,
            region_name=AWS_REGION
        ),
        system_prompt=system_prompt
    )

    try:
        # Get the plan from the LLM
        result = agent(task)
        plan = str(result.content if hasattr(result, 'content') else result).strip()
        logger.info(f"Orchestrator Plan: {plan}")
        return plan
    except Exception as e:
        logger.error(f"Orchestration failed: {e}")
        return "status" # Fallback to a safe read-only op

@workflow.defn
class UnifiedAgentWorkflow:
    @workflow.run
    async def run(self, task: str) -> str:
        workflow.logger.info(f"Processing Unified Task: {task}")
        
        # Step 1: Ask the AI Orchestrator for a plan
        plan = await workflow.execute_activity(
            unified_orchestrator_activity,
            task,
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=2)
        )

        results = []
        operations = [op.strip() for op in plan.split(',') if op.strip()]

        # Step 2: Execute the plan
        for op_spec in operations:
            try:
                # Parse the operation string (e.g., "weather:London" -> op="weather", param="London")
                parts = op_spec.split(':')
                op_type = parts[0].lower()
                param1 = parts[1] if len(parts) > 1 else None
                param2 = parts[2] if len(parts) > 2 else None

                # --- Dispatcher Logic ---
                result = None
                
                # Docker Domain
                if op_type == 'status':
                    result = await workflow.execute_activity(get_container_status_activity, param1, start_to_close_timeout=timedelta(seconds=10))
                elif op_type == 'health':
                    result = await workflow.execute_activity(check_container_health_activity, param1, start_to_close_timeout=timedelta(seconds=15))
                elif op_type == 'logs':
                    lines = int(param2) if param2 else 100
                    result = await workflow.execute_activity(get_container_logs_activity, args=[param1, lines], start_to_close_timeout=timedelta(seconds=10))
                elif op_type == 'restart':
                    # High retry policy for critical mutations
                    result = await workflow.execute_activity(restart_container_activity, param1, start_to_close_timeout=timedelta(seconds=30), 
                        retry_policy=RetryPolicy(maximum_attempts=5))

                # Utility Domain
                elif op_type == 'time':
                    result = await workflow.execute_activity(get_time_activity, start_to_close_timeout=timedelta(seconds=5))
                elif op_type == 'weather' and param1:
                    result = await workflow.execute_activity(get_weather_activity, param1, start_to_close_timeout=timedelta(seconds=10))
                elif op_type == 'fact' and param1:
                    result = await workflow.execute_activity(get_fact_activity, param1, start_to_close_timeout=timedelta(seconds=20))
                
                else:
                    result = f"Skipped unknown operation: {op_spec}"

                results.append(result)

            except Exception as e:
                workflow.logger.error(f"Failed step {op_spec}: {e}")
                results.append(f"❌ Step '{op_spec}' failed: {str(e)}")

        return "\n\n".join(results)
