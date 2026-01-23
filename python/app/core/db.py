"""Database connection and session management using SQLAlchemy async."""

import os
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
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

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
