"""Database connection and session management using SQLAlchemy async."""










































































































































































































































































































































































































































































































































































































        return False        logger.error(f"Failed to update action {action_id}: {e}", exc_info=True)    except Exception as e:            return action is not None            )                error_message=error_message                details=details,                new_status=new_status,                action_id=action_id,                db=db,            action = await ActionService.update_action_status(        async with db_manager.get_session_context() as db:        db_manager = get_db_manager()                new_status = ActionStatus(status)    try:    """        True if successful, False otherwise    Returns:                details: Optional details update        error_message: Optional error message for failures        status: New status (pending, running, completed, failed, cancelled)        action_id: ID of action to update    Args:        Update an action's status (convenience function for external callers).    """) -> bool:    details: Optional[str] = None    error_message: Optional[str] = None,    status: str,    action_id: int,async def update_action(        return None        logger.error(f"Failed to record action: {e}", exc_info=True)    except Exception as e:            return action.id            )                details=details                action_type=action_type,                target=target,                db=db,            action = await ActionService.create_action(        async with db_manager.get_session_context() as db:        db_manager = get_db_manager()    try:    """        Action ID if successful, None otherwise    Returns:                details: Optional details        action_type: Type of action        target: Target resource identifier    Args:        Creates a new action in pending status.        Record a new action (convenience function for external callers).    """) -> Optional[int]:    details: Optional[str] = None    action_type: str,    target: str,async def record_action(# Convenience functions for external use            raise            logger.error(f"Failed to update action {action_id}: {e}", exc_info=True)        except SQLAlchemyError as e:                        return action                        )                }                    "new_status": new_status.value                    "action_id": action_id,                extra={                f"Action status updated to {new_status.value}",            logger.info(                        await db.flush()                            action.completed_at = datetime.utcnow()            if new_status in terminal_statuses:            ]                ActionStatus.CANCELLED                ActionStatus.FAILED,                ActionStatus.COMPLETED,            terminal_statuses = [            # Set completed_at for terminal states                            action.error_message = error_message            if error_message:                            action.details = details            if details:                        action.status = new_status.value                            return None            if action is None:                        action = result.scalar_one_or_none()            )                select(Action).where(Action.id == action_id)            result = await db.execute(        try:        """            Updated Action instance or None if not found        Returns:                        error_message: Optional error message (for failed status)            details: Optional details to update            new_status: New status to set            action_id: ID of the action to update            db: Database session        Args:                Generic method to update action status.        """    ) -> Optional[Action]:        error_message: Optional[str] = None        details: Optional[str] = None,        new_status: ActionStatus,        action_id: int,        db: AsyncSession,    async def update_action_status(    @staticmethod                raise            logger.error(f"Failed to list actions: {e}", exc_info=True)        except SQLAlchemyError as e:                        return list(actions), total                        actions = result.scalars().all()            result = await db.execute(query)                        query = query.limit(limit).offset(offset)                            query = query.where(and_(*conditions))            if conditions:            query = select(Action).order_by(Action.started_at.desc())            # Get paginated results                        total = count_result.scalar() or 0            count_result = await db.execute(count_query)                            count_query = count_query.where(and_(*conditions))            if conditions:            count_query = select(func.count(Action.id))            from sqlalchemy import func            # Get total count                            conditions.append(Action.started_at <= end_time)            if end_time:                            conditions.append(Action.started_at >= start_time)            if start_time:                            conditions.append(Action.target == target)            if target:                            conditions.append(Action.status == status)            if status:                        conditions = []            # Build base query        try:        """            Tuple of (list of actions, total count)        Returns:                        offset: Offset for pagination (default: 0)            limit: Maximum number of results (default: 50)            end_time: Optional end time filter (inclusive)            start_time: Optional start time filter (inclusive)            target: Optional target filter            status: Optional status filter            db: Database session        Args:                List actions with optional filters and pagination.        """    ) -> tuple[List[Action], int]:        offset: int = 0        limit: int = 50,        end_time: Optional[datetime] = None,        start_time: Optional[datetime] = None,        target: Optional[str] = None,        status: Optional[str] = None,        db: AsyncSession,    async def list_actions(    @staticmethod                raise            logger.error(f"Failed to get action {action_id}: {e}", exc_info=True)        except SQLAlchemyError as e:            return result.scalar_one_or_none()            )                select(Action).where(Action.id == action_id)            result = await db.execute(        try:        """            Action instance or None if not found        Returns:                        action_id: ID of the action to retrieve            db: Database session        Args:                Get an action by ID.        """    ) -> Optional[Action]:        action_id: int        db: AsyncSession,    async def get_action(    @staticmethod                raise            logger.error(f"Failed to cancel action {action_id}: {e}", exc_info=True)        except SQLAlchemyError as e:                        return action                                logger.warning(f"Failed to record cancellation metric: {e}")                except Exception as e:                    )                        status=ActionStatus.CANCELLED.value                        action=action.action,                        target=action.target,                    metrics.record_action(                try:            if metrics_available:            # Record metrics                        )                }                    "reason": reason                    "action_type": action.action,                    "target": action.target,                    "action_id": action_id,                extra={                "Action cancelled",            logger.info(                        await db.flush()                            action.details = f"Cancelled: {reason}"            if reason:            action.completed_at = datetime.utcnow()            action.status = ActionStatus.CANCELLED.value                            )                    f"Only {cancellable_statuses} actions can be cancelled."                    f"Action with status '{action.status}' cannot be cancelled. "                raise ValueError(            if action.status not in cancellable_statuses:                        ]                ActionStatus.RUNNING.value                ActionStatus.PENDING.value,            cancellable_statuses = [            # Only pending or running actions can be cancelled                            return None                logger.warning(f"Action {action_id} not found for cancellation")            if action is None:                        action = result.scalar_one_or_none()            )                select(Action).where(Action.id == action_id)            result = await db.execute(        try:        """            ValueError: If action cannot be cancelled        Raises:                        Updated Action instance or None if not found        Returns:                        reason: Optional cancellation reason            action_id: ID of the action to cancel            db: Database session        Args:                Cancel a pending or running action.        """    ) -> Optional[Action]:        reason: Optional[str] = None        action_id: int,        db: AsyncSession,    async def cancel_action(    @staticmethod                raise            logger.error(f"Failed to record action failure {action_id}: {e}", exc_info=True)        except SQLAlchemyError as e:                        return action                                logger.warning(f"Failed to record failure metric: {e}")                except Exception as e:                    )                        status=ActionStatus.FAILED.value                        action=action.action,                        target=action.target,                    metrics.record_action(                try:            if metrics_available:            # Record metrics                        )                }                    "error": error_message                    "action_type": action.action,                    "target": action.target,                    "action_id": action_id,                extra={                "Action failed",            logger.error(                        await db.flush()                            action.details = details            if details:            action.error_message = error_message            action.completed_at = datetime.utcnow()            action.status = ActionStatus.FAILED.value                            return None                logger.warning(f"Action {action_id} not found for failure recording")            if action is None:                        action = result.scalar_one_or_none()            )                select(Action).where(Action.id == action_id)            result = await db.execute(        try:        """            Updated Action instance or None if not found        Returns:                        details: Optional additional details            error_message: Error message describing the failure            action_id: ID of the action that failed            db: Database session        Args:                Mark an action as failed with error details.        """    ) -> Optional[Action]:        details: Optional[str] = None        error_message: str,        action_id: int,        db: AsyncSession,    async def fail_action(    @staticmethod                raise            logger.error(f"Failed to complete action {action_id}: {e}", exc_info=True)        except SQLAlchemyError as e:                        return action                                logger.warning(f"Failed to record completion metric: {e}")                except Exception as e:                    )                        status=ActionStatus.COMPLETED.value                        action=action.action,                        target=action.target,                    metrics.record_action(                try:            if metrics_available:            # Record metrics                        )                }                    )                        if action.completed_at and action.started_at else None                        (action.completed_at - action.started_at).total_seconds()                    "duration_seconds": (                    "action_type": action.action,                    "target": action.target,                    "action_id": action_id,                extra={                "Action completed",            logger.info(                        await db.flush()                            action.details = details            if details:            action.completed_at = datetime.utcnow()            action.status = ActionStatus.COMPLETED.value                            return None                logger.warning(f"Action {action_id} not found for completion")            if action is None:                        action = result.scalar_one_or_none()            )                select(Action).where(Action.id == action_id)            result = await db.execute(        try:        """            Updated Action instance or None if not found        Returns:                        details: Optional completion details            action_id: ID of the action to complete            db: Database session        Args:                Mark an action as completed.        """    ) -> Optional[Action]:        details: Optional[str] = None        action_id: int,        db: AsyncSession,    async def complete_action(    @staticmethod                raise            logger.error(f"Failed to start action {action_id}: {e}", exc_info=True)        except SQLAlchemyError as e:                        return action                        )                }                    "action_type": action.action                    "target": action.target,                    "action_id": action_id,                extra={                "Action started",            logger.info(                        await db.flush()            action.status = ActionStatus.RUNNING.value                            return action                )                    f"Cannot start action {action_id} with status {action.status}"                logger.warning(            if action.status not in [ActionStatus.PENDING.value]:                            return None                logger.warning(f"Action {action_id} not found for start")            if action is None:                        action = result.scalar_one_or_none()            )                select(Action).where(Action.id == action_id)            result = await db.execute(        try:        """            Updated Action instance or None if not found        Returns:                        action_id: ID of the action to start            db: Database session        Args:                Mark an action as running.        """    ) -> Optional[Action]:        action_id: int        db: AsyncSession,    async def start_action(    @staticmethod                raise            logger.error(f"Failed to create action: {e}", exc_info=True)        except SQLAlchemyError as e:                        return action                                logger.warning(f"Failed to record action metric: {e}")                except Exception as e:                    )                        status=status.value                        action=action_type,                        target=target,                    metrics.record_action(                try:            if metrics_available:            # Record metrics                        )                }                    "status": status.value                    "action_type": action_type,                    "target": target,                    "action_id": action.id,                extra={                "Action created",            logger.info(                        await db.flush()            db.add(action)                        )                started_at=datetime.utcnow()                details=details,                status=status.value,                action=action_type,                target=target,            action = Action(        try:        """            SQLAlchemyError: On database errors        Raises:                        Created Action instance        Returns:                        status: Initial status (default: pending)            details: Optional details about the action            action_type: Type of action to perform            target: Target resource identifier            db: Database session        Args:                Create a new action record.        """    ) -> Action:        status: ActionStatus = ActionStatus.PENDING        details: Optional[str] = None,        action_type: str,        target: str,        db: AsyncSession,    async def create_action(    @staticmethod        """    Designed for use by the remediator, agent, and policy engine.    Provides methods for creating, updating, and querying actions.        Service for managing action lifecycle.    """class ActionService:    CANCELLED = "cancelled"    FAILED = "failed"    COMPLETED = "completed"    RUNNING = "running"    PENDING = "pending"    """Action status enumeration."""class ActionStatus(str, Enum):logger = get_logger(__name__)    metrics_available = Falseexcept ImportError:    metrics_available = True    from app.core import metricstry:# Import metrics if availablefrom app.core.logger import get_loggerfrom app.core.db import Action, get_db_managerfrom sqlalchemy.exc import SQLAlchemyErrorfrom sqlalchemy.ext.asyncio import AsyncSessionfrom sqlalchemy import select, update, and_from enum import Enumfrom typing import Optional, Dict, Any, Listfrom datetime import datetime"""- Integration with remediator and agent components- Recording errors and completion- Updating action status- Creating new actionsThis service provides functions for:import os
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool, QueuePool
from datetime import datetime

from app.core.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)

# Base class for ORM models
Base = declarative_base()


# --- ORM Models ---

class Metric(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    value = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<Metric(id={self.id}, name={self.name}, value={self.value}, timestamp={self.timestamp})>"


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True, index=True)
    target = Column(String(255), nullable=False, index=True)
    action = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    details = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True, index=True)

    def __repr__(self):
        return f"<Action(id={self.id}, target={self.target}, action={self.action}, status={self.status})>"


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    condition = Column(String(255), nullable=False)
    severity = Column(String(50), nullable=False, index=True)
    details = Column(Text, nullable=True)
    triggered_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    resolved_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<Alert(id={self.id}, name={self.name}, severity={self.severity})>"


class Setting(Base):
    """Persistent settings storage table."""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), nullable=False, unique=True, index=True)
    value = Column(Text, nullable=False)
    value_type = Column(String(50), nullable=False, default="string")
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Setting(key={self.key}, value={self.value}, type={self.value_type})>"


# --- Database Engine and Session Management ---

class DatabaseManager:
    """Manages async database connections, pooling, and sessions."""

    def __init__(self):
        self.settings = get_settings()
        self.engine: Optional[AsyncEngine] = None
        self.async_session_maker: Optional[async_sessionmaker] = None
        self._is_sqlite = self._detect_sqlite()

    def _detect_sqlite(self) -> bool:
        """Return True if DATABASE_URL is SQLite."""
        db_url = self.settings.DATABASE_URL
        return db_url.startswith("sqlite") or db_url.startswith("sqlite+")

    async def initialize(self) -> None:
        """Initialize database engine and create tables. Call at startup."""
        try:
            db_url = self.settings.DATABASE_URL

            logger.info(f"Initializing database connection", extra={
                "database_url": db_url,
                "is_sqlite": self._is_sqlite
            })

            # Convert SQLite URL to async format
            if self._is_sqlite:
                # SQLite async URL: sqlite+aiosqlite:///path
                if not db_url.startswith("sqlite+aiosqlite"):
                    db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")

            # Create async engine with appropriate pooling
            if self._is_sqlite:
                # SQLite doesn't support connection pooling well, use NullPool
                self.engine = create_async_engine(
                    db_url,
                    echo=self.settings.DEBUG,
                    connect_args={"timeout": 30},
                )
            else:
                # PostgreSQL and other databases use connection pooling
                self.engine = create_async_engine(
                    db_url,
                    echo=self.settings.DEBUG,
                    pool_size=10,
                    max_overflow=20,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                )

            # Create session maker
            self.async_session_maker = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )

            # Create tables
            await self.create_tables()

            logger.info("Database initialization successful")

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise

    async def create_tables(self) -> None:
        """Create all tables if they don't exist."""
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created or verified")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}", exc_info=True)
            raise

    async def get_session(self) -> AsyncSession:
        """Get an async database session."""
        if self.async_session_maker is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        return self.async_session_maker()

    async def dispose(self) -> None:
        """Close all database connections. Call at shutdown."""
        if self.engine is not None:
            await self.engine.dispose()
            logger.info("Database connections disposed")

    @asynccontextmanager
    async def get_session_context(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager for async database sessions with auto-commit/rollback."""
        session = await self.get_session()
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database error: {e}", exc_info=True)
            raise
        finally:
            await session.close()


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Get the global database manager singleton."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    db_manager = get_db_manager()
    session = await db_manager.get_session()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"Database error in dependency: {e}", exc_info=True)
        raise
    finally:
        await session.close()


# Alias for backward compatibility
get_db_async = get_db


async def init_db() -> None:
    """Initialize database at application startup."""
    db_manager = get_db_manager()
    await db_manager.initialize()


async def close_db() -> None:
    """Close database connections at application shutdown."""
    db_manager = get_db_manager()
    await db_manager.dispose()


async def get_session() -> AsyncSession:
    """Get a database session from the global manager."""
    db_manager = get_db_manager()
    return await db_manager.get_session()


# Module-level convenience access
db_manager = get_db_manager()
