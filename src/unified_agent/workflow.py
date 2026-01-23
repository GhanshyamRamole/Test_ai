import sys
from pathlib import Path
import logging
from datetime import timedelta
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# --- PATH FIX ---
# We are in src/unified_agent/workflow.py. 
# Go up 3 levels to reach project root (where config is)
root_path = Path(__file__).parents[2]
sys.path.insert(0, str(root_path))
# ----------------

from config import AWS_REGION, BEDROCK_MODEL_ID

# Activities are imported assuming 'src' is in path (handled by worker.py)
from providers.infra_monitor.docker_temporal_agent import (
    get_container_status_activity,
    check_container_health_activity,
    get_container_logs_activity,
    restart_container_activity
)
from providers.utility.temporal_agent import (
    get_time_activity,
    get_weather_activity,
    get_fact_activity
)

logger = logging.getLogger(__name__)

@activity.defn
async def unified_orchestrator_activity(task: str) -> str:
    """The 'Brain': Analyzes natural language and plans a sequence of actions."""
    try:
        from strands import Agent
        from strands.models import BedrockModel

        system_prompt = """You are a Super DevOps Agent. Analyze the user request and return a comma-separated list of operations.
        Available Operations:
        - status[:filter]
        - health[:container]
        - logs:container[:lines]
        - restart:container
        - time
        - weather:city
        - fact:topic
        
        Example: "restart nginx" -> "restart:nginx"
        Return ONLY the plan string."""

        agent = Agent(
            model=BedrockModel(model_id=BEDROCK_MODEL_ID, region_name=AWS_REGION),
            system_prompt=system_prompt
        )
        result = agent(task)
        plan = str(result.content if hasattr(result, 'content') else result).strip()
        logger.info(f"Orchestrator Plan: {plan}")
        return plan
    except Exception as e:
        logger.error(f"Orchestration failed: {e}")
        # Fallback for testing/error cases
        return "status"

@workflow.defn
class UnifiedAgentWorkflow:
    @workflow.run
    async def run(self, task: str) -> str:
        workflow.logger.info(f"Processing Unified Task: {task}")
        
        plan = await workflow.execute_activity(
            unified_orchestrator_activity,
            task,
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=2)
        )

        results = []
        operations = [op.strip() for op in plan.split(',') if op.strip()]

        for op_spec in operations:
            try:
                parts = op_spec.split(':')
                op_type = parts[0].lower()
                param1 = parts[1] if len(parts) > 1 else None
                param2 = parts[2] if len(parts) > 2 else None

                result = None
                
                if op_type == 'status':
                    result = await workflow.execute_activity(get_container_status_activity, param1, start_to_close_timeout=timedelta(seconds=10))
                elif op_type == 'health':
                    result = await workflow.execute_activity(check_container_health_activity, param1, start_to_close_timeout=timedelta(seconds=15))
                elif op_type == 'logs':
                    lines = int(param2) if param2 else 100
                    result = await workflow.execute_activity(get_container_logs_activity, args=[param1, lines], start_to_close_timeout=timedelta(seconds=10))
                elif op_type == 'restart':
                    result = await workflow.execute_activity(restart_container_activity, param1, start_to_close_timeout=timedelta(seconds=30))
                elif op_type == 'time':
                    result = await workflow.execute_activity(get_time_activity, start_to_close_timeout=timedelta(seconds=5))
                elif op_type == 'weather' and param1:
                    result = await workflow.execute_activity(get_weather_activity, param1, start_to_close_timeout=timedelta(seconds=10))
                elif op_type == 'fact' and param1:
                    result = await workflow.execute_activity(get_fact_activity, param1, start_to_close_timeout=timedelta(seconds=20))
                
                results.append(str(result))
            except Exception as e:
                results.append(f"❌ Step '{op_spec}' failed: {str(e)}")

        return "\n\n".join(results)
