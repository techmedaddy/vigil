"""
Metrics ingestion endpoint for Vigil monitoring system.

Handles POST requests to store metrics and trigger policy evaluation.
"""

from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_db, Metric
from app.core.logger import get_logger
from app.core.config import get_settings
from app.core.utils import retry
from app.core.queue import enqueue_task

# Import metrics module if available
try:
    from app.core import metrics
    metrics_available = True
except ImportError:
    metrics_available = False

# Import policy engine if available
try:
    from app.core.policy import evaluate_policies
    policy_engine_available = True
except ImportError:
    policy_engine_available = False

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
        from app.services.evaluator import evaluate_policies
        return evaluate_policies
    except ImportError:
        logger.warning("Policy evaluator not available - policy evaluation will be skipped")
        return None


# --- Background task ---

@retry(
    max_attempts=3,
    backoff_strategy="exponential",
    exceptions=(Exception,),
    log_retries=True
)
async def trigger_remediation(
    payload: Dict[str, Any],
    remediator_url: str
) -> None:
    """
    Background task to trigger remediation actions with retry logic.

    Args:
        payload: Remediation request payload
        remediator_url: URL of the remediator service
    """
    import httpx

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
            # Raise exception to trigger retry
            raise Exception(f"Remediation request failed with status {response.status_code}")


@retry(
    max_attempts=None,  # Use config default
    backoff_strategy="exponential",
    exceptions=(SQLAlchemyError,),
    log_retries=True
)
async def store_metric_in_db(
    db: AsyncSession,
    metric: Metric
) -> int:
    """
    Store metric in database with retry logic for transient errors.

    Args:
        db: Database session
        metric: Metric instance to store

    Returns:
        ID of stored metric

    Raises:
        SQLAlchemyError: On database errors after retries exhausted
    """
    db.add(metric)
    await db.flush()
    return metric.id


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

        # Store metric with retry logic for transient DB errors
        try:
            metric_id = await store_metric_in_db(db, metric)
        except SQLAlchemyError as e:
            logger.error(
                f"Failed to store metric after retries: {e}",
                extra={"metric_name": payload.name},
                exc_info=True
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to store metric in database after retries"
            )

        # Record metric ingestion in Prometheus
        if metrics_available:
            try:
                metrics.record_ingest(metric_name=payload.name)
            except Exception as e:
                logger.warning(
                    "Failed to record ingest metric",
                    extra={"metric_name": payload.name, "error": str(e)}
                )

        logger.info(
            "Metric stored successfully",
            extra={
                "metric_id": metric.id,
                "metric_name": payload.name,
                "metric_value": payload.value
            }
        )

        # --- Policy Evaluation ---
        if policy_engine_available:
            try:
                # Prepare metrics dict for policy evaluation
                metrics_dict = {payload.name: payload.value}
                if payload.tags:
                    metrics_dict.update(payload.tags)

                # Evaluate policies
                eval_result = await evaluate_policies(metrics_dict)

                violations = eval_result.get("violations", [])
                actions_triggered = eval_result.get("actions_triggered", [])

                if violations:
                    logger.warning(
                        "Policy violations detected during metric ingestion",
                        extra={
                            "metric_name": payload.name,
                            "metric_value": payload.value,
                            "violations_count": len(violations),
                        }
                    )

                    # Log audit trail for each violation
                    for violation in violations:
                        logger.warning(
                            "Policy violation detected",
                            extra={
                                "policy_name": violation.get("policy_name"),
                                "severity": violation.get("severity"),
                                "target": violation.get("target"),
                                "metric_name": payload.name,
                                "metric_id": metric.id,
                            }
                        )

                if actions_triggered:
                    logger.info(
                        "Remediation actions triggered",
                        extra={
                            "metric_name": payload.name,
                            "action_count": len(actions_triggered),
                        }
                    )

            except Exception as e:
                logger.error(
                    "Policy evaluation failed",
                    exc_info=True,
                    extra={
                        "metric_name": payload.name,
                        "error": str(e),
                    }
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


@router.post(
    "/agent/metrics",
    response_model=IngestMetricResponse,
    status_code=201,
    summary="Ingest metrics from agent",
    description="Agent-specific endpoint for metric ingestion (alias for main ingest endpoint)"
)
async def ingest_agent_metrics(
    payload: IngestMetricRequest,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None,
    evaluator=Depends(get_evaluator),
    settings=Depends(lambda: get_settings()),
) -> IngestMetricResponse:
    """
    Ingest metrics from Vigil agent.
    
    This is an alias endpoint specifically for the Go agent which appends
    /agent/metrics to the collector URL. It uses the same logic as the
    main ingest endpoint.
    
    Args:
        payload: Metric data from agent
        db: Database session
        background_tasks: FastAPI background tasks
        evaluator: Policy evaluator dependency
        settings: Application settings
    
    Returns:
        IngestMetricResponse with metric ID and status
    """
    # Use the same logic as ingest_metric
    return await ingest_metric(payload, db, background_tasks, evaluator, settings)
