"""Policy Tester endpoint for auto-injecting matching metrics for policies."""

import re
import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.policy import (
    get_policy_registry,
    Policy,
)
from app.core.logger import get_logger

logger = get_logger(__name__)

# Create router with /policy-tester prefix
router = APIRouter(
    prefix="/policy-tester",
    tags=["policy-tester"],
    responses={
        400: {"description": "Invalid request"},
        404: {"description": "Policy not found"},
        500: {"description": "Internal server error"},
    },
)


# --- Pydantic Models ---

class InjectMetricRequest(BaseModel):
    """Request model for policy metric injection."""

    policy_id: str = Field(
        ...,
        min_length=1,
        description="The policy ID (name) to generate a violating metric for"
    )

    class Config:
        schema_extra = {
            "example": {
                "policy_id": "high-cpu-alert"
            }
        }


class InjectMetricResponse(BaseModel):
    """Response model for policy metric injection."""

    policy_id: str = Field(..., description="The policy ID that was tested")
    metric_payload: Dict[str, Any] = Field(..., description="The generated metric payload")
    action_triggered: bool = Field(..., description="Whether an action was triggered")
    correlation_id: str = Field(..., description="Correlation ID for tracing")
    message: str = Field(default="", description="Additional information")
    violation_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Details about the policy violation"
    )
    actions: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="List of actions triggered"
    )

    class Config:
        schema_extra = {
            "example": {
                "policy_id": "high-cpu-alert",
                "metric_payload": {"cpu_percent": 95.0},
                "action_triggered": True,
                "correlation_id": "inject-abc123",
                "message": "Metric injected successfully, policy violated",
                "violation_details": {
                    "policy_name": "high-cpu-alert",
                    "severity": "warning"
                },
                "actions": [{"action": "scale-up", "status": "success"}]
            }
        }


# --- Metric Generation Logic ---

def _extract_condition_info(policy: Policy) -> Dict[str, Any]:
    """
    Extract condition information from a policy's condition function.
    
    Uses function inspection and closure analysis to determine
    the metric name, threshold, and condition type.
    """
    condition = policy.condition
    info = {
        "type": "unknown",
        "metric": None,
        "threshold": None,
        "conditions": []
    }
    
    # Try to extract from closure variables
    if hasattr(condition, '__closure__') and condition.__closure__:
        closure_vars = {}
        if hasattr(condition, '__code__'):
            var_names = condition.__code__.co_freevars
            for i, cell in enumerate(condition.__closure__):
                try:
                    if i < len(var_names):
                        closure_vars[var_names[i]] = cell.cell_contents
                except ValueError:
                    # Cell is empty
                    pass
        
        # Check for metric_exceeds pattern
        if 'metric_name' in closure_vars and 'threshold' in closure_vars:
            info["metric"] = closure_vars['metric_name']
            info["threshold"] = closure_vars['threshold']
            
            # Determine if exceeds or below based on function name or logic
            func_name = getattr(condition, '__qualname__', '') or getattr(condition, '__name__', '')
            if 'below' in func_name.lower() or 'below' in str(condition):
                info["type"] = "metric_below"
            else:
                info["type"] = "metric_exceeds"
        
        # Check for combined conditions (all/any)
        if 'conditions' in closure_vars:
            info["type"] = "combined"
            info["conditions"] = closure_vars['conditions']
    
    # Fallback: Try to determine from function name
    if info["type"] == "unknown":
        func_name = getattr(condition, '__qualname__', '') or getattr(condition, '__name__', '')
        if 'exceeds' in func_name.lower():
            info["type"] = "metric_exceeds"
        elif 'below' in func_name.lower():
            info["type"] = "metric_below"
        elif 'all_conditions' in func_name.lower() or 'all' in func_name.lower():
            info["type"] = "all"
        elif 'any_condition' in func_name.lower() or 'any' in func_name.lower():
            info["type"] = "any"
    
    return info


def _generate_violating_payload(policy: Policy) -> Dict[str, Any]:
    """
    Generate a synthetic metric payload that violates the policy condition.
    
    Supports:
    - metric_exceeds: Sets value above threshold
    - metric_below: Sets value below threshold
    - all conditions: Generates payloads that satisfy all sub-conditions
    - any conditions: Generates payload that satisfies at least one sub-condition
    - regex match: Crafts a matching string
    - missing field: Omits required field
    """
    condition_info = _extract_condition_info(policy)
    payload = {}
    
    logger.debug(
        "Extracted condition info",
        extra={
            "policy_name": policy.name,
            "condition_info": condition_info,
        }
    )
    
    condition_type = condition_info.get("type", "unknown")
    metric = condition_info.get("metric")
    threshold = condition_info.get("threshold")
    
    if condition_type == "metric_exceeds" and metric and threshold is not None:
        # Generate value above threshold (10% above + 1 to ensure breach)
        violating_value = float(threshold) * 1.1 + 1
        payload[metric] = round(violating_value, 2)
        logger.info(
            f"Generated exceeds payload: {metric}={payload[metric]} (threshold: {threshold})"
        )
    
    elif condition_type == "metric_below" and metric and threshold is not None:
        # Generate value below threshold (10% below - 1 to ensure breach)
        violating_value = float(threshold) * 0.9 - 1
        # Ensure we don't go negative for percentages
        violating_value = max(0, violating_value)
        payload[metric] = round(violating_value, 2)
        logger.info(
            f"Generated below payload: {metric}={payload[metric]} (threshold: {threshold})"
        )
    
    elif condition_type == "combined" or condition_type in ("all", "any"):
        # Handle combined conditions by recursively extracting from sub-conditions
        sub_conditions = condition_info.get("conditions", [])
        for sub_condition in sub_conditions:
            sub_info = _extract_condition_info_from_func(sub_condition)
            sub_metric = sub_info.get("metric")
            sub_threshold = sub_info.get("threshold")
            sub_type = sub_info.get("type")
            
            if sub_metric and sub_threshold is not None:
                if sub_type == "metric_exceeds":
                    payload[sub_metric] = round(float(sub_threshold) * 1.1 + 1, 2)
                elif sub_type == "metric_below":
                    payload[sub_metric] = max(0, round(float(sub_threshold) * 0.9 - 1, 2))
    
    else:
        # Fallback: Try to infer from policy params or use common defaults
        params = policy.params or {}
        
        # Check if params has hints about metric names
        if "metric" in params:
            metric_name = params["metric"]
            payload[metric_name] = 100.0  # Default high value
        
        # Use policy name to infer metric type
        policy_name_lower = policy.name.lower()
        
        if "cpu" in policy_name_lower:
            payload["cpu_percent"] = 95.0
        elif "memory" in policy_name_lower or "mem" in policy_name_lower:
            payload["memory_percent"] = 90.0
        elif "disk" in policy_name_lower:
            payload["disk_free_percent"] = 2.0  # Low disk space
        elif "error" in policy_name_lower or "failure" in policy_name_lower:
            payload["error_rate"] = 50.0
            payload["failure_rate"] = 12.5
        elif "health" in policy_name_lower:
            payload["health_check_failures"] = 5
        elif "restart" in policy_name_lower:
            payload["restart_count"] = 10
        elif "latency" in policy_name_lower or "response" in policy_name_lower:
            payload["response_time_ms"] = 5000
        else:
            # Generic high value for unknown metrics
            payload["test_metric"] = 100.0
        
        logger.warning(
            f"Could not extract condition details, using inferred payload for '{policy.name}'",
            extra={"payload": payload}
        )
    
    return payload


def _extract_condition_info_from_func(func) -> Dict[str, Any]:
    """Extract condition info from a condition function."""
    info = {
        "type": "unknown",
        "metric": None,
        "threshold": None,
    }
    
    if hasattr(func, '__closure__') and func.__closure__:
        if hasattr(func, '__code__'):
            var_names = func.__code__.co_freevars
            for i, cell in enumerate(func.__closure__):
                try:
                    if i < len(var_names):
                        name = var_names[i]
                        value = cell.cell_contents
                        if name == 'metric_name':
                            info["metric"] = value
                        elif name == 'threshold':
                            info["threshold"] = value
                except ValueError:
                    pass
        
        func_name = getattr(func, '__qualname__', '') or getattr(func, '__name__', '')
        if 'below' in func_name.lower():
            info["type"] = "metric_below"
        else:
            info["type"] = "metric_exceeds"
    
    return info


# --- Endpoints ---

@router.post("/inject", response_model=InjectMetricResponse)
async def inject_test_metric(request: InjectMetricRequest) -> InjectMetricResponse:
    """
    Inject a synthetic metric that violates the specified policy.
    
    This endpoint:
    1. Looks up the policy by ID
    2. Generates a synthetic metric payload that violates the policy condition
    3. Injects the payload into the ingestion pipeline
    4. Returns confirmation with violation and action details
    
    Args:
        request: InjectMetricRequest with policy_id
    
    Returns:
        InjectMetricResponse with metric payload and action status
    
    Raises:
        HTTPException: If policy not found or injection fails
    
    Example:
        POST /api/v1/policy-tester/inject
        {
            "policy_id": "high-cpu-alert"
        }
        
        Response:
        {
            "policy_id": "high-cpu-alert",
            "metric_payload": {"cpu_percent": 95.0},
            "action_triggered": true,
            "correlation_id": "inject-abc123",
            "message": "Metric injected successfully"
        }
    """
    # Generate correlation ID for tracing
    correlation_id = f"inject-{uuid.uuid4().hex[:12]}"
    
    logger.info(
        "Policy test injection started",
        extra={
            "policy_id": request.policy_id,
            "correlation_id": correlation_id,
        }
    )
    
    try:
        # 1. Look up the policy by ID
        registry = get_policy_registry()
        policy = registry.get(request.policy_id)
        
        if not policy:
            logger.warning(
                "Policy not found for injection",
                extra={
                    "policy_id": request.policy_id,
                    "correlation_id": correlation_id,
                }
            )
            raise HTTPException(
                status_code=404,
                detail=f"Policy '{request.policy_id}' not found"
            )
        
        # 2. Generate synthetic metric payload that violates the policy
        metric_payload = _generate_violating_payload(policy)
        
        logger.info(
            "Generated violating metric payload",
            extra={
                "policy_id": request.policy_id,
                "correlation_id": correlation_id,
                "metric_payload": metric_payload,
            }
        )
        
        # 3. Inject the payload through the ingestion pipeline
        action_triggered = False
        violation_details = None
        actions_list = []
        
        try:
            # Import and use the ingestion function
            from app.core.policy import evaluate_policies
            
            # Evaluate policies with the generated metrics
            eval_result = await evaluate_policies(metric_payload, policy.target)
            
            violations = eval_result.get("violations", [])
            actions = eval_result.get("actions_triggered", [])
            
            # Check if our target policy was violated
            for violation in violations:
                if violation.get("policy_name") == request.policy_id:
                    action_triggered = len(actions) > 0
                    violation_details = violation
                    break
            
            actions_list = actions
            
            logger.info(
                "Policy evaluation completed",
                extra={
                    "policy_id": request.policy_id,
                    "correlation_id": correlation_id,
                    "violations_count": len(violations),
                    "actions_count": len(actions),
                    "action_triggered": action_triggered,
                }
            )
            
            # Also try to inject via the ingest endpoint for full pipeline integration
            try:
                from app.core.db import get_db_manager, Metric
                from datetime import datetime
                
                db_manager = get_db_manager()
                async with db_manager.session() as db:
                    # Store each metric in the payload
                    for metric_name, metric_value in metric_payload.items():
                        metric = Metric(
                            name=metric_name,
                            value=float(metric_value),
                            timestamp=datetime.utcnow()
                        )
                        db.add(metric)
                    await db.commit()
                    
                logger.info(
                    "Metrics stored in database",
                    extra={
                        "policy_id": request.policy_id,
                        "correlation_id": correlation_id,
                        "metrics_stored": len(metric_payload),
                    }
                )
            except Exception as db_error:
                logger.warning(
                    "Could not store metrics in database (non-fatal)",
                    extra={
                        "policy_id": request.policy_id,
                        "correlation_id": correlation_id,
                        "error": str(db_error),
                    }
                )
        
        except Exception as eval_error:
            logger.error(
                "Policy evaluation failed during injection",
                extra={
                    "policy_id": request.policy_id,
                    "correlation_id": correlation_id,
                    "error": str(eval_error),
                },
                exc_info=True
            )
            # Continue with response even if evaluation fails
        
        # 4. Return confirmation
        message = "Metric injected successfully"
        if action_triggered:
            message += ", policy violated and action triggered"
        elif violation_details:
            message += ", policy violated (no auto-remediation)"
        else:
            message += " (policy may not have been triggered - check if policy is enabled)"
        
        logger.info(
            "Policy test injection completed",
            extra={
                "policy_id": request.policy_id,
                "correlation_id": correlation_id,
                "action_triggered": action_triggered,
                "message": message,
            }
        )
        
        return InjectMetricResponse(
            policy_id=request.policy_id,
            metric_payload=metric_payload,
            action_triggered=action_triggered,
            correlation_id=correlation_id,
            message=message,
            violation_details=violation_details,
            actions=actions_list if actions_list else None,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Policy test injection failed",
            extra={
                "policy_id": request.policy_id,
                "correlation_id": correlation_id,
                "error": str(e),
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to inject test metric: {str(e)}"
        )


@router.get("/policy/{policy_id}/preview")
async def preview_violating_payload(policy_id: str) -> Dict[str, Any]:
    """
    Preview the synthetic payload that would be generated for a policy.
    
    This is a dry-run endpoint that shows what payload would be generated
    without actually injecting it.
    
    Args:
        policy_id: The policy ID to preview
    
    Returns:
        Preview of the generated payload and policy info
    """
    registry = get_policy_registry()
    policy = registry.get(policy_id)
    
    if not policy:
        raise HTTPException(
            status_code=404,
            detail=f"Policy '{policy_id}' not found"
        )
    
    payload = _generate_violating_payload(policy)
    condition_info = _extract_condition_info(policy)
    
    return {
        "policy_id": policy_id,
        "policy_info": policy.to_dict(),
        "condition_analysis": condition_info,
        "generated_payload": payload,
        "would_violate": True,
        "note": "Use POST /api/v1/policy-tester/inject to actually inject this payload"
    }
