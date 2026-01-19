"""
Policies endpoint for Vigil monitoring system.

Handles policy management, evaluation, and remediation.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field, validator

from app.core.policy import (
    get_policy_registry,
    evaluate_policies,
    initialize_policies,
    Policy,
    Severity,
    ActionType,
    metric_exceeds,
    metric_below,
    all_conditions,
    any_condition,
)
from app.core.logger import get_logger

logger = get_logger(__name__)


# --- Helper Functions ---

def _build_condition_from_config(config: Dict[str, Any]):
    """
    Build a condition function from configuration.

    Args:
        config: Condition configuration dictionary

    Returns:
        Callable condition function

    Raises:
        ValueError: If condition type is invalid
    """
    condition_type = config.get("type")

    if condition_type == "metric_exceeds":
        return metric_exceeds(config["metric"], config["threshold"])
    elif condition_type == "metric_below":
        return metric_below(config["metric"], config["threshold"])
    elif condition_type == "all":
        sub_conditions = [_build_condition_from_config(c) for c in config["conditions"]]
        return all_conditions(*sub_conditions)
    elif condition_type == "any":
        sub_conditions = [_build_condition_from_config(c) for c in config["conditions"]]
        return any_condition(*sub_conditions)
    else:
        raise ValueError(f"Unknown condition type: {condition_type}")


def _build_action_from_string(action_str: str):
    """
    Convert action string to ActionType or callable.

    Args:
        action_str: Action string (scale-up, restart, drain-pod, custom)

    Returns:
        ActionType enum or callable

    Raises:
        ValueError: If action is invalid
    """
    action_map = {
        "scale-up": ActionType.SCALE_UP,
        "restart": ActionType.RESTART_SERVICE,
        "drain-pod": ActionType.DRAIN_POD,
        "custom": ActionType.CUSTOM,
    }

    if action_str not in action_map:
        raise ValueError(f"Invalid action: {action_str}")

    return action_map[action_str]

# Create router with /policies prefix
router = APIRouter(
    prefix="/policies",
    tags=["policies"],
    responses={
        400: {"description": "Invalid request"},
        404: {"description": "Policy not found"},
        500: {"description": "Internal server error"},
    },
)


# --- Pydantic Models ---

class PolicyInfo(BaseModel):
    """Policy information model for API responses."""

    name: str = Field(..., description="Policy name")
    description: str = Field(..., description="Policy description")
    severity: str = Field(..., description="Violation severity")
    target: str = Field(..., description="Target resource pattern")
    enabled: bool = Field(..., description="Whether policy is active")
    params: Dict[str, Any] = Field(..., description="Action parameters")
    auto_remediate: bool = Field(..., description="Auto remediation enabled")


class PolicyListResponse(BaseModel):
    """Response model for listing policies."""

    ok: bool = Field(default=True, description="Success flag")
    policies: Dict[str, PolicyInfo] = Field(..., description="Map of policies")
    total: int = Field(..., description="Total number of policies")
    enabled_count: int = Field(..., description="Number of enabled policies")


class EvaluateRequest(BaseModel):
    """Request model for policy evaluation."""

    metrics: Dict[str, Any] = Field(..., description="Metric values to evaluate")
    target: Optional[str] = Field(None, description="Optional target resource filter")


class PolicyViolation(BaseModel):
    """Policy violation model."""

    policy_name: str = Field(..., description="Name of violated policy")
    severity: str = Field(..., description="Violation severity")
    description: str = Field(..., description="Policy description")
    target: str = Field(..., description="Target resource")
    timestamp: str = Field(..., description="Violation timestamp (ISO 8601)")


class ActionResult(BaseModel):
    """Remediation action result model."""

    action: str = Field(..., description="Action type")
    target: str = Field(..., description="Target resource")
    status: str = Field(..., description="Action status")
    params: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")


class EvaluateResponse(BaseModel):
    """Response model for policy evaluation."""

    ok: bool = Field(default=True, description="Success flag")
    violations: List[PolicyViolation] = Field(..., description="Detected violations")
    actions_triggered: List[ActionResult] = Field(..., description="Triggered actions")
    timestamp: str = Field(..., description="Evaluation timestamp")


class PolicyEnableRequest(BaseModel):
    """Request to enable/disable a policy."""

    enabled: bool = Field(..., description="Whether to enable or disable")


class MessageResponse(BaseModel):
    """Generic message response."""

    ok: bool = Field(default=True, description="Success flag")
    message: str = Field(..., description="Response message")


class PolicyCreateRequest(BaseModel):
    """Request model for creating a new policy."""

    name: str = Field(..., description="Unique policy name")
    description: str = Field("", description="Policy description")
    severity: str = Field("warning", description="Severity level: info, warning, critical")
    target: str = Field("all", description="Target resource pattern")
    enabled: bool = Field(True, description="Whether policy starts enabled")
    auto_remediate: bool = Field(False, description="Whether to auto-remediate violations")
    condition: Dict[str, Any] = Field(..., description="Condition configuration")
    action: str = Field(..., description="Action to take: scale-up, restart, drain-pod, custom")
    params: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")

    @validator("severity")
    def validate_severity(cls, v):
        valid = ["info", "warning", "critical"]
        if v not in valid:
            raise ValueError(f"severity must be one of {valid}")
        return v

    @validator("action")
    def validate_action(cls, v):
        valid = ["scale-up", "restart", "drain-pod", "custom"]
        if v not in valid:
            raise ValueError(f"action must be one of {valid}")
        return v


class PolicyUpdateRequest(BaseModel):
    """Request model for updating a policy."""

    description: Optional[str] = Field(None, description="Policy description")
    severity: Optional[str] = Field(None, description="Severity level")
    target: Optional[str] = Field(None, description="Target resource pattern")
    enabled: Optional[bool] = Field(None, description="Whether policy is enabled")
    auto_remediate: Optional[bool] = Field(None, description="Whether to auto-remediate")
    params: Optional[Dict[str, Any]] = Field(None, description="Action parameters")

    @validator("severity")
    def validate_severity(cls, v):
        if v is not None:
            valid = ["info", "warning", "critical"]
            if v not in valid:
                raise ValueError(f"severity must be one of {valid}")
        return v


# --- Endpoints ---

@router.post("", response_model=PolicyInfo, status_code=201)
async def create_policy(request: PolicyCreateRequest) -> PolicyInfo:
    """
    Create a new policy.

    Args:
        request: PolicyCreateRequest with policy configuration

    Returns:
        PolicyInfo with created policy details

    Raises:
        HTTPException: If policy name already exists or invalid configuration

    Example:
        ```json
        {
            "name": "my-policy",
            "description": "My custom policy",
            "severity": "warning",
            "target": "web-*",
            "enabled": true,
            "auto_remediate": false,
            "condition": {
                "type": "metric_exceeds",
                "metric": "cpu_percent",
                "threshold": 85
            },
            "action": "scale-up",
            "params": {"replicas": 2}
        }
        ```
    """
    try:
        registry = get_policy_registry()

        # Check if policy already exists
        if registry.get(request.name):
            raise HTTPException(
                status_code=400,
                detail=f"Policy '{request.name}' already exists"
            )

        # Build condition from config
        try:
            condition = _build_condition_from_config(request.condition)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid condition configuration: {str(e)}"
            )

        # Build action
        try:
            action = _build_action_from_string(request.action)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action: {str(e)}"
            )

        # Parse severity
        try:
            severity = Severity(request.severity)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid severity: {request.severity}"
            )

        # Create policy
        policy = Policy(
            name=request.name,
            description=request.description,
            condition=condition,
            action=action,
            severity=severity,
            target=request.target,
            enabled=request.enabled,
            params=request.params,
            auto_remediate=request.auto_remediate,
        )

        # Register policy
        registry.register(policy)

        logger.info(f"Policy '{request.name}' created successfully")

        policy_dict = policy.to_dict()
        return PolicyInfo(**policy_dict)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to create policy",
            policy_name=request.name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to create policy")


@router.put("/{policy_name}", response_model=PolicyInfo)
async def update_policy(policy_name: str, request: PolicyUpdateRequest) -> PolicyInfo:
    """
    Update an existing policy.

    Args:
        policy_name: Name of the policy to update
        request: PolicyUpdateRequest with fields to update

    Returns:
        PolicyInfo with updated policy details

    Raises:
        HTTPException: If policy not found

    Example:
        ```json
        {
            "description": "Updated description",
            "severity": "critical",
            "params": {"replicas": 3}
        }
        ```
    """
    try:
        registry = get_policy_registry()

        # Get existing policy
        policy = registry.get(policy_name)
        if not policy:
            raise HTTPException(
                status_code=404,
                detail=f"Policy '{policy_name}' not found"
            )

        # Update fields if provided
        if request.description is not None:
            policy.description = request.description

        if request.severity is not None:
            policy.severity = Severity(request.severity)

        if request.target is not None:
            policy.target = request.target

        if request.enabled is not None:
            policy.enabled = request.enabled

        if request.auto_remediate is not None:
            policy.auto_remediate = request.auto_remediate

        if request.params is not None:
            policy.params = request.params

        logger.info(f"Policy '{policy_name}' updated successfully")

        policy_dict = policy.to_dict()
        return PolicyInfo(**policy_dict)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to update policy",
            policy_name=policy_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update policy")


@router.delete("/{policy_name}", response_model=MessageResponse)
async def delete_policy(policy_name: str) -> MessageResponse:
    """
    Delete a policy.

    Args:
        policy_name: Name of the policy to delete

    Returns:
        MessageResponse confirming deletion

    Raises:
        HTTPException: If policy not found
    """
    try:
        registry = get_policy_registry()

        # Check if policy exists
        if not registry.get(policy_name):
            raise HTTPException(
                status_code=404,
                detail=f"Policy '{policy_name}' not found"
            )

        # Unregister policy
        registry.unregister(policy_name)

        logger.info(f"Policy '{policy_name}' deleted successfully")

        return MessageResponse(
            ok=True,
            message=f"Policy '{policy_name}' deleted",
        )

    except HTTPException:
        raise
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Policy '{policy_name}' not found"
        )
    except Exception as e:
        logger.error(
            "Failed to delete policy",
            policy_name=policy_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to delete policy")


@router.get("", response_model=PolicyListResponse)
async def list_policies() -> PolicyListResponse:
    """
    List all registered policies.

    Returns:
        PolicyListResponse with all policies and counts
    """
    try:
        registry = get_policy_registry()
        policies = registry.list_policies()
        enabled_count = len(registry.get_enabled())

        return PolicyListResponse(
            ok=True,
            policies={
                name: PolicyInfo(**info) for name, info in policies.items()
            },
            total=len(policies),
            enabled_count=enabled_count,
        )
    except Exception as e:
        logger.error("Failed to list policies", exc_info=True, extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to list policies")


@router.get("/{policy_name}", response_model=PolicyInfo)
async def get_policy(policy_name: str) -> PolicyInfo:
    """
    Get details of a specific policy.

    Args:
        policy_name: Name of the policy

    Returns:
        PolicyInfo with policy details

    Raises:
        HTTPException: If policy not found
    """
    try:
        registry = get_policy_registry()
        policy = registry.get(policy_name)

        if not policy:
            raise HTTPException(status_code=404, detail=f"Policy '{policy_name}' not found")

        policy_dict = policy.to_dict()
        return PolicyInfo(**policy_dict)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get policy",
            policy_name=policy_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to get policy")


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate_all_policies(request: EvaluateRequest) -> EvaluateResponse:
    """
    Evaluate all enabled policies against provided metrics.

    Args:
        request: EvaluateRequest with metrics and optional target

    Returns:
        EvaluateResponse with violations and actions

    Example:
        ```json
        {
            "metrics": {
                "cpu_percent": 95,
                "memory_percent": 88,
                "disk_free_percent": 10
            },
            "target": "web-server-01"
        }
        ```
    """
    try:
        result = await evaluate_policies(request.metrics, request.target)

        return EvaluateResponse(
            ok=True,
            violations=[
                PolicyViolation(**v) for v in result.get("violations", [])
            ],
            actions_triggered=[
                ActionResult(**a) for a in result.get("actions_triggered", [])
            ],
            timestamp=result.get("timestamp"),
        )
    except Exception as e:
        logger.error(
            "Failed to evaluate policies",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to evaluate policies")


@router.put("/{policy_name}/enable", response_model=MessageResponse)
async def enable_policy(policy_name: str) -> MessageResponse:
    """
    Enable a policy.

    Args:
        policy_name: Name of the policy

    Returns:
        MessageResponse confirming enablement

    Raises:
        HTTPException: If policy not found
    """
    try:
        registry = get_policy_registry()
        registry.enable_policy(policy_name)

        return MessageResponse(
            ok=True,
            message=f"Policy '{policy_name}' enabled",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_name}' not found")
    except Exception as e:
        logger.error(
            "Failed to enable policy",
            policy_name=policy_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to enable policy")


@router.put("/{policy_name}/disable", response_model=MessageResponse)
async def disable_policy(policy_name: str) -> MessageResponse:
    """
    Disable a policy.

    Args:
        policy_name: Name of the policy

    Returns:
        MessageResponse confirming disablement

    Raises:
        HTTPException: If policy not found
    """
    try:
        registry = get_policy_registry()
        registry.disable_policy(policy_name)

        return MessageResponse(
            ok=True,
            message=f"Policy '{policy_name}' disabled",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_name}' not found")
    except Exception as e:
        logger.error(
            "Failed to disable policy",
            policy_name=policy_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to disable policy")


@router.post("/reload", response_model=MessageResponse)
async def reload_policies() -> MessageResponse:
    """
    Reload policies from configuration files.

    Returns:
        MessageResponse with reload status
    """
    try:
        initialize_policies()

        registry = get_policy_registry()
        policy_count = len(registry.get_all())

        return MessageResponse(
            ok=True,
            message=f"Policies reloaded successfully ({policy_count} policies)",
        )
    except Exception as e:
        logger.error("Failed to reload policies", exc_info=True, extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to reload policies")


@router.get("/severity/{severity}", response_model=PolicyListResponse)
async def get_policies_by_severity(severity: str) -> PolicyListResponse:
    """
    Get policies filtered by severity level.

    Args:
        severity: Severity level (info, warning, critical)

    Returns:
        PolicyListResponse with filtered policies

    Raises:
        HTTPException: If severity invalid
    """
    try:
        severity_enum = Severity(severity)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity: {severity}. Must be: info, warning, critical",
        )

    try:
        registry = get_policy_registry()
        policies = registry.get_by_severity(severity_enum)

        policies_dict = {p.name: p.to_dict() for p in policies}

        return PolicyListResponse(
            ok=True,
            policies={
                name: PolicyInfo(**info) for name, info in policies_dict.items()
            },
            total=len(policies_dict),
            enabled_count=sum(1 for p in policies if p.enabled),
        )
    except Exception as e:
        logger.error(
            "Failed to get policies by severity",
            severity=severity,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to get policies by severity")


@router.get("/runner/status", response_model=Dict[str, Any])
async def get_policy_runner_status() -> Dict[str, Any]:
    """
    Get the status of the policy runner.

    Returns:
        Status information including enabled state, running state, and configuration

    Example response:
        ```json
        {
            "ok": true,
            "runner": {
                "enabled": true,
                "running": true,
                "interval_seconds": 30,
                "batch_size": 100
            }
        }
        ```
    """
    try:
        try:
            from app.core.policy_runner import get_policy_runner_status
            status = get_policy_runner_status()
            return {"ok": True, "runner": status}
        except ImportError:
            return {
                "ok": True,
                "runner": {
                    "enabled": False,
                    "running": False,
                    "message": "Policy runner not available"
                }
            }
    except Exception as e:
        logger.error(
            "Failed to get policy runner status",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to get runner status")