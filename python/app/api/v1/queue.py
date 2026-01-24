"""Queue Monitor API endpoints for tracking remediation task queue status."""

from typing import Optional, Dict, Any, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.logger import get_logger
from app.core.queue import get_queue_client, get_extended_queue_stats

logger = get_logger(__name__)

# Create router with /queue prefix
router = APIRouter(
    prefix="/queue",
    tags=["queue"],
    responses={
        500: {"description": "Internal server error"},
    },
)


# --- Pydantic Models ---

class LastProcessedTask(BaseModel):
    """Last processed task information."""
    task_id: str = Field(description="Task identifier")
    action_id: Optional[int] = Field(default=None, description="Associated action ID")
    target: str = Field(description="Target resource")
    timestamp: str = Field(description="Processing timestamp")


class HistorySample(BaseModel):
    """Queue depth history sample."""
    time: str = Field(description="Sample timestamp")
    depth: int = Field(description="Queue depth at sample time")


class QueueStatsUIResponse(BaseModel):
    """Response model for frontend Queue Monitor - simplified format."""
    queue_depth: int = Field(default=0, description="Current number of pending tasks")
    completed: int = Field(default=0, description="Total successful tasks")
    failed: int = Field(default=0, description="Total failed tasks")
    success_rate: float = Field(default=0.0, description="Success rate percentage")
    history: List[int] = Field(default_factory=list, description="Last 5 queue depth samples")

    class Config:
        json_schema_extra = {
            "example": {
                "queue_depth": 3,
                "completed": 25,
                "failed": 2,
                "success_rate": 92.6,
                "history": [0, 2, 4, 3, 5]
            }
        }


class QueueStatsResponse(BaseModel):
    """Response model for queue statistics (detailed)."""
    
    # Primary fields matching frontend QueueStats interface
    queue_depth: int = Field(default=0, description="Current number of pending tasks")
    completed: int = Field(default=0, description="Total successful tasks")
    failed: int = Field(default=0, description="Total failed tasks")
    success_rate: float = Field(default=0.0, description="Success rate percentage")
    history: List[HistorySample] = Field(default_factory=list, description="Queue depth history with timestamps")
    
    # Legacy/detailed fields
    queue_length: int = Field(default=0, description="Alias for queue_depth")
    tasks_enqueued: int = Field(default=0, description="Total tasks enqueued")
    tasks_dequeued: int = Field(default=0, description="Total tasks dequeued")
    tasks_failed: int = Field(default=0, description="Alias for failed")
    tasks_completed: int = Field(default=0, description="Alias for completed")
    last_processed_task: Optional[LastProcessedTask] = Field(default=None, description="Last processed task info")
    queue_name: str = Field(default="remediation_queue", description="Queue name")

    class Config:
        json_schema_extra = {
            "example": {
                "queue_depth": 3,
                "completed": 25,
                "failed": 2,
                "success_rate": 92.6,
                "history": [
                    {"time": "2026-01-24T12:00:00", "depth": 0},
                    {"time": "2026-01-24T12:00:05", "depth": 2},
                    {"time": "2026-01-24T12:00:10", "depth": 4}
                ],
                "queue_length": 3,
                "tasks_enqueued": 30,
                "tasks_dequeued": 27,
                "tasks_failed": 2,
                "tasks_completed": 25,
                "last_processed_task": {
                    "task_id": "task_1706097600000",
                    "action_id": 42,
                    "target": "web-server-01",
                    "timestamp": "2026-01-24T12:00:00"
                },
                "queue_name": "remediation_queue"
            }
        }


class QueueHealthResponse(BaseModel):
    """Response model for queue health check."""
    status: str = Field(description="Health status")
    service: str = Field(default="queue", description="Service name")
    redis_connected: bool = Field(description="Redis connection status")
    queue_depth: int = Field(description="Current queue depth")


# --- API Endpoints ---

@router.get(
    "/status",
    response_model=QueueStatsResponse,
    summary="Get queue status",
    description="Get current queue status and statistics"
)
async def get_queue_status() -> QueueStatsResponse:
    """
    Get the current queue status including:
    - Queue depth (pending tasks)
    - Completed and failed task counts
    - Success rate
    - Queue depth history for charting
    - Last processed task info
    
    Returns:
        QueueStatsResponse with all queue metrics
    """
    try:
        stats = get_extended_queue_stats()
        
        # Convert history to proper format
        history = []
        for sample in stats.get("history", []):
            if isinstance(sample, dict):
                history.append(HistorySample(
                    time=sample.get("time", ""),
                    depth=sample.get("depth", 0)
                ))
        
        # Convert last_processed_task to proper format
        last_task = None
        if stats.get("last_processed_task"):
            lpt = stats["last_processed_task"]
            last_task = LastProcessedTask(
                task_id=str(lpt.get("task_id", "")),
                action_id=lpt.get("action_id"),
                target=str(lpt.get("target", "")),
                timestamp=str(lpt.get("timestamp", ""))
            )
        
        return QueueStatsResponse(
            queue_depth=stats.get("queue_depth", 0),
            completed=stats.get("completed", 0),
            failed=stats.get("failed", 0),
            success_rate=stats.get("success_rate", 0.0),
            history=history,
            queue_length=stats.get("queue_length", 0),
            tasks_enqueued=stats.get("tasks_enqueued", 0),
            tasks_dequeued=stats.get("tasks_dequeued", 0),
            tasks_failed=stats.get("tasks_failed", 0),
            tasks_completed=stats.get("tasks_completed", 0),
            last_processed_task=last_task,
            queue_name=stats.get("queue_name", "remediation_queue"),
        )
        
    except Exception as e:
        logger.error(f"Failed to get queue status: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get queue status: {str(e)}"
        )


@router.get(
    "/health",
    response_model=QueueHealthResponse,
    summary="Queue health check",
    description="Check if the queue service is operational"
)
async def queue_health() -> QueueHealthResponse:
    """Health check for queue service."""
    try:
        client = get_queue_client()
        redis_ok = False
        queue_depth = 0
        
        try:
            client.redis_client.ping()
            redis_ok = True
            queue_depth = client.get_queue_length()
        except Exception:
            pass
        
        return QueueHealthResponse(
            status="healthy" if redis_ok else "degraded",
            service="queue",
            redis_connected=redis_ok,
            queue_depth=queue_depth,
        )
    except Exception as e:
        return QueueHealthResponse(
            status="unhealthy",
            service="queue",
            redis_connected=False,
            queue_depth=0,
        )


# --- UI Router for frontend compatibility ---
# The frontend calls /api/v1/ui/queue/stats

ui_router = APIRouter(
    prefix="/ui/queue",
    tags=["queue-ui"],
    responses={
        500: {"description": "Internal server error"},
    },
)


@ui_router.get(
    "/stats",
    response_model=QueueStatsUIResponse,
    summary="Get queue stats for UI",
    description="Get queue statistics formatted for the frontend Queue Monitor panel"
)
async def get_queue_stats_ui() -> QueueStatsUIResponse:
    """
    Get queue statistics for the frontend Queue Monitor.
    
    This is the endpoint called by the frontend at /api/v1/ui/queue/stats.
    Returns history as array of numbers (just depth values).
    """
    try:
        stats = get_extended_queue_stats()
        
        # Extract just the depth values from history for frontend
        history_depths = []
        for sample in stats.get("history", []):
            if isinstance(sample, dict):
                history_depths.append(sample.get("depth", 0))
            elif isinstance(sample, int):
                history_depths.append(sample)
        
        # Frontend expects only last 5 samples
        last_5_samples = history_depths[-5:] if len(history_depths) >= 5 else history_depths
        
        return QueueStatsUIResponse(
            queue_depth=stats.get("queue_depth", 0),
            completed=stats.get("completed", 0),
            failed=stats.get("failed", 0),
            success_rate=stats.get("success_rate", 0.0),
            history=last_5_samples,
        )
        
    except Exception as e:
        logger.error(f"Failed to get queue stats for UI: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get queue stats: {str(e)}"
        )


class InjectTasksRequest(BaseModel):
    """Request to inject test tasks into the queue."""
    count: int = Field(default=5, ge=1, le=50, description="Number of tasks to inject (1-50)")


class InjectTasksResponse(BaseModel):
    """Response from injecting test tasks."""
    ok: bool
    injected: int
    queue_depth: int
    message: str


@ui_router.post(
    "/inject-tasks",
    response_model=InjectTasksResponse,
    summary="Inject test tasks",
    description="Inject test tasks into the queue to simulate activity (for demo/testing)"
)
async def inject_test_tasks(request: InjectTasksRequest = None):
    """
    Inject test tasks into the queue to create visual spikes in the Queue Monitor.
    This is useful for demos and testing the queue visualization.
    """
    import time
    import random
    from app.core.queue import enqueue_task, get_queue_client
    
    count = request.count if request else 5
    client = get_queue_client()
    
    targets = ["web-server", "api-server", "db-server", "cache-server", "worker-node"]
    actions = ["restart", "scale-up", "health-check", "rotate-logs", "clear-cache"]
    severities = ["info", "warning", "critical"]
    
    injected = 0
    for i in range(count):
        task = {
            "task_id": f"demo_{int(time.time()*1000)}_{i}",
            "action_id": 1000 + i,
            "target": f"{random.choice(targets)}-{random.randint(1, 10):02d}",
            "action": random.choice(actions),
            "severity": random.choice(severities),
            "reason": "Demo task injected via Queue Monitor",
        }
        if enqueue_task(task):
            injected += 1
    
    return InjectTasksResponse(
        ok=True,
        injected=injected,
        queue_depth=client.get_queue_length(),
        message=f"Injected {injected} test tasks into queue"
    )


@router.post(
    "/record-history",
    summary="Force record a history sample",
    description="Manually trigger queue history recording (debug endpoint)"
)
async def force_record_history():
    """
    Force record a queue depth history sample.
    Used for debugging the background task.
    """
    from app.core.queue import record_queue_history
    record_queue_history()
    return {"status": "recorded", "message": "Queue history sample recorded"}


@router.get(
    "/debug/tasks",
    summary="Debug background tasks",
    description="Get status of background tasks (debug endpoint)"
)
async def get_background_tasks_status():
    """Get the status of background tasks."""
    from app.core.tasks import _background_tasks
    tasks = []
    for t in _background_tasks:
        tasks.append({
            "name": t.get_name(),
            "done": t.done(),
            "cancelled": t.cancelled(),
        })
    return {
        "count": len(_background_tasks),
        "tasks": tasks
    }
