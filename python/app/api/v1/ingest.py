"""
Metrics ingestion endpoint for Vigil monitoring system.

Handles POST requests to store metrics and trigger policy evaluation.
"""

from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession

from python.app.core.db import get_db, Metric
from python.app.core.logger import get_logger
from python.app.core.config import get_settings

logger = get_logger(__name__)

# Create router with /ingest prefix
router = APIRouter(
    prefix="/ingest",
    tags=["metrics"],
    responses={
        400: {"description": "Invalid request"},
        500: {"description": "Internal server error"},
    },
)


# --- Pydantic Models ---

class IngestMetricRequest(BaseModel):
    """
    Request model for metric ingestion.

    Attributes:
        name: Metric name (e.g., 'cpu_usage', 'memory_usage')
        value: Numeric metric value
        tags: Optional dictionary of metric tags for categorization
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Metric name"
    )
    value: float = Field(
        ...,
        description="Numeric metric value"
    )
    tags: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional tags for the metric"
    )

    @validator("name")
    def validate_name(cls, v):
        """Ensure metric name is valid."""
        if not v or not v.strip():
            raise ValueError("Metric name cannot be empty")
        return v.strip()

    @validator("value")
    def validate_value(cls, v):
        """Ensure value is a valid number."""
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f"Value must be a valid number, got {type(v).__name__}")

    class Config:
        """Pydantic model configuration."""
        schema_extra = {
            "example": {
                "name": "cpu_usage",
                "value": 85.5,
                "tags": {"host": "web-server-01", "region": "us-east-1"}
            }
        }


class IngestMetricResponse(BaseModel):
    """Response model for successful metric ingestion."""

    ok: bool = Field(
        default=True,
        description="Success flag"
    )
    metric_id: int = Field(
        ...,
        description="ID of the stored metric"
    )
    message: str = Field(
        default="Metric ingested successfully",
        description="Response message"
    )

    class Config:
        """Pydantic model configuration."""
        schema_extra = {
            "example": {
                "ok": True,
                "metric_id": 123,
                "message": "Metric ingested successfully"
            }
        }


# --- Dependency for policy evaluation ---

def get_evaluator():
    """
    Get policy evaluator function.

    Returns:
        Policy evaluation function or None if not available.
    """
    try:
        from python.app.services.evaluator import evaluate_policies
        return evaluate_policies
    except ImportError:
        logger.warning("Policy evaluator not available - policy evaluation will be skipped")
        return None


# --- Background task ---

async def trigger_remediation(
    payload: Dict[str, Any],
    remediator_url: str
) -> None:
    """
    Background task to trigger remediation actions.

    Args:
        payload: Remediation request payload
        remediator_url: URL of the remediator service
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(remediator_url, json=payload)
            if response.status_code < 300:
                logger.info(
                    "Remediation triggered successfully",
                    extra={
                        "service": payload.get("service"),
                        "action": payload.get("action"),
                        "status_code": response.status_code
                    }
                )
            else:
                logger.warning(
                    f"Remediation request failed: {response.status_code}",
                    extra={
                        "service": payload.get("service"),
                        "action": payload.get("action"),
                        "status_code": response.status_code
                    }
                )
    except Exception as e:
        logger.error(
            f"Failed to trigger remediation: {e}",
            extra={
                "service": payload.get("service"),
                "action": payload.get("action")
            },
            exc_info=True
        )


# --- Routes ---

@router.post(
    "",
    response_model=IngestMetricResponse,
    status_code=201,
    summary="Ingest a metric",
    description="Store a new metric and evaluate policies for remediation"
)
async def ingest_metric(
    payload: IngestMetricRequest,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None,
    evaluator=Depends(get_evaluator),
    settings=Depends(lambda: get_settings()),
) -> IngestMetricResponse:
    """
    Ingest a metric into the system.

    This endpoint:
    1. Validates the metric payload
    2. Stores the metric in the database
    3. Evaluates configured policies
    4. Triggers remediation actions if policies are triggered

    Args:
        payload: Metric data (name, value, tags)
        db: AsyncSession for database operations
        background_tasks: FastAPI background tasks manager
        evaluator: Policy evaluation function
        settings: Application settings

    Returns:
        IngestMetricResponse with metric ID and status

    Raises:
        HTTPException: On validation or database errors
    """
    try:
        logger.info(
            "Metric ingestion started",
            extra={
                "metric_name": payload.name,
                "metric_value": payload.value,
                "has_tags": payload.tags is not None
            }
        )

        # Create metric instance
        metric = Metric(
            name=payload.name,
            value=payload.value,
            timestamp=datetime.utcnow()
        )

        # Add to session and flush to get the ID
        db.add(metric)
        await db.flush()

        logger.info(
            "Metric stored successfully",
            extra={
                "metric_id": metric.id,
                "metric_name": payload.name,
                "metric_value": payload.value
            }
        )

        # --- Policy Evaluation ---
        if evaluator is not None:
            try:
                triggered_actions = evaluator(payload.name, payload.value)

                if triggered_actions:
                    logger.warning(
                        f"Policy triggered: {len(triggered_actions)} action(s)",
                        extra={
                            "metric_name": payload.name,
                            "metric_value": payload.value,
                            "action_count": len(triggered_actions)
                        }
                    )

                    # Trigger remediation for each action
                    for action in triggered_actions:
                        remediation_payload = {
                            "service": action.get("target"),
                            "action": action.get("action"),
                            "policy": action.get("policy"),
                            "metric_name": payload.name,
                            "metric_value": payload.value,
                            "metric_id": metric.id
                        }

                        logger.info(
                            f"Queuing remediation: {action.get('policy')} → {action.get('action')}",
                            extra={
                                "target": action.get("target"),
                                "action": action.get("action"),
                                "policy": action.get("policy")
                            }
                        )

                        if background_tasks:
                            background_tasks.add_task(
                                trigger_remediation,
                                remediation_payload,
                                settings.REMEDIATOR_URL
                            )
                else:
                    logger.debug(
                        "No policies triggered",
                        extra={
                            "metric_name": payload.name,
                            "metric_value": payload.value
                        }
                    )

            except Exception as e:
                logger.error(
                    f"Policy evaluation failed: {e}",
                    extra={
                        "metric_name": payload.name,
                        "metric_value": payload.value
                    },
                    exc_info=True
                )
                # Don't fail the ingest if policy evaluation fails
        # --- End Policy Evaluation ---

        return IngestMetricResponse(
            ok=True,
            metric_id=metric.id,
            message="Metric ingested successfully"
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
            f"Failed to ingest metric: {e}",
            extra={"metric_name": payload.name},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to store metric in database"
        )


@router.get(
    "/health",
    summary="Health check",
    description="Check if the ingest service is operational"
)
async def health_check() -> Dict[str, str]:
    """
    Check health of the ingest service.

    Returns:
        Health status
    """
    return {"status": "healthy", "service": "ingest"}
