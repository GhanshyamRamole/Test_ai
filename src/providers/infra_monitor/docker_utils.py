"""Docker utilities for container health monitoring with consistent error handling."""

import sys
from pathlib import Path
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any
import docker
from docker.errors import DockerException, NotFound, APIError

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    DOCKER_HOST,
    DOCKER_TIMEOUT,
    CPU_THRESHOLD_PERCENT,
    MEMORY_THRESHOLD_PERCENT,
    RESTART_COUNT_THRESHOLD
)

logger = logging.getLogger(__name__)


class DockerConnectionError(Exception):
    """Raised when unable to connect to Docker daemon."""
    pass


class ContainerNotFoundError(Exception):
    """Raised when specified container doesn't exist."""
    def __init__(self, container_name: str):
        self.container_name = container_name
        super().__init__(f"Container '{container_name}' not found")


@dataclass
class ContainerInfo:
    """Information about a Docker container."""
    id: str
    name: str
    status: str
    image: str
    created: datetime
    started: Optional[datetime] = None
    ports: Dict[str, List[str]] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.id:
            raise ValueError("Container ID cannot be empty")
        if not self.name:
            raise ValueError("Container name cannot be empty")
        if self.status not in ['running', 'stopped', 'restarting', 'paused', 'exited', 'created', 'removing', 'dead']:
            logger.warning(f"Unexpected container status: {self.status}")
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'image': self.image,
            'created': self.created.isoformat(),
            'started': self.started.isoformat() if self.started else None,
            'ports': self.ports,
            'labels': self.labels
        }
    
    def format_summary(self) -> str:
        uptime = ""
        if self.started:
            delta = datetime.now(self.started.tzinfo) - self.started
            hours = delta.total_seconds() / 3600
            if hours < 1:
                uptime = f"{int(delta.total_seconds() / 60)} minutes"
            elif hours < 24:
                uptime = f"{int(hours)} hours"
            else:
                uptime = f"{int(hours / 24)} days"
        
        port_str = ", ".join([f"{k}->{','.join(v)}" for k, v in self.ports.items()]) if self.ports else "none"
        
        return (
            f"Container: {self.name} ({self.id})\n"
            f"  Status: {self.status}\n"
            f"  Image: {self.image}\n"
            f"  Uptime: {uptime if uptime else 'not started'}\n"
            f"  Ports: {port_str}"
        )


@dataclass
class HealthStatus:
    """Health status of a Docker container."""
    container_name: str
    is_healthy: bool
    status: str
    health_check_status: Optional[str] = None
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    restart_count: int = 0
    last_restart: Optional[datetime] = None
    issues: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.container_name:
            raise ValueError("Container name cannot be empty")
        if self.cpu_percent is not None and (self.cpu_percent < 0 or self.cpu_percent > 100 * 100):
            logger.warning(f"CPU percent out of expected range: {self.cpu_percent}")
        if self.memory_percent is not None and (self.memory_percent < 0 or self.memory_percent > 100):
            logger.warning(f"Memory percent out of expected range: {self.memory_percent}")
    
    def to_dict(self) -> dict:
        return {
            'container_name': self.container_name,
            'is_healthy': self.is_healthy,
            'status': self.status,
            'health_check_status': self.health_check_status,
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'restart_count': self.restart_count,
            'last_restart': self.last_restart.isoformat() if self.last_restart else None,
            'issues': self.issues
        }
    
    def format_summary(self) -> str:
        health_icon = "✓" if self.is_healthy else "✗"
        health_text = "Healthy" if self.is_healthy else "Unhealthy"
        
        lines = [
            f"{health_icon} {self.container_name}: {health_text}",
            f"  Status: {self.status}"
        ]
        
        if self.health_check_status:
            lines.append(f"  Health Check: {self.health_check_status}")
        
        if self.cpu_percent is not None:
            lines.append(f"  CPU: {self.cpu_percent:.1f}%")
        
        if self.memory_percent is not None:
            lines.append(f"  Memory: {self.memory_percent:.1f}%")
        
        if self.restart_count > 0:
            lines.append(f"  Restarts: {self.restart_count}")
        
        if self.issues:
            lines.append(f"  Issues: {', '.join(self.issues)}")
        
        return "\n".join(lines)


@dataclass
class OperationResult:
    """Result of a Docker operation."""
    operation: str
    success: bool
    data: Any
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def __post_init__(self):
        if not self.operation:
            raise ValueError("Operation name cannot be empty")
    
    def to_dict(self) -> dict:
        return {
            'operation': self.operation,
            'success': self.success,
            'data': self.data,
            'error': self.error,
            'timestamp': self.timestamp.isoformat()
        }
    
    def format_summary(self) -> str:
        status = "Success" if self.success else "Failed"
        result = f"Operation: {self.operation} - {status}"
        if self.error:
            result += f"\nError: {self.error}"
        return result


class DockerClientWrapper:
    """Wrapper around Docker SDK with consistent error handling and structured data types."""
    
    def __init__(self):
        try:
            self.client = docker.from_env(timeout=DOCKER_TIMEOUT)
            self.client.ping()
            logger.info("Successfully connected to Docker daemon")
        except DockerException as e:
            logger.error(f"Failed to connect to Docker daemon: {e}")
            raise DockerConnectionError(
                "Docker daemon is not accessible. Please ensure Docker is running."
            ) from e
    
    def get_containers(self, all: bool = True, filters: dict = None) -> List[ContainerInfo]:
        """Get list of containers with optional filtering."""
        try:
            containers = self.client.containers.list(all=all, filters=filters)
            return [self._container_to_info(c) for c in containers]
        except DockerException as e:
            logger.error(f"Failed to list containers: {e}")
            raise DockerConnectionError(
                "Failed to retrieve container list from Docker daemon"
            ) from e
    
    def _container_to_info(self, container) -> ContainerInfo:
        """Convert Docker container object to ContainerInfo."""
        created_str = container.attrs.get('Created', '')
        created = datetime.fromisoformat(created_str.replace('Z', '+00:00')) if created_str else datetime.now()
        
        started = None
        state = container.attrs.get('State', {})
        started_str = state.get('StartedAt', '')
        if started_str and started_str != '0001-01-01T00:00:00Z':
            started = datetime.fromisoformat(started_str.replace('Z', '+00:00'))
        
        ports = {}
        port_bindings = container.attrs.get('NetworkSettings', {}).get('Ports', {})
        for container_port, host_bindings in (port_bindings or {}).items():
            if host_bindings:
                ports[container_port] = [f"{b['HostIp']}:{b['HostPort']}" for b in host_bindings]
        
        return ContainerInfo(
            id=container.id[:12],
            name=container.name,
            status=container.status,
            image=container.image.tags[0] if container.image.tags else container.image.id[:12],
            created=created,
            started=started,
            ports=ports,
            labels=container.labels
        )

    def get_container_logs(self, container_name: str, lines: int = 100, since: str = None) -> str:
        """Retrieve logs from a container."""
        try:
            container = self.client.containers.get(container_name)
            
            log_kwargs = {'tail': lines, 'timestamps': True}
            if since:
                log_kwargs['since'] = since
            
            logs = container.logs(**log_kwargs)
            return logs.decode('utf-8') if logs else ""
            
        except NotFound:
            logger.error(f"Container not found: {container_name}")
            raise ContainerNotFoundError(container_name)
        except DockerException as e:
            logger.error(f"Failed to retrieve logs for {container_name}: {e}")
            raise DockerConnectionError(
                f"Failed to retrieve logs from container '{container_name}'"
            ) from e
    
    def restart_container(self, container_name: str, timeout: int = 10) -> bool:
        """Restart a container."""
        try:
            container = self.client.containers.get(container_name)
            container.restart(timeout=timeout)
            
            container.reload()
            if container.status == 'running':
                logger.info(f"Successfully restarted container: {container_name}")
                return True
            
            logger.warning(f"Container {container_name} restarted but status is: {container.status}")
            return False
                
        except NotFound:
            logger.error(f"Container not found: {container_name}")
            raise ContainerNotFoundError(container_name)
        except DockerException as e:
            logger.error(f"Failed to restart container {container_name}: {e}")
            raise DockerConnectionError(
                f"Failed to restart container '{container_name}'"
            ) from e

    def check_container_health(self, container_name: str) -> HealthStatus:
        """Check comprehensive health status of a container including resource usage."""
        try:
            container = self.client.containers.get(container_name)
            container.reload()
            
            issues = []
            is_healthy = True
            
            status = container.status
            if status != 'running':
                is_healthy = False
                issues.append(f"Container is {status}, not running")
            
            health_check_status = None
            state = container.attrs.get('State', {})
            health = state.get('Health', {})
            if health:
                health_check_status = health.get('Status', 'none')
                if health_check_status == 'unhealthy':
                    is_healthy = False
                    issues.append("Docker health check reports unhealthy")
            
            restart_count = state.get('RestartCount', 0)
            if restart_count >= RESTART_COUNT_THRESHOLD:
                is_healthy = False
                issues.append(f"High restart count: {restart_count}")
            
            last_restart = None
            started_str = state.get('StartedAt', '')
            if started_str and started_str != '0001-01-01T00:00:00Z':
                last_restart = datetime.fromisoformat(started_str.replace('Z', '+00:00'))
            
            cpu_percent = None
            memory_percent = None
            try:
                stats = container.stats(stream=False)
                
                cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                           stats['precpu_stats']['cpu_usage']['total_usage']
                system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                              stats['precpu_stats']['system_cpu_usage']
                cpu_count = stats['cpu_stats'].get('online_cpus', 1)
                
                if system_delta > 0:
                    cpu_percent = (cpu_delta / system_delta) * cpu_count * 100.0
                    if cpu_percent > CPU_THRESHOLD_PERCENT:
                        is_healthy = False
                        issues.append(f"High CPU usage: {cpu_percent:.1f}%")
                
                memory_usage = stats['memory_stats'].get('usage', 0)
                memory_limit = stats['memory_stats'].get('limit', 1)
                memory_percent = (memory_usage / memory_limit) * 100.0
                if memory_percent > MEMORY_THRESHOLD_PERCENT:
                    is_healthy = False
                    issues.append(f"High memory usage: {memory_percent:.1f}%")
                    
            except (KeyError, ZeroDivisionError) as e:
                logger.debug(f"Could not calculate resource usage for {container_name}: {e}")
            
            return HealthStatus(
                container_name=container.name,
                is_healthy=is_healthy,
                status=status,
                health_check_status=health_check_status,
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                restart_count=restart_count,
                last_restart=last_restart,
                issues=issues
            )
            
        except NotFound:
            logger.error(f"Container not found: {container_name}")
            raise ContainerNotFoundError(container_name)
        except DockerException as e:
            logger.error(f"Failed to check health for {container_name}: {e}")
            raise DockerConnectionError(
                f"Failed to check health for container '{container_name}'"
            ) from e
