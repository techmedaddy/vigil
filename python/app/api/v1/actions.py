"""Actions endpoint for remediation action management and tracking."""

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_db, Action
from app.core.logger import get_logger
from app.core.config import get_settings
from app.core.utils import retry

# Import action service
try:
    from app.services.action_service import ActionService, ActionStatus as ServiceActionStatus
    action_service_available = True
except ImportError:
    action_service_available = False

# Import metrics module if available
try:
    from app.core import metrics
    metrics_available = True
except ImportError:
    metrics_available = False

logger = get_logger(__name__)

# Create router with /actions prefix
router = APIRouter(
    prefix="/actions",
    tags=["actions"],
    responses={
        400: {"description": "Invalid request"},
        500: {"description": "Internal server error"},
    },
)


# --- Enums ---

class ActionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# --- Pydantic Models ---

class CreateActionRequest(BaseModel):
    """Request model for creating an action."""

    target: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Target resource identifier"
    )
    action_type: str = Field(
        ...,
        min_length=1,
        max_length=255,
        alias="action",
        description="Action type to perform (e.g., restart, scale, apply_manifest)"
    )
    status: str = Field(
        default=ActionStatus.PENDING,
        description="Action status"
    )
    details: Optional[str] = Field(
        default=None,
        description="Additional details about the action"
    )
    queue_immediately: bool = Field(
        default=False,
        description="If true, queue the action for immediate execution"
    )
    priority: Optional[str] = Field(
        default="medium",
        description="Action priority: low, medium, high"
    )

    @validator("target")
    def validate_target(cls, v):
        if not v or not v.strip():
            raise ValueError("Target cannot be empty")
        return v.strip()

    @validator("action_type", pre=True)
    def validate_action_type(cls, v):
        if not v or not v.strip():
            raise ValueError("Action type cannot be empty")
        return v.strip()

    @validator("status")
    def validate_status(cls, v):
        valid_statuses = [s.value for s in ActionStatus]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return v

    @validator("priority")
    def validate_priority(cls, v):
        valid_priorities = ["low", "medium", "high"]
        if v and v not in valid_priorities:
            raise ValueError(f"Priority must be one of {valid_priorities}")
        return v or "medium"

    class Config:
        populate_by_name = True  # Allow both 'action' and 'action_type'
        schema_extra = {
            "example": {
                "target": "web-service",
                "action_type": "restart",
                "status": "pending",
                "details": "Triggered by high CPU policy",
                "queue_immediately": True,
                "priority": "high"
            }
        }


class ActionResponse(BaseModel):
    """Response model for action creation."""

    ok: bool = Field(
        default=True,
        description="Success flag"
    )
    action_id: int = Field(
        ...,
        description="ID of the created action"
    )
    message: str = Field(
        default="Action created successfully",
        description="Response message"
    )
    target: Optional[str] = Field(
        default=None,
        description="Target resource"
    )
    action_type: Optional[str] = Field(
        default=None,
        description="Type of action"
    )
    status: Optional[str] = Field(
        default=None,
        description="Current status of the action"
    )
    queued: bool = Field(
        default=False,
        description="Whether the action was queued for execution"
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the action was created"
    )

    class Config:
        """Pydantic model configuration."""
        schema_extra = {
            "example": {
                "ok": True,
                "action_id": 1,
                "message": "Action created successfully",
                "target": "web-service",
                "action_type": "restart",
                "status": "pending",
                "queued": True,
                "created_at": "2026-01-24T15:52:00Z"
            }
        }


class ActionDetailResponse(BaseModel):
    """Response model for action details."""

    id: int
    target: str
    action: str
    status: str
    details: Optional[str] = None
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        """Pydantic model configuration."""
        from_attributes = True
        schema_extra = {
            "example": {
                "id": 1,
                "target": "web-service",
                "action": "restart",
                "status": "completed",
                "details": "Service restarted successfully",
                "error_message": None,
                "started_at": "2026-01-13T12:34:56Z",
                "completed_at": "2026-01-13T12:35:10Z"
            }
        }


class ListActionsResponse(BaseModel):
    """Response model for listing actions."""

    count: int = Field(..., description="Number of actions returned")
    total: int = Field(..., description="Total number of matching actions")
    page: int = Field(default=1, description="Current page number")
    page_size: int = Field(default=50, description="Number of items per page")
    actions: List[ActionDetailResponse] = Field(..., description="List of actions")


# --- Helper functions with retry logic ---

@retry(
    max_attempts=None,  # Use config default
    backoff_strategy="exponential",
    exceptions=(SQLAlchemyError,),
    log_retries=True
)
async def store_action_in_db(
    db: AsyncSession,
    action: Action
) -> int:
    """
    Store action in database with retry logic for transient errors.

    Args:
        db: Database session
        action: Action instance to store

    Returns:
        ID of stored action

    Raises:
        SQLAlchemyError: On database errors after retries exhausted
    """
    db.add(action)
    await db.flush()
    return action.id


@retry(
    max_attempts=None,  # Use config default
    backoff_strategy="exponential",
    exceptions=(SQLAlchemyError,),
    log_retries=True
)
async def query_actions_from_db(
    db: AsyncSession,
    query
) -> List[Action]:
    """
    Query actions from database with retry logic for transient errors.

    Args:
        db: Database session
        query: SQLAlchemy query to execute

    Returns:
        List of actions

    Raises:
        SQLAlchemyError: On database errors after retries exhausted
    """
    result = await db.execute(query)
    return result.scalars().all()


@retry(
    max_attempts=None,  # Use config default
    backoff_strategy="exponential",
    exceptions=(SQLAlchemyError,),
    log_retries=True
)
async def query_action_by_id_from_db(
    db: AsyncSession,
    action_id: int
) -> Optional[Action]:
    """
    Query action by ID from database with retry logic for transient errors.

    Args:
        db: Database session
        action_id: ID of action to retrieve

    Returns:
        Action instance or None

    Raises:
        SQLAlchemyError: On database errors after retries exhausted
    """
    query = select(Action).where(Action.id == action_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


# --- Routes ---

@router.get(
    "/health",
    summary="Health check",
    description="Check if the actions service is operational"
)
async def health_check() -> Dict[str, str]:
    """Health check endpoint for actions service."""
    return {"status": "healthy", "service": "actions"}

@router.post(
    "",
    response_model=ActionResponse,
    status_code=201,
    summary="Create an action",
    description="Create a new remediation action record"
)
async def create_action(
    payload: CreateActionRequest,
    db: AsyncSession = Depends(get_db),
) -> ActionResponse:
    """
    Create a new action record.

    This endpoint:
    1. Validates the action payload (target, action_type)
    2. Stores the action in the database with status=pending
    3. Optionally queues the action for immediate execution
    4. Returns the action ID and metadata

    Args:
        payload: Action data (target, action_type, status, details, queue_immediately, priority)
        db: AsyncSession for database operations

    Returns:
        ActionResponse with action ID, metadata, and queue status

    Raises:
        HTTPException: On validation or database errors
    """
    try:
        created_at = datetime.utcnow()
        
        logger.info(
            "Action creation started",
            extra={
                "target": payload.target,
                "action_type": payload.action_type,
                "status": payload.status,
                "queue_immediately": payload.queue_immediately,
                "priority": payload.priority
            }
        )

        # Create action instance with pending status
        action = Action(
            target=payload.target,
            action=payload.action_type,
            status=ActionStatus.PENDING.value,  # Always start as pending
            details=payload.details,
            started_at=created_at
        )

        # Store action with retry logic for transient DB errors
        try:
            action_id = await store_action_in_db(db, action)
        except SQLAlchemyError as e:
            logger.error(
                f"Failed to store action after retries: {e}",
                extra={
                    "target": payload.target,
                    "action_type": payload.action_type
                },
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to create action in database after retries"
            )

        # Queue action for execution if requested
        queued = False
        if payload.queue_immediately:
            try:
                from app.core.queue import enqueue_task
                task_payload = {
                    "action_id": action.id,
                    "target": payload.target,
                    "action_type": payload.action_type,
                    "priority": payload.priority,
                    "details": payload.details,
                    "severity": payload.priority,  # Map priority to severity for queue
                }
                queued = enqueue_task(task_payload)
                
                if queued:
                    logger.info(
                        "Action queued for execution",
                        extra={
                            "action_id": action.id,
                            "target": payload.target,
                            "priority": payload.priority
                        }
                    )
            except ImportError:
                logger.warning(
                    "Queue module not available, action not queued",
                    extra={"action_id": action.id}
                )
            except Exception as e:
                logger.warning(
                    f"Failed to queue action: {e}",
                    extra={
                        "action_id": action.id,
                        "error": str(e)
                    }
                )

        # Record action in Prometheus metrics
        if metrics_available:
            try:
                metrics.record_action(
                    target=payload.target,
                    action=payload.action_type,
                    status=ActionStatus.PENDING.value
                )
            except Exception as e:
                logger.warning(
                    "Failed to record action metric",
                    extra={
                        "target": payload.target,
                        "action_type": payload.action_type,
                        "error": str(e)
                    }
                )

        logger.info(
            "Action created successfully",
            extra={
                "action_id": action.id,
                "target": payload.target,
                "action_type": payload.action_type,
                "status": ActionStatus.PENDING.value,
                "queued": queued
            }
        )

        return ActionResponse(
            ok=True,
            action_id=action.id,
            message="Action created successfully" + (" and queued for execution" if queued else ""),
            target=payload.target,
            action_type=payload.action_type,
            status=ActionStatus.PENDING.value,
            queued=queued,
            created_at=created_at
        )

    except ValueError as e:
        logger.warning(
            f"Validation error: {e}",
            extra={"error": str(e)}
        )
        raise HTTPException(
            status_code=400,
            detail=f"Validation error: {str(e)}"
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"Failed to create action: {e}",
            extra={
                "target": payload.target,
                "action_type": payload.action_type
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to create action in database"
        )


@router.get(
    "",
    response_model=ListActionsResponse,
    summary="List actions",
    description="Retrieve recent actions with filtering and pagination"
)
async def list_actions(
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of actions to return"),
    page: int = Query(default=1, ge=1, description="Page number for pagination"),
    status: Optional[str] = Query(default=None, description="Filter by action status"),
    target: Optional[str] = Query(default=None, description="Filter by target resource"),
    start_time: Optional[datetime] = Query(default=None, description="Filter actions started after this time (ISO format)"),
    end_time: Optional[datetime] = Query(default=None, description="Filter actions started before this time (ISO format)"),
    db: AsyncSession = Depends(get_db),
) -> ListActionsResponse:
    """
    Retrieve a list of recent actions with filtering and pagination.

    Args:
        limit: Maximum number of actions to return (default: 50, max: 500)
        page: Page number for pagination (default: 1)
        status: Optional filter by action status
        target: Optional filter by target resource
        start_time: Optional filter for actions started after this time
        end_time: Optional filter for actions started before this time
        db: AsyncSession for database operations

    Returns:
        ListActionsResponse with count, total, pagination info, and action list

    Raises:
        HTTPException: On database errors
    """
    try:
        # Validate status if provided
        if status:
            valid_statuses = [s.value for s in ActionStatus]
            if status not in valid_statuses:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status. Must be one of {valid_statuses}"
                )

        # Calculate offset
        offset = (page - 1) * limit

        logger.debug(
            "Listing actions",
            extra={
                "limit": limit,
                "page": page,
                "offset": offset,
                "status_filter": status,
                "target_filter": target,
                "start_time": start_time.isoformat() if start_time else None,
                "end_time": end_time.isoformat() if end_time else None
            }
        )

        # Build filter conditions
        conditions = []
        if status:
            conditions.append(Action.status == status)
        if target:
            conditions.append(Action.target == target)
        if start_time:
            conditions.append(Action.started_at >= start_time)
        if end_time:
            conditions.append(Action.started_at <= end_time)

        # Get total count
        count_query = select(func.count(Action.id))
        if conditions:
            count_query = count_query.where(and_(*conditions))
        
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        # Build main query with pagination
        query = select(Action).order_by(Action.started_at.desc())
        if conditions:
            query = query.where(and_(*conditions))
        query = query.limit(limit).offset(offset)

        # Execute query with retry logic
        try:
            actions = await query_actions_from_db(db, query)
        except SQLAlchemyError as e:
            logger.error(
                f"Failed to query actions after retries: {e}",
                extra={
                    "status_filter": status,
                    "target_filter": target
                },
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve actions from database after retries"
            )

        logger.info(
            f"Retrieved {len(actions)} actions (total: {total})",
            extra={
                "count": len(actions),
                "total": total,
                "page": page,
                "limit": limit,
                "status_filter": status,
                "target_filter": target
            }
        )

        return ListActionsResponse(
            count=len(actions),
            total=total,
            page=page,
            page_size=limit,
            actions=[
                ActionDetailResponse(
                    id=a.id,
                    target=a.target,
                    action=a.action,
                    status=a.status,
                    details=a.details,
                    error_message=getattr(a, 'error_message', None),
                    started_at=a.started_at,
                    completed_at=getattr(a, 'completed_at', None)
                )
                for a in actions
            ]
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"Failed to retrieve actions: {e}",
            extra={
                "status_filter": status,
                "target_filter": target
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve actions from database"
        )


@router.get(
    "/{action_id}",
    response_model=ActionDetailResponse,
    summary="Get action details",
    description="Retrieve details of a specific action"
)
async def get_action_detail(
    action_id: int,
    db: AsyncSession = Depends(get_db),
) -> ActionDetailResponse:
    """
    Get details of a specific action by ID.

    Args:
        action_id: ID of the action to retrieve
        db: AsyncSession for database operations

    Returns:
        ActionDetailResponse with action details

    Raises:
        HTTPException: If action not found or database error
    """
    try:
        logger.debug(
            "Retrieving action details",
            extra={"action_id": action_id}
        )

        # Query action with retry logic
        try:
            action = await query_action_by_id_from_db(db, action_id)
        except SQLAlchemyError as e:
            logger.error(
                f"Failed to query action after retries: {e}",
                extra={"action_id": action_id},
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve action from database after retries"
            )

        if action is None:
            logger.warning(
                f"Action not found",
                extra={"action_id": action_id}
            )
            raise HTTPException(
                status_code=404,
                detail=f"Action with id {action_id} not found"
            )

        logger.debug(
            "Action details retrieved",
            extra={
                "action_id": action_id,
                "target": action.target
            }
        )

        return ActionDetailResponse(
            id=action.id,
            target=action.target,
            action=action.action,
            status=action.status,
            details=action.details,
            error_message=getattr(action, 'error_message', None),
            started_at=action.started_at,
            completed_at=getattr(action, 'completed_at', None)
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"Failed to retrieve action: {e}",
            extra={"action_id": action_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve action from database"
        )


@router.get(
    "/status/{action_status}",
    response_model=ListActionsResponse,
    summary="Filter actions by status",
    description="Retrieve actions with a specific status"
)
async def get_actions_by_status(
    action_status: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> ListActionsResponse:
    """
    Get all actions with a specific status.

    Args:
        action_status: Status to filter by (pending, running, completed, failed, cancelled)
        limit: Maximum number of actions to return
        db: AsyncSession for database operations

    Returns:
        ListActionsResponse with filtered actions

    Raises:
        HTTPException: On invalid status or database errors
    """
    try:
        # Validate status
        valid_statuses = [s.value for s in ActionStatus]
        if action_status not in valid_statuses:
            raise ValueError(f"Invalid status. Must be one of {valid_statuses}")

        # Validate limit
        limit = min(limit, 500)
        if limit < 1:
            limit = 1

        logger.debug(
            "Filtering actions by status",
            extra={
                "status": action_status,
                "limit": limit
            }
        )

        query = (
            select(Action)
            .where(Action.status == action_status)
            .order_by(Action.started_at.desc())
            .limit(limit)
        )

        # Execute query with retry logic
        try:
            actions = await query_actions_from_db(db, query)
        except SQLAlchemyError as e:
            logger.error(
                f"Failed to query actions by status after retries: {e}",
                extra={"status": action_status},
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve actions from database after retries"
            )

        logger.info(
            f"Retrieved {len(actions)} {action_status} actions",
            extra={
                "count": len(actions),
                "status": action_status
            }
        )

        return ListActionsResponse(
            count=len(actions),
            total=len(actions),
            page=1,
            page_size=limit,
            actions=[
                ActionDetailResponse(
                    id=a.id,
                    target=a.target,
                    action=a.action,
                    status=a.status,
                    details=a.details,
                    error_message=getattr(a, 'error_message', None),
                    started_at=a.started_at,
                    completed_at=getattr(a, 'completed_at', None)
                )
                for a in actions
            ]
        )

    except ValueError as e:
        logger.warning(
            f"Invalid status: {e}",
            extra={"status": action_status}
        )
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

    except Exception as e:
        logger.error(
            f"Failed to filter actions by status: {e}",
            extra={"status": action_status},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve actions from database"
        )


# --- Cancel Action Endpoint ---

class CancelActionRequest(BaseModel):
    """Request model for cancelling an action."""
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional reason for cancellation"
    )


class CancelActionResponse(BaseModel):
    """Response model for action cancellation."""
    ok: bool = Field(default=True, description="Success flag")
    action_id: int = Field(..., description="ID of the cancelled action")
    message: str = Field(default="Action cancelled successfully", description="Response message")
    previous_status: str = Field(..., description="Status before cancellation")


@router.put(
    "/{action_id}/cancel",
    response_model=CancelActionResponse,
    summary="Cancel an action",
    description="Cancel a pending or running action"
)
async def cancel_action(
    action_id: int,
    request: Optional[CancelActionRequest] = None,
    db: AsyncSession = Depends(get_db),
) -> CancelActionResponse:
    """
    Cancel a pending or running action.

    Only actions with status 'pending' or 'running' can be cancelled.
    Actions that are already completed, failed, or cancelled cannot be cancelled.

    Args:
        action_id: ID of the action to cancel
        request: Optional cancellation request with reason
        db: AsyncSession for database operations

    Returns:
        CancelActionResponse with cancellation result

    Raises:
        HTTPException: If action not found, already completed, or database error
    """
    try:
        logger.info(
            "Cancel action requested",
            extra={
                "action_id": action_id,
                "reason": request.reason if request else None
            }
        )

        # Get the action
        try:
            action = await query_action_by_id_from_db(db, action_id)
        except SQLAlchemyError as e:
            logger.error(
                f"Failed to query action for cancellation: {e}",
                extra={"action_id": action_id},
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve action from database"
            )

        if action is None:
            logger.warning(
                f"Action not found for cancellation",
                extra={"action_id": action_id}
            )
            raise HTTPException(
                status_code=404,
                detail=f"Action with id {action_id} not found"
            )

        # Check if action can be cancelled
        cancellable_statuses = [ActionStatus.PENDING.value, ActionStatus.RUNNING.value]
        if action.status not in cancellable_statuses:
            logger.warning(
                f"Action cannot be cancelled",
                extra={
                    "action_id": action_id,
                    "current_status": action.status
                }
            )
            raise HTTPException(
                status_code=400,
                detail=f"Action with status '{action.status}' cannot be cancelled. "
                       f"Only actions with status {cancellable_statuses} can be cancelled."
            )

        # Store previous status
        previous_status = action.status

        # Update action to cancelled
        action.status = ActionStatus.CANCELLED.value
        action.completed_at = datetime.utcnow()
        if request and request.reason:
            action.details = f"Cancelled: {request.reason}"

        await db.flush()

        # Record metrics
        if metrics_available:
            try:
                metrics.record_action(
                    target=action.target,
                    action=action.action,
                    status=ActionStatus.CANCELLED.value
                )
            except Exception as e:
                logger.warning(f"Failed to record cancellation metric: {e}")

        logger.info(
            "Action cancelled",
            extra={
                "action_id": action_id,
                "target": action.target,
                "previous_status": previous_status,
                "reason": request.reason if request else None
            }
        )

        return CancelActionResponse(
            ok=True,
            action_id=action_id,
            message="Action cancelled successfully",
            previous_status=previous_status
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"Failed to cancel action: {e}",
            extra={"action_id": action_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to cancel action"
        )


# --- Update Action Status Endpoint ---

class UpdateActionStatusRequest(BaseModel):
    """Request model for updating action status."""
    status: str = Field(
        ...,
        description="New status (pending, running, completed, failed, cancelled)"
    )
    details: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Optional details update"
    )
    error_message: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Error message (for failed status)"
    )

    @validator("status")
    def validate_status(cls, v):
        valid_statuses = [s.value for s in ActionStatus]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return v


class UpdateActionStatusResponse(BaseModel):
    """Response model for action status update."""
    ok: bool = Field(default=True, description="Success flag")
    action_id: int = Field(..., description="ID of the updated action")
    message: str = Field(default="Action status updated", description="Response message")
    previous_status: str = Field(..., description="Status before update")
    new_status: str = Field(..., description="New status after update")


@router.put(
    "/{action_id}/status",
    response_model=UpdateActionStatusResponse,
    summary="Update action status",
    description="Update the status of an action"
)
async def update_action_status(
    action_id: int,
    request: UpdateActionStatusRequest,
    db: AsyncSession = Depends(get_db),
) -> UpdateActionStatusResponse:
    """
    Update the status of an action.

    This endpoint allows updating an action's status, details, and error message.
    Used by the remediator and agent to report action progress.

    Args:
        action_id: ID of the action to update
        request: Status update request
        db: AsyncSession for database operations

    Returns:
        UpdateActionStatusResponse with update result

    Raises:
        HTTPException: If action not found or database error
    """
    try:
        logger.info(
            "Update action status requested",
            extra={
                "action_id": action_id,
                "new_status": request.status
            }
        )

        # Get the action
        try:
            action = await query_action_by_id_from_db(db, action_id)
        except SQLAlchemyError as e:
            logger.error(
                f"Failed to query action for status update: {e}",
                extra={"action_id": action_id},
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve action from database"
            )

        if action is None:
            logger.warning(
                f"Action not found for status update",
                extra={"action_id": action_id}
            )
            raise HTTPException(
                status_code=404,
                detail=f"Action with id {action_id} not found"
            )

        # Store previous status
        previous_status = action.status

        # Update action
        action.status = request.status
        
        if request.details:
            action.details = request.details
        
        if request.error_message:
            action.error_message = request.error_message

        # Set completed_at for terminal states
        terminal_statuses = [
            ActionStatus.COMPLETED.value,
            ActionStatus.FAILED.value,
            ActionStatus.CANCELLED.value
        ]
        if request.status in terminal_statuses and action.completed_at is None:
            action.completed_at = datetime.utcnow()

        await db.flush()

        # Record metrics
        if metrics_available:
            try:
                metrics.record_action(
                    target=action.target,
                    action=action.action,
                    status=request.status
                )
            except Exception as e:
                logger.warning(f"Failed to record status update metric: {e}")

        logger.info(
            "Action status updated",
            extra={
                "action_id": action_id,
                "previous_status": previous_status,
                "new_status": request.status
            }
        )

        return UpdateActionStatusResponse(
            ok=True,
            action_id=action_id,
            message="Action status updated",
            previous_status=previous_status,
            new_status=request.status
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"Failed to update action status: {e}",
            extra={"action_id": action_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to update action status"
        )


# --- Remediator Integration Endpoints ---

class RemediationResultRequest(BaseModel):
    """Request model for remediation result from Go remediator."""
    task_id: str = Field(..., description="Unique task identifier")
    timestamp: int = Field(..., description="Unix timestamp of result")
    status: str = Field(..., description="Result status: success, failed, timeout, partial")
    resource: str = Field(..., description="Target resource")
    namespace: Optional[str] = Field(default=None, description="Kubernetes namespace")
    action: str = Field(..., description="Action type performed")
    duration: int = Field(default=0, description="Duration in milliseconds")
    error_message: Optional[str] = Field(default=None, description="Error message if failed")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional details")
    remediator_id: Optional[str] = Field(default=None, description="ID of the remediator")
    remediator_version: Optional[str] = Field(default=None, description="Version of remediator")
    retry_attempts: Optional[int] = Field(default=0, description="Number of retry attempts")

    @validator("status")
    def validate_status(cls, v):
        valid_statuses = ["success", "failed", "timeout", "partial"]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return v


class RemediationResultResponse(BaseModel):
    """Response for remediation result submission."""
    ok: bool = Field(default=True, description="Success flag")
    action_id: int = Field(..., description="Created/updated action ID")
    message: str = Field(default="Result recorded", description="Response message")


@router.post(
    "/remediator/results",
    response_model=RemediationResultResponse,
    summary="Record remediation result",
    description="Endpoint for Go remediator to report action results"
)
async def record_remediator_result(
    result: RemediationResultRequest,
    db: AsyncSession = Depends(get_db),
) -> RemediationResultResponse:
    """
    Record a remediation result from the Go remediator.

    This endpoint receives results from the Go remediator and creates
    or updates action records accordingly.

    Args:
        result: Remediation result from remediator
        db: AsyncSession for database operations

    Returns:
        RemediationResultResponse with action ID

    Raises:
        HTTPException: On database errors
    """
    try:
        logger.info(
            "Received remediation result",
            extra={
                "task_id": result.task_id,
                "resource": result.resource,
                "action": result.action,
                "status": result.status,
                "remediator_id": result.remediator_id
            }
        )

        # Map remediator status to action status
        status_map = {
            "success": ActionStatus.COMPLETED.value,
            "failed": ActionStatus.FAILED.value,
            "timeout": ActionStatus.FAILED.value,
            "partial": ActionStatus.FAILED.value
        }
        action_status = status_map.get(result.status, ActionStatus.FAILED.value)

        # Build details string
        details_parts = []
        if result.details:
            details_parts.append(f"Details: {result.details}")
        if result.remediator_id:
            details_parts.append(f"Remediator: {result.remediator_id}")
        if result.remediator_version:
            details_parts.append(f"Version: {result.remediator_version}")
        if result.duration > 0:
            details_parts.append(f"Duration: {result.duration}ms")
        if result.retry_attempts > 0:
            details_parts.append(f"Retries: {result.retry_attempts}")
        
        details_str = " | ".join(details_parts) if details_parts else None

        # Create the action record
        action = Action(
            target=result.resource,
            action=result.action,
            status=action_status,
            details=details_str,
            error_message=result.error_message,
            started_at=datetime.fromtimestamp(result.timestamp),
            completed_at=datetime.utcnow()
        )

        db.add(action)
        await db.flush()

        # Record metrics
        if metrics_available:
            try:
                metrics.record_action(
                    target=result.resource,
                    action=result.action,
                    status=action_status
                )
            except Exception as e:
                logger.warning(f"Failed to record remediator result metric: {e}")

        logger.info(
            "Remediation result recorded as action",
            extra={
                "action_id": action.id,
                "task_id": result.task_id,
                "status": action_status
            }
        )

        return RemediationResultResponse(
            ok=True,
            action_id=action.id,
            message="Result recorded successfully"
        )

    except Exception as e:
        logger.error(
            f"Failed to record remediation result: {e}",
            extra={"task_id": result.task_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to record remediation result"
        )


class RemediationTaskResponse(BaseModel):
    """Response model for pending remediation tasks."""
    tasks: List[Dict[str, Any]] = Field(default=[], description="Pending tasks")


@router.get(
    "/remediator/tasks",
    response_model=RemediationTaskResponse,
    summary="Get pending remediation tasks",
    description="Endpoint for Go remediator to fetch pending tasks"
)
async def get_remediator_tasks(
    limit: int = Query(default=10, ge=1, le=50, description="Maximum tasks to return"),
    remediator_id: Optional[str] = Query(default=None, description="Remediator ID"),
    db: AsyncSession = Depends(get_db),
) -> RemediationTaskResponse:
    """
    Get pending remediation tasks for the Go remediator.

    This endpoint returns pending actions that need to be executed
    by the remediator service.

    Args:
        limit: Maximum number of tasks to return
        remediator_id: ID of requesting remediator
        db: AsyncSession for database operations

    Returns:
        RemediationTaskResponse with pending tasks
    """
    try:
        logger.debug(
            "Remediator requesting tasks",
            extra={
                "remediator_id": remediator_id,
                "limit": limit
            }
        )

        # Query pending actions
        query = (
            select(Action)
            .where(Action.status == ActionStatus.PENDING.value)
            .order_by(Action.started_at.asc())
            .limit(limit)
        )

        result = await db.execute(query)
        actions = result.scalars().all()

        # Convert to task format expected by remediator
        tasks = []
        for action in actions:
            task = {
                "id": str(action.id),
                "timestamp": int(action.started_at.timestamp()) if action.started_at else 0,
                "resource": action.target,
                "namespace": "default",
                "action": action.action,
                "parameters": {},
                "priority": "medium",
                "policy_id": "",
                "timeout": 60,
                "max_retries": 3
            }
            tasks.append(task)

            # Mark as running
            action.status = ActionStatus.RUNNING.value

        if actions:
            await db.flush()

        logger.info(
            f"Returned {len(tasks)} tasks to remediator",
            extra={
                "task_count": len(tasks),
                "remediator_id": remediator_id
            }
        )

        return RemediationTaskResponse(tasks=tasks)

    except Exception as e:
        logger.error(
            f"Failed to get remediator tasks: {e}",
            extra={"remediator_id": remediator_id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to get pending tasks"
        )


@router.get(
    "/health",
    summary="Health check",
    description="Check if the actions service is operational"
)
async def health_check() -> Dict[str, str]:
    """
    Check health of the actions service.

    Returns:
        Health status
    """
    return {"status": "healthy", "service": "actions"}
