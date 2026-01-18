"""
Policy runner for Vigil monitoring system.

Continuously evaluates policies against current metrics and triggers remediation actions.
Provides:
- Periodic policy evaluation loop
- Metrics fetching from database
- Remediation action execution
- Audit logging of policy evaluation cycles
- Graceful startup/shutdown integration
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.policy import evaluate_policies, get_policy_registry
from app.core.db import get_db_manager, Metric, Action
from app.core.queue import enqueue_task

logger = get_logger(__name__)
settings = get_settings()


# --- Global Runner State ---

_policy_runner_task: Optional[asyncio.Task] = None


# --- Metrics Fetching ---

async def fetch_recent_metrics(
    minutes: int = 5,
    batch_size: int = 100,
) -> Dict[str, Any]:
    """
    Fetch recent metrics from database for policy evaluation.

    Args:
        minutes: Number of minutes to look back
        batch_size: Maximum number of metrics to fetch

    Returns:
        Dictionary mapping metric names to their latest values
    """
    try:
        db_manager = get_db_manager()
        
        async with db_manager.get_session_context() as session:
            from sqlalchemy import select, desc, func
            
            # Calculate cutoff time
            cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
            
            # Query recent metrics
            query = (
                select(Metric)
                .where(Metric.timestamp >= cutoff_time)
                .order_by(desc(Metric.timestamp))
                .limit(batch_size)
            )
            
            result = await session.execute(query)
            metrics_list = result.scalars().all()
            
            if not metrics_list:
                logger.debug("No recent metrics found for policy evaluation")
                return {}
            
            # Build metrics dictionary, keeping latest values for each metric name
            metrics_dict: Dict[str, Any] = {}
            seen_names = set()
            
            for metric in metrics_list:
                if metric.name not in seen_names:
                    metrics_dict[metric.name] = metric.value
                    seen_names.add(metric.name)
            
            logger.debug(
                "Fetched recent metrics",
                metric_count=len(metrics_dict),
                lookback_minutes=minutes,
                batch_size=batch_size,
            )
            
            return metrics_dict
            
    except Exception as e:
        logger.error(
            "Failed to fetch recent metrics",
            error=str(e),
            exc_info=True,
        )
        return {}


# --- Action Execution ---

async def execute_remediation_action(
    target: str,
    action_type: str,
    params: Dict[str, Any],
    policy_name: str,
) -> bool:
    """
    Execute a remediation action by storing it in the database and enqueuing it.

    Args:
        target: Target resource identifier
        action_type: Type of action to execute
        params: Action parameters
        policy_name: Name of policy that triggered the action

    Returns:
        True if action was successfully recorded and enqueued, False otherwise
    """
    try:
        db_manager = get_db_manager()
        
        async with db_manager.get_session_context() as session:
            # Create action record
            action = Action(
                target=target,
                action=action_type,
                status="queued",  # Changed from "pending" to "queued"
                details=json.dumps({
                    "policy_name": policy_name,
                    "params": params,
                    "triggered_at": datetime.utcnow().isoformat(),
                }),
            )
            
            session.add(action)
            await session.flush()
            
            action_id = action.id
            
            logger.info(
                "Remediation action recorded",
                extra={
                    "action_id": action_id,
                    "target": target,
                    "action_type": action_type,
                    "policy_name": policy_name,
                }
            )
            
            # Enqueue task for worker to process
            task_payload = {
                "action_id": str(action_id),
                "target": target,
                "action": action_type,
                "severity": params.get("severity", "medium"),
                "timestamp": datetime.utcnow().isoformat(),
                "policy_id": policy_name,
                "alert_id": params.get("alert_id"),
                "request_id": f"policy_{policy_name}_{action_id}",
            }
            
            try:
                enqueue_task(task_payload)
                logger.info(
                    "Task enqueued for action",
                    extra={
                        "action_id": action_id,
                        "target": target,
                        "action_type": action_type,
                    }
                )
            except Exception as e:
                logger.error(
                    "Failed to enqueue task",
                    extra={
                        "action_id": action_id,
                        "target": target,
                        "action_type": action_type,
                        "error": str(e),
                    }
                )
                # Update action status to failed
                action.status = "failed"
                await session.flush()
                return False
            
            return True
            
    except Exception as e:
        logger.error(
            "Failed to execute remediation action",
            extra={
                "target": target,
                "action_type": action_type,
                "policy_name": policy_name,
                "error": str(e),
            },
            exc_info=True,
        )
        return False


# --- Policy Evaluation Cycle ---

async def run_single_policy_check() -> Dict[str, Any]:
    """
    Run a single policy evaluation cycle.

    Returns:
        Dictionary with evaluation results:
        - violations: Number of violations detected
        - actions_triggered: Number of actions executed
        - errors: Number of errors encountered
        - timestamp: Evaluation timestamp
    """
    cycle_start = datetime.utcnow()
    
    logger.debug("Policy evaluation cycle starting")
    
    results = {
        "violations": 0,
        "actions_triggered": 0,
        "errors": 0,
        "timestamp": cycle_start.isoformat(),
    }
    
    try:
        # Fetch recent metrics
        metrics = await fetch_recent_metrics(
            minutes=5,
            batch_size=getattr(settings, "POLICY_RUNNER_BATCH_SIZE", 100),
        )
        
        if not metrics:
            logger.warning("No metrics available for policy evaluation")
            results["errors"] += 1
            return results
        
        # Evaluate policies
        eval_result = await evaluate_policies(metrics)
        
        violations = eval_result.get("violations", [])
        actions_triggered = eval_result.get("actions_triggered", [])
        
        results["violations"] = len(violations)
        results["actions_triggered"] = len(actions_triggered)
        
        # Log violations
        if violations:
            logger.warning(
                "Policy violations detected",
                violation_count=len(violations),
            )
            
            for violation in violations:
                logger.warning(
                    "Policy violation audit log",
                    policy_name=violation.get("policy_name"),
                    severity=violation.get("severity"),
                    target=violation.get("target"),
                    description=violation.get("description"),
                )
        
        # Log triggered actions
        if actions_triggered:
            logger.info(
                "Remediation actions triggered",
                action_count=len(actions_triggered),
            )
            
            for action in actions_triggered:
                success = await execute_remediation_action(
                    target=action.get("target", "unknown"),
                    action_type=action.get("action", "custom"),
                    params=action.get("params", {}),
                    policy_name="",  # Policy name would be in context
                )
                
                if not success:
                    results["errors"] += 1
        
        # Calculate cycle duration
        cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
        
        logger.info(
            "Policy evaluation cycle completed",
            duration_seconds=round(cycle_duration, 3),
            metrics_evaluated=len(metrics),
            violations=results["violations"],
            actions_triggered=results["actions_triggered"],
            errors=results["errors"],
        )
        
    except Exception as e:
        logger.error(
            "Policy evaluation cycle failed",
            error=str(e),
            exc_info=True,
        )
        results["errors"] += 1
    
    return results


# --- Policy Runner Loop ---

async def run_policy_checks() -> None:
    """
    Run the continuous policy evaluation loop.

    This async function:
    - Runs on a configurable interval (POLICY_RUNNER_INTERVAL)
    - Fetches recent metrics from the database
    - Evaluates all enabled policies
    - Logs violations and triggered actions
    - Triggers remediation actions
    - Provides audit trail of all evaluations
    - Handles graceful shutdown via CancelledError

    The loop logs a summary after each evaluation cycle with:
    - Number of metrics evaluated
    - Number of violations detected
    - Number of actions triggered
    - Cycle execution time
    """
    
    logger.info(
        "Policy runner starting",
        interval_seconds=getattr(settings, "POLICY_RUNNER_INTERVAL", 30.0),
        enabled=getattr(settings, "POLICY_RUNNER_ENABLED", True),
    )
    
    iteration = 0
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    try:
        while True:
            try:
                # Wait for interval
                await asyncio.sleep(getattr(settings, "POLICY_RUNNER_INTERVAL", 30.0))
                
                iteration += 1
                
                logger.debug(
                    "Policy evaluation iteration starting",
                    iteration_number=iteration,
                )
                
                # Run policy check
                result = await run_single_policy_check()
                
                # Reset error counter on successful cycle
                if result.get("errors", 0) == 0:
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                
                # Check for excessive errors
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        "Policy runner exceeded maximum consecutive errors, pausing",
                        consecutive_errors=consecutive_errors,
                        max_errors=max_consecutive_errors,
                    )
                    # Wait longer before retrying
                    await asyncio.sleep(300)  # 5 minutes
                    consecutive_errors = 0
                
            except asyncio.CancelledError:
                logger.info(
                    "Policy runner cancelled, shutting down gracefully",
                    iterations_completed=iteration,
                )
                break
                
            except Exception as e:
                logger.error(
                    "Policy evaluation iteration failed",
                    iteration_number=iteration,
                    error=str(e),
                    exc_info=True,
                )
                consecutive_errors += 1
                
                # Add small delay before retry to avoid tight loop
                await asyncio.sleep(5)
    
    finally:
        logger.info(
            "Policy runner shutdown complete",
            iterations_completed=iteration,
        )


# --- Lifecycle Management ---

async def start_policy_runner() -> Optional[asyncio.Task]:
    """
    Start the policy runner background task.

    Returns:
        asyncio.Task handle or None if runner is disabled
    """
    global _policy_runner_task
    
    if not getattr(settings, "POLICY_RUNNER_ENABLED", True):
        logger.info("Policy runner is disabled, skipping startup")
        return None
    
    try:
        # Check that policy registry is initialized
        registry = get_policy_registry()
        policy_count = len(registry.get_all())
        
        logger.info(
            "Policy runner startup",
            policies_loaded=policy_count,
            enabled_policies=len(registry.get_enabled()),
        )
        
        # Create and start task
        _policy_runner_task = asyncio.create_task(run_policy_checks())
        
        return _policy_runner_task
        
    except Exception as e:
        logger.error(
            "Failed to start policy runner",
            error=str(e),
            exc_info=True,
        )
        return None


async def stop_policy_runner() -> None:
    """
    Stop the policy runner background task gracefully.

    Cancels the task and waits for it to finish.
    """
    global _policy_runner_task
    
    if _policy_runner_task is None:
        logger.debug("Policy runner task not running")
        return
    
    try:
        logger.info("Policy runner shutdown initiated")
        
        # Cancel the task
        _policy_runner_task.cancel()
        
        try:
            # Wait for task to finish
            await _policy_runner_task
        except asyncio.CancelledError:
            # Expected when task is cancelled
            pass
        
        logger.info("Policy runner shutdown complete")
        _policy_runner_task = None
        
    except Exception as e:
        logger.error(
            "Error during policy runner shutdown",
            error=str(e),
            exc_info=True,
        )


def get_policy_runner_status() -> Dict[str, Any]:
    """
    Get current status of the policy runner.

    Returns:
        Dictionary with runner status information
    """
    global _policy_runner_task
    
    is_running = (
        _policy_runner_task is not None and
        not _policy_runner_task.done()
    )
    
    return {
        "enabled": getattr(settings, "POLICY_RUNNER_ENABLED", True),
        "running": is_running,
        "interval_seconds": getattr(settings, "POLICY_RUNNER_INTERVAL", 30.0),
        "batch_size": getattr(settings, "POLICY_RUNNER_BATCH_SIZE", 100),
    }
