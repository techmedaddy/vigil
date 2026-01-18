"""
Worker service for processing remediation tasks from Redis queue.

Continuously polls for tasks and dispatches them to the remediator service.
"""

import asyncio
import httpx
import time
from typing import Optional
from datetime import datetime

from app.core.logger import get_logger
from app.core.config import get_settings
from app.core.queue import get_queue_client
from app.core.db import get_db_async
from sqlalchemy import text

logger = get_logger(__name__)


class RemediationWorker:
    """Async worker that processes remediation tasks from queue."""
    
    def __init__(self):
        """Initialize worker with configuration."""
        self.settings = get_settings()
        self.queue_client = get_queue_client()
        self.running = False
        self.tasks_processed = 0
        self.tasks_failed = 0
        self.started_at: Optional[datetime] = None
        self.last_task_at: Optional[datetime] = None
    
    async def start(self):
        """Start the worker loop."""
        self.running = True
        self.started_at = datetime.utcnow()
        
        logger.info(
            "Remediation worker starting",
            extra={
                "event": "worker_started",
                "worker_id": id(self),
                "remediator_url": self.settings.REMEDIATOR_URL,
            }
        )
        
        try:
            await self._worker_loop()
        except KeyboardInterrupt:
            logger.info("Worker interrupted by user")
        except Exception as e:
            logger.error(
                "Worker crashed",
                extra={
                    "event": "worker_crashed",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
            raise
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the worker gracefully."""
        self.running = False
        
        logger.info(
            "Remediation worker stopping",
            extra={
                "event": "worker_stopped",
                "tasks_processed": self.tasks_processed,
                "tasks_failed": self.tasks_failed,
                "uptime_seconds": (datetime.utcnow() - self.started_at).total_seconds() if self.started_at else 0,
            }
        )
    
    async def _worker_loop(self):
        """Main worker loop - dequeue and process tasks."""
        logger.info("Worker loop started, waiting for tasks...")
        
        while self.running:
            try:
                # Dequeue task (blocking with timeout)
                # Run in executor since dequeue_task is synchronous/blocking
                task = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.queue_client.dequeue_task,
                    5  # 5 second timeout
                )
                
                if task is None:
                    # No task available, continue waiting
                    continue
                
                # Process the task
                await self._process_task(task)
                
            except asyncio.CancelledError:
                logger.info("Worker loop cancelled")
                break
            except Exception as e:
                logger.error(
                    "Error in worker loop",
                    extra={
                        "event": "worker_loop_error",
                        "error": str(e),
                        "error_type": type(e).__name__,
                    }
                )
                # Continue running even on errors
                await asyncio.sleep(1)
    
    async def _process_task(self, task: dict):
        """
        Process a single remediation task.
        
        Args:
            task: Task payload with action_id, target, severity, timestamp
        """
        task_id = task.get("task_id", "unknown")
        action_id = task.get("action_id")
        request_id = task.get("request_id", task_id)
        
        logger.info(
            "Processing remediation task",
            extra={
                "event": "task_processing",
                "task_id": task_id,
                "action_id": action_id,
                "target": task.get("target"),
                "severity": task.get("severity"),
                "request_id": request_id,
            }
        )
        
        self.last_task_at = datetime.utcnow()
        
        try:
            # Dispatch to remediator service
            success = await self._dispatch_to_remediator(task)
            
            if success:
                self.tasks_processed += 1
                self.queue_client.increment_completed()
                
                # Update action status in database
                await self._update_action_status(action_id, "completed", request_id)
                
                logger.info(
                    "Task processed successfully",
                    extra={
                        "event": "task_completed",
                        "task_id": task_id,
                        "action_id": action_id,
                        "request_id": request_id,
                    }
                )
            else:
                self.tasks_failed += 1
                self.queue_client.increment_failed()
                
                # Update action status to failed
                await self._update_action_status(action_id, "failed", request_id)
                
                logger.error(
                    "Task processing failed",
                    extra={
                        "event": "task_failed",
                        "task_id": task_id,
                        "action_id": action_id,
                        "request_id": request_id,
                    }
                )
        
        except Exception as e:
            self.tasks_failed += 1
            self.queue_client.increment_failed()
            
            logger.error(
                "Exception processing task",
                extra={
                    "event": "task_exception",
                    "task_id": task_id,
                    "action_id": action_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                }
            )
            
            # Try to update action status
            try:
                await self._update_action_status(action_id, "failed", request_id)
            except Exception:
                pass
    
    async def _dispatch_to_remediator(self, task: dict) -> bool:
        """
        Dispatch task to remediator service via HTTP POST.
        
        Args:
            task: Task payload
        
        Returns:
            True if successful, False otherwise
        """
        remediator_url = self.settings.REMEDIATOR_URL
        request_id = task.get("request_id", task.get("task_id", "unknown"))
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Prepare payload for remediator
                payload = {
                    "action": task.get("action"),
                    "target": task.get("target"),
                    "severity": task.get("severity"),
                    "policy_id": task.get("policy_id"),
                    "alert_id": task.get("alert_id"),
                    "action_id": task.get("action_id"),
                    "request_id": request_id,
                }
                
                logger.debug(
                    "Sending task to remediator",
                    extra={
                        "remediator_url": remediator_url,
                        "action_id": task.get("action_id"),
                        "request_id": request_id,
                    }
                )
                
                response = await client.post(
                    f"{remediator_url}/remediate",
                    json=payload,
                    headers={"X-Request-ID": request_id}
                )
                
                if response.status_code == 200:
                    logger.info(
                        "Remediator accepted task",
                        extra={
                            "event": "remediator_success",
                            "action_id": task.get("action_id"),
                            "status_code": response.status_code,
                            "request_id": request_id,
                        }
                    )
                    return True
                else:
                    logger.error(
                        "Remediator rejected task",
                        extra={
                            "event": "remediator_rejected",
                            "action_id": task.get("action_id"),
                            "status_code": response.status_code,
                            "response": response.text[:200],
                            "request_id": request_id,
                        }
                    )
                    return False
        
        except httpx.RequestError as e:
            logger.error(
                "Failed to reach remediator",
                extra={
                    "event": "remediator_unreachable",
                    "action_id": task.get("action_id"),
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                }
            )
            return False
        
        except Exception as e:
            logger.error(
                "Unexpected error dispatching to remediator",
                extra={
                    "event": "dispatch_error",
                    "action_id": task.get("action_id"),
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                }
            )
            return False
    
    async def _update_action_status(self, action_id: Optional[str], status: str, request_id: str):
        """
        Update action status in database.
        
        Args:
            action_id: Action ID to update
            status: New status (completed, failed, processing)
            request_id: Request ID for logging
        """
        if not action_id:
            return
        
        try:
            async for db in get_db_async():
                await db.execute(
                    text("""
                        UPDATE actions 
                        SET status = :status, 
                            updated_at = CURRENT_TIMESTAMP 
                        WHERE action_id = :action_id
                    """),
                    {"action_id": action_id, "status": status}
                )
                await db.commit()
                
                logger.debug(
                    "Updated action status",
                    extra={
                        "action_id": action_id,
                        "status": status,
                        "request_id": request_id,
                    }
                )
        except Exception as e:
            logger.error(
                "Failed to update action status",
                extra={
                    "action_id": action_id,
                    "status": status,
                    "error": str(e),
                    "request_id": request_id,
                }
            )
    
    def get_status(self) -> dict:
        """
        Get worker status.
        
        Returns:
            Dictionary with worker status information
        """
        uptime = (datetime.utcnow() - self.started_at).total_seconds() if self.started_at else 0
        
        return {
            "running": self.running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "uptime_seconds": uptime,
            "tasks_processed": self.tasks_processed,
            "tasks_failed": self.tasks_failed,
            "last_task_at": self.last_task_at.isoformat() if self.last_task_at else None,
            "success_rate": (
                self.tasks_processed / (self.tasks_processed + self.tasks_failed) * 100
                if (self.tasks_processed + self.tasks_failed) > 0
                else 0.0
            ),
        }


# Singleton worker instance
_worker_instance: Optional[RemediationWorker] = None


def get_worker() -> RemediationWorker:
    """
    Get or create singleton worker instance.
    
    Returns:
        RemediationWorker instance
    """
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = RemediationWorker()
    return _worker_instance


async def start_worker():
    """Start the remediation worker."""
    worker = get_worker()
    await worker.start()


if __name__ == "__main__":
    """Run worker as standalone service."""
    asyncio.run(start_worker())
