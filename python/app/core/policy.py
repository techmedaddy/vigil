"""Policy engine for automated remediation based on metric conditions."""

import asyncio
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any, Union

import yaml

from app.core.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


# --- Enums ---

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ActionType(str, Enum):
    SCALE_UP = "scale-up"
    SCALE_DOWN = "scale-down"
    RESTART_SERVICE = "restart-service"
    DRAIN_POD = "drain-pod"
    REBALANCE = "rebalance"
    SNAPSHOT = "snapshot"
    CUSTOM = "custom"


# --- Type Aliases ---

Condition = Callable[[Dict[str, Any]], bool]
ActionFunction = Callable[[str, Dict[str, Any]], Any]


# --- Condition Functions (Built-in Conditions) ---

def metric_exceeds(metric_name: str, threshold: float) -> Condition:
    """Return condition checking if metric_name > threshold."""
    def check(metrics: Dict[str, Any]) -> bool:
        value = metrics.get(metric_name, 0)
        return float(value) > threshold
    return check


def metric_below(metric_name: str, threshold: float) -> Condition:
    """Return condition checking if metric_name < threshold."""
    def check(metrics: Dict[str, Any]) -> bool:
        value = metrics.get(metric_name, float('inf'))
        return float(value) < threshold
    return check


def all_conditions(*conditions: Condition) -> Condition:
    """Combine conditions with AND logic."""
    def check(metrics: Dict[str, Any]) -> bool:
        return all(condition(metrics) for condition in conditions)
    return check


def any_condition(*conditions: Condition) -> Condition:
    """Combine conditions with OR logic."""
    def check(metrics: Dict[str, Any]) -> bool:
        return any(condition(metrics) for condition in conditions)
    return check


def custom_condition(func: Callable) -> Condition:
    """Wrap a custom callable as a condition with error handling."""
    def check(metrics: Dict[str, Any]) -> bool:
        try:
            return bool(func(metrics))
        except Exception as e:
            logger.error(
                "Custom condition evaluation failed",
                exc_info=True,
                extra={
                    "error": str(e),
                }
            )
            return False
    return check


# --- Action Functions (Built-in Actions) ---

async def scale_up_action(target: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute scale-up action on target resource."""
    logger.info(
        "Scaling up resource",
        extra={
            "target": target,
            "params": params,
        }
    )
    return {
        "action": "scale-up",
        "target": target,
        "status": "success",
        "params": params,
    }


async def restart_action(target: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute restart action on target service."""
    logger.info(
        "Restarting service",
        extra={
            "target": target,
            "params": params,
        }
    )
    return {
        "action": "restart",
        "target": target,
        "status": "success",
        "params": params,
    }


async def drain_pod_action(target: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute drain action on Kubernetes pod."""
    logger.info(
        "Draining pod",
        extra={
            "target": target,
            "params": params,
        }
    )
    return {
        "action": "drain-pod",
        "target": target,
        "status": "success",
        "params": params,
    }


# --- Policy Class ---

@dataclass
class Policy:
    """Policy definition for automated remediation with conditions and actions."""

    name: str
    condition: Condition
    action: Union[ActionType, str, ActionFunction]
    severity: Severity = Severity.WARNING
    description: str = ""
    target: str = "all"
    enabled: bool = True
    params: Dict[str, Any] = field(default_factory=dict)
    auto_remediate: bool = True

    def evaluate(self, metrics: Dict[str, Any]) -> bool:
        """Evaluate policy condition against metrics. Returns True if triggered."""
        if not self.enabled:
            return False

        try:
            return self.condition(metrics)
        except Exception as e:
            logger.error(
                "Policy evaluation failed",
                exc_info=True,
                extra={
                    "policy_name": self.name,
                    "error": str(e),
                }
            )
            return False

    def matches_target(self, resource_name: str) -> bool:
        """Check if policy target pattern matches resource_name (supports wildcards)."""
        if self.target == "all" or self.target == "*":
            return True

        # Simple wildcard matching
        if "*" in self.target:
            import fnmatch
            return fnmatch.fnmatch(resource_name, self.target)

        return self.target == resource_name

    def to_dict(self) -> Dict[str, Any]:
        """Convert policy to dictionary (excludes callable fields)."""
        return {
            "name": self.name,
            "description": self.description,
            "severity": self.severity.value,
            "target": self.target,
            "enabled": self.enabled,
            "params": self.params,
            "auto_remediate": self.auto_remediate,
        }


# --- Policy Registry ---

class PolicyRegistry:
    """Registry for managing and looking up policies."""

    def __init__(self):
        self._policies: Dict[str, Policy] = {}

    def register(self, policy: Policy) -> None:
        """Register a policy. Raises ValueError if name already exists."""
        if policy.name in self._policies:
            raise ValueError(f"Policy '{policy.name}' already registered")

        self._policies[policy.name] = policy
        logger.info(
            "Policy registered",
            extra={
                "policy_name": policy.name,
                "severity": policy.severity.value,
                "enabled": policy.enabled,
            }
        )

    def unregister(self, policy_name: str) -> None:
        """Unregister a policy. Raises KeyError if not found."""
        if policy_name not in self._policies:
            raise KeyError(f"Policy '{policy_name}' not found")

        del self._policies[policy_name]
        logger.info("Policy unregistered", extra={"policy_name": policy_name})

    def get(self, policy_name: str) -> Optional[Policy]:
        """Get policy by name, or None if not found."""
        return self._policies.get(policy_name)

    def get_all(self) -> List[Policy]:
        """Get all registered policies."""
        return list(self._policies.values())

    def get_enabled(self) -> List[Policy]:
        """Get all enabled policies."""
        return [p for p in self._policies.values() if p.enabled]

    def get_by_severity(self, severity: Severity) -> List[Policy]:
        """Get policies matching the given severity level."""
        return [p for p in self._policies.values() if p.severity == severity]

    def list_policies(self) -> Dict[str, Dict[str, Any]]:
        """Get summary dict of all policies."""
        return {name: policy.to_dict() for name, policy in self._policies.items()}

    def enable_policy(self, policy_name: str) -> None:
        """Enable a policy. Raises KeyError if not found."""
        policy = self.get(policy_name)
        if not policy:
            raise KeyError(f"Policy '{policy_name}' not found")

        policy.enabled = True
        logger.info("Policy enabled", extra={"policy_name": policy_name})

    def disable_policy(self, policy_name: str) -> None:
        """Disable a policy. Raises KeyError if not found."""
        policy = self.get(policy_name)
        if not policy:
            raise KeyError(f"Policy '{policy_name}' not found")

        policy.enabled = False
        logger.info("Policy disabled", extra={"policy_name": policy_name})


# --- Global Registry Instance ---

_registry: Optional[PolicyRegistry] = None


def get_policy_registry() -> PolicyRegistry:
    """Get the global policy registry singleton."""
    global _registry
    if _registry is None:
        _registry = PolicyRegistry()
    return _registry


# --- Policy Evaluation ---

async def evaluate_policies(
    metrics: Dict[str, Any],
    target: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate enabled policies against metrics. Returns violations and triggered actions."""
    registry = get_policy_registry()
    violations = []
    actions_triggered = []

    logger.debug(
        "Evaluating policies",
        extra={
            "metrics_count": len(metrics),
            "target": target,
        }
    )

    for policy in registry.get_enabled():
        # Check if policy applies to target
        if target and not policy.matches_target(target):
            continue

        # Evaluate condition
        if policy.evaluate(metrics):
            violation = {
                "policy_name": policy.name,
                "severity": policy.severity.value,
                "description": policy.description,
                "target": target or "all",
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
            violations.append(violation)

            logger.warning(
                "Policy violation detected",
                extra={
                    "policy_name": policy.name,
                    "severity": policy.severity.value,
                    "target": target or "all",
                }
            )

            # Trigger remediation if enabled
            if policy.auto_remediate:
                try:
                    action_result = await _execute_action(
                        policy=policy,
                        target=target or policy.target,
                        metrics=metrics,
                    )
                    actions_triggered.append(action_result)
                except Exception as e:
                    logger.error(
                        "Failed to execute remediation action",
                        exc_info=True,
                        extra={
                            "policy_name": policy.name,
                            "error": str(e),
                        }
                    )

    return {
        "violations": violations,
        "actions_triggered": actions_triggered,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


async def _execute_action(
    policy: Policy,
    target: str,
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute remediation action for a policy violation."""
    action = policy.action
    params = {**policy.params, "metrics": metrics}

    logger.info(
        "Executing remediation action",
        extra={
            "policy_name": policy.name,
            "action": str(action),
            "target": target,
            "params": params,
        }
    )

    # Execute action based on type
    if callable(action):
        # Custom action function
        result = await action(target, params) if asyncio.iscoroutinefunction(action) else action(target, params)
    elif isinstance(action, ActionType):
        # Built-in action
        result = await _execute_builtin_action(action, target, params)
    else:
        # String action type
        result = await _execute_builtin_action(ActionType.CUSTOM, target, params)

    # Audit log
    logger.info(
        "Action audit",
        extra={
            "policy_name": policy.name,
            "action": str(action),
            "target": target,
            "result_status": result.get("status"),
        }
    )

    return result


async def _execute_builtin_action(
    action_type: ActionType,
    target: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute a built-in remediation action by type."""
    if action_type == ActionType.SCALE_UP:
        return await scale_up_action(target, params)
    elif action_type == ActionType.RESTART_SERVICE:
        return await restart_action(target, params)
    elif action_type == ActionType.DRAIN_POD:
        return await drain_pod_action(target, params)
    else:
        logger.warning(
            "Unknown action type",
            extra={
                "action_type": action_type.value,
                "target": target,
            }
        )
        return {
            "action": action_type.value,
            "target": target,
            "status": "unknown_action",
        }


# --- Policy Loading ---

def load_policies_from_yaml(file_path: str) -> List[Policy]:
    """
    Load policies from YAML file.

    Args:
        file_path: Path to YAML file

    Returns:
        List of loaded policies

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Policy file not found: {file_path}")

    with open(file_path, "r") as f:
        config = yaml.safe_load(f) or {}

    policies = []
    policy_configs = config.get("policies", [])

    for policy_config in policy_configs:
        try:
            policy = _policy_from_config(policy_config)
            policies.append(policy)
            logger.info(
                "Policy loaded from YAML",
                extra={
                    "policy_name": policy.name,
                    "file": file_path,
                }
            )
        except Exception as e:
            logger.error(
                "Failed to load policy from YAML",
                exc_info=True,
                extra={
                    "policy_config": policy_config,
                    "error": str(e),
                }
            )

    return policies


def load_policies_from_json(file_path: str) -> List[Policy]:
    """
    Load policies from JSON file.

    Args:
        file_path: Path to JSON file

    Returns:
        List of loaded policies

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Policy file not found: {file_path}")

    with open(file_path, "r") as f:
        config = json.load(f)

    policies = []
    policy_configs = config.get("policies", [])

    for policy_config in policy_configs:
        try:
            policy = _policy_from_config(policy_config)
            policies.append(policy)
            logger.info(
                "Policy loaded from JSON",
                extra={
                    "policy_name": policy.name,
                    "file": file_path,
                }
            )
        except Exception as e:
            logger.error(
                "Failed to load policy from JSON",
                exc_info=True,
                extra={
                    "policy_config": policy_config,
                    "error": str(e),
                }
            )

    return policies


def _policy_from_config(config: Dict[str, Any]) -> Policy:
    """Create a Policy instance from configuration dictionary."""
    name = config.get("name")
    if not name:
        raise ValueError("Policy must have a 'name'")

    # Build condition from config
    condition_config = config.get("condition", {})
    condition = _build_condition(condition_config)

    # Get action
    action = config.get("action", "custom")
    if isinstance(action, str):
        try:
            action = ActionType(action)
        except ValueError:
            # Keep as string for custom action
            pass

    # Get severity
    severity_str = config.get("severity", "warning")
    try:
        severity = Severity(severity_str)
    except ValueError:
        logger.warning(
            "Invalid severity, using default",
            extra={
                "severity": severity_str,
                "policy_name": name,
            }
        )
        severity = Severity.WARNING

    # Create policy
    policy = Policy(
        name=name,
        description=config.get("description", ""),
        condition=condition,
        action=action,
        severity=severity,
        target=config.get("target", "all"),
        enabled=config.get("enabled", True),
        params=config.get("params", {}),
        auto_remediate=config.get("auto_remediate", True),
    )

    return policy


def _build_condition(config: Dict[str, Any]) -> Condition:
    """Build a condition function from configuration dict."""
    condition_type = config.get("type", "custom")

    if condition_type == "metric_exceeds":
        metric = config.get("metric")
        threshold = config.get("threshold")
        if not metric or threshold is None:
            raise ValueError("metric_exceeds requires 'metric' and 'threshold'")
        return metric_exceeds(metric, threshold)

    elif condition_type == "metric_below":
        metric = config.get("metric")
        threshold = config.get("threshold")
        if not metric or threshold is None:
            raise ValueError("metric_below requires 'metric' and 'threshold'")
        return metric_below(metric, threshold)

    elif condition_type == "all":
        conditions_list = [
            _build_condition(c) for c in config.get("conditions", [])
        ]
        return all_conditions(*conditions_list)

    elif condition_type == "any":
        conditions_list = [
            _build_condition(c) for c in config.get("conditions", [])
        ]
        return any_condition(*conditions_list)

    else:
        # Default to true condition
        logger.warning(
            "Unknown condition type, using default",
            extra={
                "condition_type": condition_type,
            }
        )
        return lambda metrics: True


def load_policies_from_config() -> List[Policy]:
    """Load policies from CONFIG_PATH, configs/policies.yaml, or configs/policies.json."""
    policies = []
    config_path = getattr(settings, "CONFIG_PATH", "configs/collector.yaml")

    # Try to load from main config path
    if os.path.exists(config_path):
        try:
            config = yaml.safe_load(open(config_path))
            if config and "policies" in config:
                for policy_config in config.get("policies", []):
                    policy = _policy_from_config(policy_config)
                    policies.append(policy)
                    logger.info(
                        "Policy loaded from config file",
                        extra={
                            "policy_name": policy.name,
                        }
                    )
        except Exception as e:
            logger.warning(
                "Failed to load policies from config file",
                extra={
                    "config_path": config_path,
                    "error": str(e),
                }
            )

    # Try to load from policies.yaml
    policies_yaml = "configs/policies.yaml"
    if os.path.exists(policies_yaml):
        try:
            policies.extend(load_policies_from_yaml(policies_yaml))
        except Exception as e:
            logger.warning(
                "Failed to load policies from YAML",
                extra={
                    "path": policies_yaml,
                    "error": str(e),
                }
            )

    # Try to load from policies.json
    policies_json = "configs/policies.json"
    if os.path.exists(policies_json):
        try:
            policies.extend(load_policies_from_json(policies_json))
        except Exception as e:
            logger.warning(
                "Failed to load policies from JSON",
                extra={
                    "path": policies_json,
                    "error": str(e),
                }
            )

    return policies


def initialize_policies() -> None:
    """Initialize policy registry with policies from configuration."""
    registry = get_policy_registry()

    try:
        policies = load_policies_from_config()
        for policy in policies:
            registry.register(policy)

        logger.info(
            "Policy engine initialized",
            extra={"policies_loaded": len(policies)}
        )
    except Exception as e:
        logger.error(
            "Failed to initialize policies",
            extra={"error": str(e)},
            exc_info=True,
        )
