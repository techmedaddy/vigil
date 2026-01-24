"""Background tasks for agent checks and GitOps daemon with graceful shutdown."""

import asyncio
from typing import Optional, List
from datetime import datetime
import random

from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.db import get_db

logger = get_logger(__name__)
settings = get_settings()

# Global task handles for lifecycle management
_background_tasks: List[asyncio.Task] = []


# --- Agent Loop ---

async def start_agent_loop() -> asyncio.Task:
    """Start the periodic agent check loop for metrics and anomaly detection."""
    async def agent_check():
        logger.info(f"Agent loop starting with {settings.AGENT_INTERVAL}s interval")

        while True:
            try:
                await asyncio.sleep(settings.AGENT_INTERVAL)

                logger.debug("Agent check running")

                # Get database session
                try:
                    from app.core.db import get_db_manager
                    db_manager = get_db_manager()

                    async with db_manager.get_session_context() as session:
                        # Import Metric model
                        from app.core.db import Metric
                        from sqlalchemy import select, desc
                        from datetime import timedelta

                        # Query recent metrics (last 5 minutes)
                        cutoff_time = datetime.utcnow() - timedelta(minutes=5)
                        query = (
                            select(Metric)
                            .where(Metric.timestamp >= cutoff_time)
                            .order_by(desc(Metric.timestamp))
                            .limit(100)
                        )

                        result = await session.execute(query)
                        metrics = result.scalars().all()

                        if not metrics:
                            logger.debug("No recent metrics found")
                            continue

                        # Analyze metrics for anomalies
                        anomalies = _detect_anomalies(metrics)

                        if anomalies:
                            logger.warning(f"Anomalies detected: {len(anomalies)} found")

                            # Log anomaly events for potential remediation
                            for anomaly in anomalies:
                                logger.info(
                                    f"Anomaly detected: {anomaly['name']}={anomaly['value']} "
                                    f"(threshold={anomaly['threshold']}, severity={anomaly['severity']})"
                                )
                        else:
                            logger.debug(f"Agent check complete: {len(metrics)} metrics, status=healthy")

                except Exception as db_error:
                    logger.error(f"Agent check database error: {db_error}", exc_info=True)
                    continue

            except asyncio.CancelledError:
                logger.info("Agent loop cancelled, shutting down")
                break
            except Exception as e:
                logger.error(f"Agent loop error: {e}", exc_info=True)
                # Continue after error
                await asyncio.sleep(5)

    # Create and return task
    task = asyncio.create_task(agent_check())
    _background_tasks.append(task)
    return task


# --- GitOps Daemon Loop ---

async def start_gitopsd_loop() -> asyncio.Task:
    """Start the GitOps daemon loop for manifest drift detection."""
    async def gitopsd_sync():
        logger.info(f"GitOpsD loop starting with {settings.GITOPSD_INTERVAL}s interval")

        while True:
            try:
                await asyncio.sleep(settings.GITOPSD_INTERVAL)

                logger.debug("GitOpsD sync running")

                # Simulate manifest reconciliation
                drift_events = _reconcile_manifests()

                if drift_events:
                    logger.warning(f"Drift detected: {len(drift_events)} events")

                    # Log individual drift events
                    for event in drift_events:
                        try:
                            from app.core.db import get_db_manager, Action
                            from datetime import datetime

                            db_manager = get_db_manager()
                            async with db_manager.get_session_context() as session:
                                # Record drift action
                                drift_action = Action(
                                    target=event["resource_name"],
                                    action="reconcile",
                                    status="pending",
                                    details=f"Drift detected: {event['resource_kind']} "
                                           f"desired={event['desired_state']} "
                                           f"actual={event['actual_state']}",
                                )
                                session.add(drift_action)
                                await session.commit()

                                logger.info(
                                    f"Drift reconciliation action queued: {event['resource_kind']}/{event['resource_name']} (id={drift_action.id})"
                                )
                        except Exception as db_error:
                            logger.error(f"Failed to record drift action: {db_error}", exc_info=True)
                else:
                    logger.debug("GitOpsD sync complete, no drift detected")

            except asyncio.CancelledError:
                logger.info("GitOpsD loop cancelled, shutting down")
                break
            except Exception as e:
                logger.error(f"GitOpsD loop error: {e}", exc_info=True)
                # Continue after error
                await asyncio.sleep(5)

    # Create and return task
    task = asyncio.create_task(gitopsd_sync())
    _background_tasks.append(task)
    return task


# --- Anomaly Detection ---

def _detect_anomalies(metrics: list) -> list:
    """Detect anomalies in metrics based on thresholds."""
    anomalies = []

    # Define thresholds for common metrics
    thresholds = {
        "cpu_usage": {"threshold": 0.85, "severity": "warning"},
        "memory_usage": {"threshold": 0.90, "severity": "warning"},
        "disk_usage": {"threshold": 0.95, "severity": "critical"},
        "request_latency_ms": {"threshold": 5000, "severity": "warning"},
        "error_rate": {"threshold": 0.05, "severity": "critical"},
    }

    for metric in metrics:
        if metric.name in thresholds:
            threshold_config = thresholds[metric.name]
            threshold_value = threshold_config["threshold"]

            # Check if metric exceeds threshold
            if metric.value > threshold_value:
                anomalies.append({
                    "name": metric.name,
                    "value": metric.value,
                    "threshold": threshold_value,
                    "severity": threshold_config["severity"],
                    "timestamp": metric.timestamp,
                })

    return anomalies


# --- Manifest Reconciliation ---

def _reconcile_manifests() -> list:
    """Reconcile manifests with live state and detect drift (placeholder)."""
    drift_events = []

    # Placeholder: Simulate drift detection
    # In production, this would:
    # 1. Read manifests from CONFIG_PATH
    # 2. Query live state (Kubernetes, cloud provider, etc.)
    # 3. Compare and report differences

    if random.random() < 0.1:  # 10% chance of detecting drift
        drift_events.append({
            "resource_kind": "Deployment",
            "resource_name": "web-service",
            "desired_state": "3 replicas",
            "actual_state": "2 replicas",
        })

    return drift_events


# --- Queue History Recording ---

async def start_queue_history_loop() -> asyncio.Task:
    """Start the periodic queue history recording loop."""
    async def _queue_history_loop():
        logger.info("Queue history loop starting with 5s interval")

        while True:
            try:
                await asyncio.sleep(5)  # Record every 5 seconds

                try:
                    from app.core.queue import record_queue_history as do_record
                    do_record()
                    logger.debug("Queue history sample recorded")
                except Exception as e:
                    logger.debug(f"Queue history recording failed: {e}")

            except asyncio.CancelledError:
                logger.info("Queue history loop cancelled, shutting down")
                break
            except Exception as e:
                logger.error(f"Queue history loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    # Create and return task
    task = asyncio.create_task(_queue_history_loop())
    task.set_name("queue_history_loop")
    _background_tasks.append(task)
    return task


# --- Task Lifecycle Management ---

async def start_all_background_tasks() -> None:
    """Start all background tasks at application startup."""
    logger.info("Starting all background tasks")

    try:
        await start_agent_loop()
        logger.info("Agent loop started")
    except Exception as e:
        logger.error("Failed to start agent loop", exc_info=True, extra={"error": str(e)})

    try:
        await start_gitopsd_loop()
        logger.info("GitOpsD loop started")
    except Exception as e:
        logger.error("Failed to start GitOpsD loop", exc_info=True, extra={"error": str(e)})

    try:
        await start_queue_history_loop()
        logger.info("Queue history loop started")
    except Exception as e:
        logger.error("Failed to start queue history loop", exc_info=True, extra={"error": str(e)})

    logger.info("All background tasks started", extra={"active_tasks": len(_background_tasks)})


async def cancel_all_background_tasks() -> None:
    """Cancel all background tasks at application shutdown."""
    if not _background_tasks:
        logger.info("No background tasks to cancel")
        return

    logger.info("Cancelling background tasks", extra={"count": len(_background_tasks)})

    # Cancel all tasks
    for task in _background_tasks:
        if not task.done():
            task.cancel()

    # Wait for all tasks to complete (with timeout)
    try:
        await asyncio.wait_for(
            asyncio.gather(*_background_tasks, return_exceptions=True),
            timeout=10.0
        )
    except asyncio.TimeoutError:
        logger.warning("Background task cancellation timed out")

    logger.info("All background tasks cancelled")


async def get_background_task_status() -> dict:
    """Get status of all background tasks."""
    return {
        "total_tasks": len(_background_tasks),
        "running_tasks": sum(1 for t in _background_tasks if not t.done()),
        "completed_tasks": sum(1 for t in _background_tasks if t.done()),
        "tasks": [
            {
                "name": task.get_name(),
                "done": task.done(),
                "cancelled": task.cancelled(),
            }
            for task in _background_tasks
        ]
    }
