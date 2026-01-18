"""
Queue management utilities for Vigil monitoring system.

Provides Redis-backed task queue for asynchronous remediation actions.
"""

import json
import time
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.logger import get_logger
from app.core.config import get_settings
from app.core.utils import retry

logger = get_logger(__name__)


class QueueClient:
    """Redis-backed queue client for task management."""
    
    def __init__(self):
        """Initialize queue client with Redis connection."""
        self.settings = get_settings()
        self.redis_client = None
        self.queue_name = "remediation_queue"
        self.stats_key = "remediation_queue:stats"
        self._connect()
    
    def _connect(self):
        """Establish Redis connection with error handling."""
        try:
            import redis
            self.redis_client = redis.from_url(
                self.settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            self.redis_client.ping()
            logger.info(
                "Queue client connected to Redis",
                extra={
                    "queue_name": self.queue_name,
                    "redis_url": self.settings.REDIS_URL.split('@')[-1] if '@' in self.settings.REDIS_URL else self.settings.REDIS_URL,
                }
            )
        except Exception as e:
            logger.error(
                "Failed to connect to Redis for queue",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
            raise
    
    @retry(
        max_attempts=3,
        backoff_strategy="exponential",
        base_delay=0.5,
        exceptions=(Exception,),
        log_retries=True
    )
    def enqueue_task(self, payload: Dict[str, Any]) -> bool:
        """
        Enqueue a remediation task into Redis queue.
        
        Args:
            payload: Task payload with action_id, target, severity, timestamp
        
        Returns:
            True if enqueued successfully
        
        Raises:
            Exception: On Redis errors after retries
        """
        try:
            # Add enqueue timestamp and ID if not present
            if "enqueued_at" not in payload:
                payload["enqueued_at"] = datetime.utcnow().isoformat()
            
            if "task_id" not in payload:
                payload["task_id"] = f"task_{int(time.time() * 1000)}"
            
            # Serialize to JSON
            task_json = json.dumps(payload)
            
            # Push to Redis list (queue)
            self.redis_client.rpush(self.queue_name, task_json)
            
            # Update stats
            self._increment_stat("tasks_enqueued")
            
            logger.info(
                "Task enqueued",
                extra={
                    "event": "task_enqueued",
                    "task_id": payload.get("task_id"),
                    "action_id": payload.get("action_id"),
                    "target": payload.get("target"),
                    "severity": payload.get("severity"),
                    "queue_name": self.queue_name,
                }
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to enqueue task",
                extra={
                    "event": "enqueue_failed",
                    "action_id": payload.get("action_id"),
                    "target": payload.get("target"),
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
            raise
    
    @retry(
        max_attempts=3,
        backoff_strategy="exponential",
        base_delay=0.5,
        exceptions=(Exception,),
        log_retries=True
    )
    def dequeue_task(self, timeout: int = 5) -> Optional[Dict[str, Any]]:
        """
        Dequeue a task from Redis queue (blocking with timeout).
        
        Args:
            timeout: Blocking timeout in seconds
        
        Returns:
            Task payload dict or None if timeout
        
        Raises:
            Exception: On Redis errors after retries
        """
        try:
            # BLPOP - blocking left pop with timeout
            result = self.redis_client.blpop(self.queue_name, timeout=timeout)
            
            if result is None:
                return None
            
            # result is tuple: (queue_name, task_json)
            _, task_json = result
            
            # Deserialize from JSON
            payload = json.loads(task_json)
            
            # Add dequeue timestamp
            payload["dequeued_at"] = datetime.utcnow().isoformat()
            
            # Update stats
            self._increment_stat("tasks_dequeued")
            self._set_last_processed(payload)
            
            logger.info(
                "Task dequeued",
                extra={
                    "event": "task_dequeued",
                    "task_id": payload.get("task_id"),
                    "action_id": payload.get("action_id"),
                    "target": payload.get("target"),
                    "severity": payload.get("severity"),
                    "queue_name": self.queue_name,
                }
            )
            
            return payload
            
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to decode task JSON",
                extra={
                    "event": "dequeue_decode_error",
                    "error": str(e),
                }
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to dequeue task",
                extra={
                    "event": "dequeue_failed",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
            raise
    
    def get_queue_length(self) -> int:
        """
        Get current queue length.
        
        Returns:
            Number of tasks in queue
        """
        try:
            return self.redis_client.llen(self.queue_name)
        except Exception as e:
            logger.error(
                "Failed to get queue length",
                extra={"error": str(e)}
            )
            return 0
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get queue statistics.
        
        Returns:
            Dictionary with queue stats
        """
        try:
            stats = {
                "queue_length": self.get_queue_length(),
                "tasks_enqueued": self._get_stat("tasks_enqueued"),
                "tasks_dequeued": self._get_stat("tasks_dequeued"),
                "tasks_failed": self._get_stat("tasks_failed"),
                "tasks_completed": self._get_stat("tasks_completed"),
                "last_processed_task": self._get_last_processed(),
                "queue_name": self.queue_name,
            }
            return stats
        except Exception as e:
            logger.error(
                "Failed to get queue stats",
                extra={"error": str(e)}
            )
            return {
                "queue_length": 0,
                "error": str(e),
            }
    
    def _increment_stat(self, stat_name: str):
        """Increment a stat counter."""
        try:
            self.redis_client.hincrby(self.stats_key, stat_name, 1)
        except Exception:
            pass  # Don't fail if stats update fails
    
    def _get_stat(self, stat_name: str) -> int:
        """Get a stat counter value."""
        try:
            value = self.redis_client.hget(self.stats_key, stat_name)
            return int(value) if value else 0
        except Exception:
            return 0
    
    def _set_last_processed(self, payload: Dict[str, Any]):
        """Store last processed task info."""
        try:
            last_processed = {
                "task_id": payload.get("task_id"),
                "action_id": payload.get("action_id"),
                "target": payload.get("target"),
                "timestamp": datetime.utcnow().isoformat(),
            }
            self.redis_client.hset(
                self.stats_key,
                "last_processed_task",
                json.dumps(last_processed)
            )
        except Exception:
            pass
    
    def _get_last_processed(self) -> Optional[Dict[str, Any]]:
        """Get last processed task info."""
        try:
            data = self.redis_client.hget(self.stats_key, "last_processed_task")
            return json.loads(data) if data else None
        except Exception:
            return None
    
    def increment_completed(self):
        """Increment completed tasks counter."""
        self._increment_stat("tasks_completed")
    
    def increment_failed(self):
        """Increment failed tasks counter."""
        self._increment_stat("tasks_failed")


# Singleton instance
_queue_client: Optional[QueueClient] = None


def get_queue_client() -> QueueClient:
    """
    Get or create singleton queue client instance.
    
    Returns:
        QueueClient instance
    """
    global _queue_client
    if _queue_client is None:
        _queue_client = QueueClient()
    return _queue_client


# Convenience functions
def enqueue_task(payload: Dict[str, Any]) -> bool:
    """
    Enqueue a remediation task.
    
    Args:
        payload: Task payload
    
    Returns:
        True if enqueued successfully
    """
    client = get_queue_client()
    return client.enqueue_task(payload)


def dequeue_task(timeout: int = 5) -> Optional[Dict[str, Any]]:
    """
    Dequeue a remediation task.
    
    Args:
        timeout: Blocking timeout in seconds
    
    Returns:
        Task payload or None
    """
    client = get_queue_client()
    return client.dequeue_task(timeout)


def get_queue_stats() -> Dict[str, Any]:
    """
    Get queue statistics.
    
    Returns:
        Queue stats dictionary
    """
    client = get_queue_client()
    return client.get_queue_stats()
