"""
Database integration examples and patterns for Vigil API.

Demonstrates how to use async SQLAlchemy sessions in FastAPI routes and services.
"""

from fastapi import FastAPI, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from python.app.core.db import (
    get_db,
    init_db,
    close_db,
    Metric,
    Action,
    Alert,
)
from python.app.core.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(title="Vigil API with Async Database")


# --- FastAPI Startup/Shutdown Events ---

@app.on_event("startup")
async def startup_event():
    """Initialize database at application startup."""
    logger.info("Application starting up...")
    await init_db()
    logger.info("Database initialized")


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connections at application shutdown."""
    logger.info("Application shutting down...")
    await close_db()
    logger.info("Database connections closed")


# --- Example Routes Using Database Dependency ---

@app.post("/ingest")
async def ingest_metric(payload: dict, db: AsyncSession = Depends(get_db)):
    """
    Ingest a metric and store it in the database.

    Args:
        payload: Metric payload with 'name' and 'value'
        db: AsyncSession dependency injected by FastAPI

    Returns:
        Acknowledgment with metric ID
    """
    try:
        metric = Metric(
            name=payload.get("name"),
            value=payload.get("value"),
            timestamp=datetime.utcnow()
        )
        db.add(metric)
        await db.flush()  # Get the ID without committing yet

        logger.info(f"Metric ingested", extra={
            "metric_id": metric.id,
            "metric_name": metric.name,
            "metric_value": metric.value
        })

        return {
            "status": "received",
            "metric_id": metric.id,
            "metric_name": metric.name
        }
    except Exception as e:
        logger.error(f"Failed to ingest metric: {e}", exc_info=True)
        raise


@app.get("/metrics/latest")
async def get_latest_metrics(limit: int = 30, db: AsyncSession = Depends(get_db)):
    """
    Retrieve the latest metrics from the database.

    Args:
        limit: Maximum number of metrics to return
        db: AsyncSession dependency

    Returns:
        List of recent metrics
    """
    try:
        # Build async query
        query = (
            select(Metric)
            .order_by(Metric.timestamp.desc())
            .limit(limit)
        )

        result = await db.execute(query)
        metrics = result.scalars().all()

        logger.info(f"Retrieved {len(metrics)} metrics")

        return {
            "count": len(metrics),
            "metrics": [
                {
                    "id": m.id,
                    "name": m.name,
                    "value": m.value,
                    "timestamp": m.timestamp.isoformat()
                }
                for m in metrics
            ]
        }
    except Exception as e:
        logger.error(f"Failed to retrieve metrics: {e}", exc_info=True)
        raise


@app.get("/metrics/by-name/{metric_name}")
async def get_metrics_by_name(
    metric_name: str,
    hours: int = 1,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve metrics by name for a given time period.

    Args:
        metric_name: Name of the metric
        hours: Number of hours to look back
        db: AsyncSession dependency

    Returns:
        Metrics matching the criteria
    """
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        query = (
            select(Metric)
            .where(Metric.name == metric_name)
            .where(Metric.timestamp >= cutoff_time)
            .order_by(Metric.timestamp.desc())
        )

        result = await db.execute(query)
        metrics = result.scalars().all()

        logger.info(f"Retrieved {len(metrics)} metrics for {metric_name}")

        return {
            "metric_name": metric_name,
            "hours": hours,
            "count": len(metrics),
            "metrics": [
                {
                    "value": m.value,
                    "timestamp": m.timestamp.isoformat()
                }
                for m in metrics
            ]
        }
    except Exception as e:
        logger.error(f"Failed to retrieve metrics by name: {e}", exc_info=True)
        raise


@app.post("/actions")
async def create_action(payload: dict, db: AsyncSession = Depends(get_db)):
    """
    Create a remediation action record.

    Args:
        payload: Action payload with 'target', 'action', 'status', 'details'
        db: AsyncSession dependency

    Returns:
        Created action with ID
    """
    try:
        action = Action(
            target=payload.get("target"),
            action=payload.get("action"),
            status=payload.get("status", "pending"),
            details=payload.get("details")
        )
        db.add(action)
        await db.flush()

        logger.warning(f"Action created", extra={
            "action_id": action.id,
            "target": action.target,
            "action": action.action
        })

        return {
            "id": action.id,
            "status": "created",
            "target": action.target,
            "action": action.action
        }
    except Exception as e:
        logger.error(f"Failed to create action: {e}", exc_info=True)
        raise


@app.get("/actions/pending")
async def get_pending_actions(db: AsyncSession = Depends(get_db)):
    """
    Retrieve all pending actions.

    Args:
        db: AsyncSession dependency

    Returns:
        List of pending actions
    """
    try:
        query = (
            select(Action)
            .where(Action.status == "pending")
            .order_by(Action.started_at.desc())
        )

        result = await db.execute(query)
        actions = result.scalars().all()

        logger.info(f"Retrieved {len(actions)} pending actions")

        return {
            "count": len(actions),
            "actions": [
                {
                    "id": a.id,
                    "target": a.target,
                    "action": a.action,
                    "started_at": a.started_at.isoformat()
                }
                for a in actions
            ]
        }
    except Exception as e:
        logger.error(f"Failed to retrieve pending actions: {e}", exc_info=True)
        raise


# --- Configuration Examples ---

"""
DATABASE_URL Environment Variables:

SQLite (Development):
    export DATABASE_URL="sqlite:///./vigil.db"
    (Automatically converted to sqlite+aiosqlite:///./vigil.db internally)

PostgreSQL (Production):
    export DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/vigil"

MySQL (Alternative):
    export DATABASE_URL="mysql+aiomysql://user:password@localhost:3306/vigil"
"""


# --- Migration Guide ---

"""
Migrating from Synchronous to Async SQLAlchemy:

OLD (Synchronous):
    def get_db():
        conn = sqlite3.connect(DB_PATH)
        return conn

    @app.get("/metrics")
    def get_metrics():
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM metrics").fetchall()
            return rows

NEW (Asynchronous):
    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        session = get_session_maker()
        try:
            yield session
            await session.commit()
        finally:
            await session.close()

    @app.get("/metrics")
    async def get_metrics(db: AsyncSession = Depends(get_db)):
        result = await db.execute(select(Metric))
        return result.scalars().all()
"""


# --- Service Class Example ---

class MetricsService:
    """Example service class using async database sessions."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_logger(__name__)

    async def get_cpu_metrics(self, hours: int = 1) -> list:
        """Get CPU metrics for the past N hours."""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)

        query = (
            select(Metric)
            .where(Metric.name == "cpu_usage")
            .where(Metric.timestamp >= cutoff_time)
            .order_by(Metric.timestamp.desc())
        )

        result = await self.db.execute(query)
        metrics = result.scalars().all()

        self.logger.info(f"Retrieved {len(metrics)} CPU metrics")
        return metrics

    async def calculate_average_cpu(self, hours: int = 1) -> float:
        """Calculate average CPU usage for the past N hours."""
        metrics = await self.get_cpu_metrics(hours)
        if not metrics:
            return 0.0

        total = sum(m.value for m in metrics)
        return total / len(metrics)


# --- Usage in Routes ---

@app.get("/metrics/cpu-average")
async def get_cpu_average(hours: int = 1, db: AsyncSession = Depends(get_db)):
    """
    Get average CPU usage for the past N hours.

    Args:
        hours: Number of hours to look back
        db: AsyncSession dependency

    Returns:
        Average CPU usage value
    """
    service = MetricsService(db)
    average = await service.calculate_average_cpu(hours)

    logger.info(f"Average CPU usage: {average:.2f}%")

    return {
        "hours": hours,
        "average_cpu": f"{average:.2f}%"
    }
