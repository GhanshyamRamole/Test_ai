"""Temporal Docker Container Health Monitor with automatic retries and fault tolerance."""

import logging
from datetime import timedelta
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

# --- Imports fixed for 'src' structure ---
from config import AWS_REGION, BEDROCK_MODEL_ID

logger = logging.getLogger(__name__)

@activity.defn
async def get_container_status_activity(filter_by: str = None) -> str:
    """Get container status with optional filtering."""
    # Fixed Import
    from providers.infra_monitor.docker_utils import DockerClientWrapper, DockerConnectionError
    
    activity.logger.info(f"Getting container status, filter: {filter_by}")
    
    try:
        docker_client = DockerClientWrapper()
        
        filters = None
        if filter_by:
            if filter_by.lower() in ['running', 'stopped', 'paused', 'exited', 'restarting']:
                filters = {'status': filter_by.lower()}
            else:
                filters = {'name': filter_by}
        
        containers = docker_client.get_containers(all=True, filters=filters)
        
        if not containers:
            return f"No containers found matching '{filter_by}'" if filter_by else "No containers found on this system"
        
        result = [f"Found {len(containers)} container(s):\n"]
        for container in containers:
            result.append(container.format_summary())
            result.append("")
        
        activity.logger.info(f"Successfully retrieved {len(containers)} containers")
        return "\n".join(result)
        
    except DockerConnectionError as e:
        activity.logger.error(f"Docker connection error: {e}")
        raise
    except Exception as e:
        activity.logger.exception("Unexpected error in get_container_status_activity")
        raise ApplicationError(f"Unexpected error: {str(e)}", non_retryable=True)


@activity.defn
async def check_container_health_activity(container_name: str = None) -> str:
    """Check health of specific container or all containers."""
    # Fixed Import
    from providers.infra_monitor.docker_utils import DockerClientWrapper, DockerConnectionError, ContainerNotFoundError
    
    activity.logger.info(f"Checking container health: {container_name or 'all'}")
    
    try:
        docker_client = DockerClientWrapper()
        
        if container_name:
            health = docker_client.check_container_health(container_name)
            activity.logger.info(f"Health check complete for {container_name}: {'healthy' if health.is_healthy else 'unhealthy'}")
            return health.format_summary()
        
        containers = docker_client.get_containers(all=False)
        if not containers:
            return "No running containers found"
        
        results = [f"Health check for {len(containers)} running container(s):\n"]
        healthy_count = 0
        
        for container in containers:
            try:
                health = docker_client.check_container_health(container.name)
                results.append(health.format_summary())
                results.append("")
                if health.is_healthy:
                    healthy_count += 1
            except Exception as e:
                results.append(f"✗ {container.name}: Error checking health - {str(e)}")
                results.append("")
        
        results.append(f"Summary: {healthy_count}/{len(containers)} containers healthy")
        activity.logger.info(f"Health check complete: {healthy_count}/{len(containers)} healthy")
        return "\n".join(results)
        
    except ContainerNotFoundError as e:
        activity.logger.error(f"Container not found: {e}")
        raise ApplicationError(f"Container '{e.container_name}' not found", non_retryable=True)
    except DockerConnectionError as e:
        activity.logger.error(f"Docker connection error: {e}")
        raise
    except Exception as e:
        activity.logger.exception("Unexpected error in check_container_health_activity")
        raise ApplicationError(f"Unexpected error: {str(e)}", non_retryable=True)


@activity.defn
async def get_container_logs_activity(container_name: str, lines: int = 100) -> str:
    """Retrieve container logs."""
    # Fixed Import
    from providers.infra_monitor.docker_utils import DockerClientWrapper, DockerConnectionError, ContainerNotFoundError
    
    activity.logger.info(f"Getting logs for {container_name}, lines: {lines}")
    
    try:
        docker_client = DockerClientWrapper()
        logs = docker_client.get_container_logs(container_name, lines=lines)
        
        if not logs:
            return f"No logs found for container '{container_name}'"
        
        result = f"Last {lines} lines from container '{container_name}':\n"
        result += "=" * 60 + "\n"
        result += logs
        
        activity.logger.info(f"Successfully retrieved logs for {container_name}")
        return result
        
    except ContainerNotFoundError as e:
        activity.logger.error(f"Container not found: {e}")
        raise ApplicationError(f"Container '{e.container_name}' not found", non_retryable=True)
    except DockerConnectionError as e:
        activity.logger.error(f"Docker connection error: {e}")
        raise
    except Exception as e:
        activity.logger.exception("Unexpected error in get_container_logs_activity")
        raise ApplicationError(f"Unexpected error: {str(e)}", non_retryable=True)


@activity.defn
async def restart_container_activity(container_name: str) -> str:
    """Restart a container."""
    # Fixed Import
    from providers.infra_monitor.docker_utils import DockerClientWrapper, DockerConnectionError, ContainerNotFoundError
    
    activity.logger.info(f"Restarting container: {container_name}")
    
    try:
        docker_client = DockerClientWrapper()
        success = docker_client.restart_container(container_name)
        
        if success:
            activity.logger.info(f"Successfully restarted {container_name}")
            return f"✓ Successfully restarted container '{container_name}'"
        
        activity.logger.warning(f"Container {container_name} restarted but may not be running properly")
        return f"Container '{container_name}' was restarted but may not be running properly"
        
    except ContainerNotFoundError as e:
        activity.logger.error(f"Container not found: {e}")
        raise ApplicationError(f"Container '{e.container_name}' not found", non_retryable=True)
    except DockerConnectionError as e:
        activity.logger.error(f"Docker connection error: {e}")
        raise
    except Exception as e:
        activity.logger.exception("Unexpected error in restart_container_activity")
        raise ApplicationError(f"Unexpected error: {str(e)}", non_retryable=True)


