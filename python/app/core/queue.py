"""Redis-backed task queue for asynchronous remediation actions."""

import json
import time
from typing import Optional, Dict, Any
from datetime import datetime

from app.core.logger import get_logger
from app.core.config import get_settings
from app.core.utils import retry

logger = get_logger(__name__)


class QueueClient:
    """Redis-backed queue client for remediation task management."""
    
    def __init__(self):
        self.settings = get_settings()
        self.redis_client = None
        self.queue_name = "remediation_queue"
        self.stats_key = "remediation_queue:stats"
        self.history_key = "remediation_queue:history"
        self.history_max_samples = 60  # 5 minutes at 5-second intervals
        self._connect()
    
    def _connect(self):
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
        """Enqueue a remediation task. Returns True on success."""
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
            
            # Update Prometheus metrics
            try:
                from app.core.metrics import record_queue_operation, update_queue_length
                record_queue_operation("enqueue")
                update_queue_length(self.get_queue_length())
            except ImportError:
                pass  # Metrics module not available
            
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
        """Dequeue a task (blocking). Returns payload or None on timeout."""
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
            
            # Update Prometheus metrics
            try:
                from app.core.metrics import record_queue_operation, update_queue_length
                record_queue_operation("dequeue")
                update_queue_length(self.get_queue_length())
            except ImportError:
                pass  # Metrics module not available
            
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
        """Get current number of tasks in queue."""
        try:
            return self.redis_client.llen(self.queue_name)
        except Exception as e:
            logger.error(
                "Failed to get queue length",
                extra={"error": str(e)}
            )
            return 0
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics including counts and last processed task."""
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
        try:
            self.redis_client.hincrby(self.stats_key, stat_name, 1)
        except Exception:
            pass  # Don't fail if stats update fails
    
    def _get_stat(self, stat_name: str) -> int:
        try:
            value = self.redis_client.hget(self.stats_key, stat_name)
            return int(value) if value else 0
        except Exception:
            return 0
    
    def _set_last_processed(self, payload: Dict[str, Any]):
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
        try:
            data = self.redis_client.hget(self.stats_key, "last_processed_task")
            return json.loads(data) if data else None
        except Exception:
            return None
    
    def increment_completed(self):
        self._increment_stat("tasks_completed")
    
    def increment_failed(self):
        self._increment_stat("tasks_failed")
    
    def record_history_sample(self):
        """Record current queue depth to history for charting."""
        try:
            sample = {
                "time": datetime.utcnow().isoformat(),
                "depth": self.get_queue_length()
            }
            # Push to list and trim to max samples
            self.redis_client.lpush(self.history_key, json.dumps(sample))
            self.redis_client.ltrim(self.history_key, 0, self.history_max_samples - 1)
        except Exception as e:
            logger.debug(f"Failed to record history sample: {e}")
    
    def get_history(self) -> list:
        """Get queue depth history samples."""
        try:
            raw = self.redis_client.lrange(self.history_key, 0, self.history_max_samples - 1)
            # Parse and reverse to oldest-first order
            history = [json.loads(s) for s in raw]
            history.reverse()
            return history
        except Exception as e:
            logger.debug(f"Failed to get history: {e}")
            return []
    
    def get_extended_stats(self) -> Dict[str, Any]:
        """Get extended queue statistics including success rate and history."""
        try:
            completed = self._get_stat("tasks_completed")
            failed = self._get_stat("tasks_failed")
            dequeued = self._get_stat("tasks_dequeued")
            total_processed = completed + failed
            success_rate = (completed / total_processed * 100) if total_processed > 0 else 0.0
            
            stats = {
                # New fields matching frontend QueueStats interface
                "queue_depth": self.get_queue_length(),
                "completed": completed,
                "failed": failed,
                "success_rate": round(success_rate, 1),
                "history": self.get_history(),
                # Legacy fields for backward compatibility
                "queue_length": self.get_queue_length(),
                "tasks_enqueued": self._get_stat("tasks_enqueued"),
                "tasks_dequeued": dequeued,
                "tasks_failed": failed,
                "tasks_completed": completed,
                "last_processed_task": self._get_last_processed(),
                "queue_name": self.queue_name,
            }
            return stats
        except Exception as e:
            logger.error(f"Failed to get extended queue stats: {e}")
            return {
                "queue_depth": 0,
                "completed": 0,
                "failed": 0,
                "success_rate": 0.0,
                "history": [],
                "queue_length": 0,
                "tasks_enqueued": 0,
                "tasks_dequeued": 0,
                "tasks_failed": 0,
                "tasks_completed": 0,
                "last_processed_task": None,
                "queue_name": self.queue_name,
                "error": str(e),
            }


# Singleton instance
_queue_client: Optional[QueueClient] = None


def get_queue_client() -> QueueClient:
    """Get singleton queue client instance."""
    global _queue_client
    if _queue_client is None:
        _queue_client = QueueClient()
    return _queue_client


# Convenience functions
def enqueue_task(payload: Dict[str, Any]) -> bool:
    """Convenience function to enqueue a remediation task."""
    client = get_queue_client()
    return client.enqueue_task(payload)


def dequeue_task(timeout: int = 5) -> Optional[Dict[str, Any]]:
    """Convenience function to dequeue a remediation task."""
    client = get_queue_client()
    return client.dequeue_task(timeout)


def get_queue_stats() -> Dict[str, Any]:
    """Convenience function to get queue statistics."""
    client = get_queue_client()
    return client.get_queue_stats()


def get_extended_queue_stats() -> Dict[str, Any]:
    """Convenience function to get extended queue statistics with history."""
    client = get_queue_client()
    return client.get_extended_stats()


def record_queue_history() -> None:
    """Convenience function to record a queue depth history sample."""
    client = get_queue_client()
    client.record_history_sample()
