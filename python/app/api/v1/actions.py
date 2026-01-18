"""
Actions endpoint for Vigil monitoring system.

Handles POST/GET requests for remediation action management and tracking.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db, Action
from app.core.logger import get_logger
from app.core.config import get_settings

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
    """Valid action statuses."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# --- Pydantic Models ---

class CreateActionRequest(BaseModel):
    """
    Request model for creating an action.

    Attributes:
        target: Target resource (e.g., 'web-service', 'database-pod')
        action: Action type (e.g., 'restart', 'scale-up', 'drain')
        status: Current status of the action
        details: Optional detailed information about the action
    """

    target: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Target resource identifier"
    )
    action: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Action type to perform"
    )
    status: str = Field(
        default=ActionStatus.PENDING,
        description="Action status"
    )
    details: Optional[str] = Field(
        default=None,
        description="Additional details about the action"
    )

    @validator("target")
    def validate_target(cls, v):
        """Ensure target is valid."""
        if not v or not v.strip():
            raise ValueError("Target cannot be empty")
        return v.strip()

    @validator("action")
    def validate_action(cls, v):
        """Ensure action is valid."""
        if not v or not v.strip():
            raise ValueError("Action cannot be empty")
        return v.strip()

    @validator("status")
    def validate_status(cls, v):
        """Ensure status is valid."""
        valid_statuses = [s.value for s in ActionStatus]
        if v not in valid_statuses:
            raise ValueError(f"Status must be one of {valid_statuses}")
        return v

    class Config:
        """Pydantic model configuration."""
        schema_extra = {
            "example": {
                "target": "web-service",
                "action": "restart",
                "status": "pending",
                "details": "Triggered by high CPU policy"
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

    class Config:
        """Pydantic model configuration."""
        schema_extra = {
            "example": {
                "ok": True,
                "action_id": 1,
                "message": "Action created successfully"
            }
        }


class ActionDetailResponse(BaseModel):
    """Response model for action details."""

    id: int
    target: str
    action: str
    status: str
    details: Optional[str] = None
    started_at: datetime

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
                "started_at": "2026-01-13T12:34:56Z"
            }
        }


class ListActionsResponse(BaseModel):
    """Response model for listing actions."""

    count: int = Field(..., description="Number of actions returned")
    actions: List[ActionDetailResponse] = Field(..., description="List of actions")


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
    1. Validates the action payload
    2. Stores the action in the database
    3. Returns the action ID

    Args:
        payload: Action data (target, action, status, details)
        db: AsyncSession for database operations

    Returns:
        ActionResponse with action ID and status

    Raises:
        HTTPException: On validation or database errors
    """
    try:
        logger.info(
            "Action creation started",
            extra={
                "target": payload.target,
                "action": payload.action,
                "status": payload.status
            }
        )

        # Create action instance
        action = Action(
            target=payload.target,
            action=payload.action,
            status=payload.status,
            details=payload.details,
            started_at=datetime.utcnow()
        )

        # Add to session and flush to get the ID
        db.add(action)
        await db.flush()

        # Record action in Prometheus metrics
        if metrics_available:
            try:
                metrics.record_action(
                    target=payload.target,
                    action=payload.action,
                    status=payload.status
                )
            except Exception as e:
                logger.warning(
                    "Failed to record action metric",
                    extra={
                        "target": payload.target,
                        "action": payload.action,
                        "error": str(e)
                    }
                )

        logger.warning(
            "Action created",
            extra={
                "action_id": action.id,
                "target": payload.target,
                "action": payload.action,
                "status": payload.status
            }
        )

        return ActionResponse(
            ok=True,
            action_id=action.id,
            message="Action created successfully"
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

    except Exception as e:
        logger.error(
            f"Failed to create action: {e}",
            extra={
                "target": payload.target,
                "action": payload.action
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
    description="Retrieve recent actions"
)
async def list_actions(
    limit: int = 50,
    status: Optional[str] = None,
    target: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> ListActionsResponse:
    """
    Retrieve a list of recent actions.

    Args:
        limit: Maximum number of actions to return (default: 50, max: 500)
        status: Optional filter by action status
        target: Optional filter by target resource
        db: AsyncSession for database operations

    Returns:
        ListActionsResponse with count and action list

    Raises:
        HTTPException: On database errors
    """
    try:
        # Validate limit
        limit = min(limit, 500)
        if limit < 1:
            limit = 1

        logger.debug(
            "Listing actions",
            extra={
                "limit": limit,
                "status_filter": status,
                "target_filter": target
            }
        )

        # Build query
        query = select(Action).order_by(Action.started_at.desc()).limit(limit)

        # Apply filters if provided
        if status:
            valid_statuses = [s.value for s in ActionStatus]
            if status in valid_statuses:
                query = query.where(Action.status == status)

        if target:
            query = query.where(Action.target == target)

        # Execute query
        result = await db.execute(query)
        actions = result.scalars().all()

        logger.info(
            f"Retrieved {len(actions)} actions",
            extra={
                "count": len(actions),
                "limit": limit,
                "status_filter": status,
                "target_filter": target
            }
        )

        return ListActionsResponse(
            count=len(actions),
            actions=[
                ActionDetailResponse(
                    id=a.id,
                    target=a.target,
                    action=a.action,
                    status=a.status,
                    details=a.details,
                    started_at=a.started_at
                )
                for a in actions
            ]
        )

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

        query = select(Action).where(Action.id == action_id)
        result = await db.execute(query)
        action = result.scalar_one_or_none()

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
            started_at=action.started_at
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

        result = await db.execute(query)
        actions = result.scalars().all()

        logger.info(
            f"Retrieved {len(actions)} {action_status} actions",
            extra={
                "count": len(actions),
                "status": action_status
            }
        )

        return ListActionsResponse(
            count=len(actions),
            actions=[
                ActionDetailResponse(
                    id=a.id,
                    target=a.target,
                    action=a.action,
                    status=a.status,
                    details=a.details,
                    started_at=a.started_at
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
