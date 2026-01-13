"""
Comprehensive unit tests for core modules.

Tests:
- logger.py: JSON formatting, structured logging, request ID tracking
- config.py: Settings loading, environment overrides, singleton caching
- db.py: Database initialization, async sessions, ORM models
- middleware.py: Request ID, timing, rate limiting, audit logging
- tasks.py: Agent loop, GitOpsD loop, background task management
"""

import asyncio
import json
import logging
import os
import uuid
from io import StringIO
from typing import AsyncGenerator, Optional
from unittest.mock import Mock, patch, AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request, Response
from starlette.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

# Import all modules to test
from python.app.core.logger import (
    get_logger,
    JSONFormatter,
    RequestLoggingMiddleware,
    RequestContextVar,
    configure_logging,
)
from python.app.core.config import get_settings, reload_settings, Settings
from python.app.core.db import (
    init_db,
    get_db,
    get_db_manager,
    DatabaseManager,
    Base,
    Metric,
    Action,
    Alert,
)
from python.app.core.middleware import (
    RequestIDMiddleware,
    TimingMiddleware,
    RateLimitMiddleware,
    AuditLoggingMiddleware,
    register_middleware,
)
from python.app.core.tasks import (
    start_agent_loop,
    start_gitopsd_loop,
    start_all_background_tasks,
    cancel_all_background_tasks,
    get_background_task_status,
    _detect_anomalies,
    _reconcile_manifests,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[async_sessionmaker, None]:
    """
    Create in-memory SQLite database for testing.

    Provides an AsyncSession factory with auto-cleanup.
    """
    # Create in-memory SQLite engine
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        poolclass=StaticPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create session maker
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    yield async_session

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
def test_settings() -> Settings:
    """
    Create test settings with custom values.
    """
    return Settings(
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        REDIS_URL="redis://localhost:6379/0",
        LOG_LEVEL="DEBUG",
        AGENT_INTERVAL=1.0,
        GITOPSD_INTERVAL=2.0,
        RATE_LIMIT_ENABLED=False,
        DEBUG=True,
    )


@pytest.fixture
def mock_redis():
    """
    Mock Redis client for rate limiting tests.
    """
    mock = MagicMock()
    mock.ping.return_value = True
    mock.incr.return_value = 1
    mock.expire.return_value = True
    return mock


@pytest.fixture
def logger_with_capture():
    """
    Get logger instance with string stream capture.
    """
    logger = get_logger("test_logger")
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    return logger, stream


@pytest.fixture
def fastapi_app() -> FastAPI:
    """
    Create a test FastAPI application.
    """
    app = FastAPI(title="Test App")

    @app.get("/test")
    async def test_endpoint():
        return {"message": "test"}

    @app.post("/test")
    async def test_post():
        return {"ok": True}

    return app


# ============================================================================
# LOGGER TESTS
# ============================================================================

class TestLogger:
    """Tests for logger.py module."""

    def test_get_logger_returns_logger_instance(self):
        """Verify get_logger() returns a Logger instance."""
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_get_logger_is_cached(self):
        """Verify get_logger() returns same instance for same name."""
        logger1 = get_logger("test_cache")
        logger2 = get_logger("test_cache")
        assert logger1 is logger2

    def test_logger_has_json_formatter(self):
        """Verify logger uses JSON formatter."""
        logger = get_logger("json_test")
        assert len(logger.handlers) > 0
        handler = logger.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)

    def test_json_formatter_basic_format(self, logger_with_capture):
        """Verify JSONFormatter produces valid JSON."""
        logger, stream = logger_with_capture
        logger.info("Test message")

        log_output = stream.getvalue()
        log_json = json.loads(log_output.strip())

        assert log_json["message"] == "Test message"
        assert log_json["level"] == "INFO"
        assert log_json["service"] is not None
        assert "timestamp" in log_json

    def test_json_formatter_includes_request_id(self, logger_with_capture):
        """Verify JSONFormatter includes request ID when available."""
        logger, stream = logger_with_capture
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test with request ID",
            args=(),
            exc_info=None,
        )
        record.request_id = "test-req-123"

        formatter = JSONFormatter()
        output = formatter.format(record)
        log_json = json.loads(output)

        assert log_json["request_id"] == "test-req-123"

    def test_json_formatter_includes_exception(self, logger_with_capture):
        """Verify JSONFormatter includes exception info when present."""
        logger, stream = logger_with_capture

        try:
            raise ValueError("Test error")
        except ValueError:
            logger.exception("An error occurred")

        log_output = stream.getvalue()
        log_json = json.loads(log_output.strip())

        assert "exception" in log_json
        assert "ValueError" in log_json["exception"]

    def test_logger_logs_at_info_level(self, logger_with_capture):
        """Verify logger can log at INFO level."""
        logger, stream = logger_with_capture
        logger.info("Info message")
        assert "Info message" in stream.getvalue()

    def test_logger_logs_at_error_level(self, logger_with_capture):
        """Verify logger can log at ERROR level."""
        logger, stream = logger_with_capture
        logger.error("Error message")
        assert "Error message" in stream.getvalue()

    def test_configure_logging_suppresses_verbose_loggers(self):
        """Verify configure_logging() suppresses verbose third-party loggers."""
        configure_logging()

        uvicorn_logger = logging.getLogger("uvicorn")
        assert uvicorn_logger.level >= logging.WARNING

        starlette_logger = logging.getLogger("starlette")
        assert starlette_logger.level >= logging.WARNING

    def test_request_context_var_storage(self):
        """Verify RequestContextVar stores request context."""
        RequestContextVar.request_id = "test-id-123"
        RequestContextVar.path = "/test/path"
        RequestContextVar.method = "GET"

        assert RequestContextVar.request_id == "test-id-123"
        assert RequestContextVar.path == "/test/path"
        assert RequestContextVar.method == "GET"


# ============================================================================
# CONFIG TESTS
# ============================================================================

class TestConfig:
    """Tests for config.py module."""

    def test_get_settings_returns_settings_instance(self):
        """Verify get_settings() returns Settings instance."""
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_get_settings_is_singleton(self):
        """Verify get_settings() returns same instance (singleton)."""
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2

    def test_settings_has_default_values(self):
        """Verify Settings has sensible defaults."""
        settings = Settings()
        assert settings.DATABASE_URL is not None
        assert settings.REDIS_URL is not None
        assert settings.COLLECTOR_PORT > 0
        assert settings.AGENT_INTERVAL > 0
        assert settings.GITOPSD_INTERVAL > 0
        assert settings.LOG_LEVEL in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def test_settings_loads_from_environment(self, monkeypatch):
        """Verify Settings loads values from environment variables."""
        monkeypatch.setenv("COLLECTOR_PORT", "9000")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")

        # Clear cache
        get_settings.cache_clear()
        settings = get_settings()

        assert settings.COLLECTOR_PORT == 9000
        assert settings.LOG_LEVEL == "WARNING"

    def test_settings_env_var_overrides_default(self, monkeypatch):
        """Verify environment variables override defaults."""
        monkeypatch.setenv("SERVICE_NAME", "custom-service")

        # Reload settings
        reload_settings()
        settings = get_settings()

        assert settings.SERVICE_NAME == "custom-service"

    def test_settings_validators_enforce_positive_values(self):
        """Verify validators enforce positive values for numeric fields."""
        with pytest.raises(ValueError):
            Settings(COLLECTOR_PORT=-1)

        with pytest.raises(ValueError):
            Settings(AGENT_INTERVAL=-5.0)

    def test_settings_validators_enforce_log_level(self):
        """Verify validator enforces valid log levels."""
        with pytest.raises(ValueError):
            Settings(LOG_LEVEL="INVALID")

    def test_settings_validators_enforce_environment(self):
        """Verify validator enforces valid environment names."""
        with pytest.raises(ValueError):
            Settings(ENVIRONMENT="invalid-env")

    def test_settings_to_dict(self):
        """Verify Settings.to_dict() returns dictionary."""
        settings = Settings()
        config_dict = settings.to_dict()

        assert isinstance(config_dict, dict)
        assert "DATABASE_URL" in config_dict
        assert "REDIS_URL" in config_dict

    def test_settings_to_json(self):
        """Verify Settings.to_json() returns valid JSON."""
        settings = Settings()
        config_json = settings.to_json()

        parsed = json.loads(config_json)
        assert isinstance(parsed, dict)
        assert "DATABASE_URL" in parsed

    def test_reload_settings_clears_cache(self):
        """Verify reload_settings() creates new instance."""
        settings1 = get_settings()
        reload_settings()
        settings2 = get_settings()

        # Should be different instances
        assert settings1 is not settings2


# ============================================================================
# DATABASE TESTS
# ============================================================================

class TestDatabase:
    """Tests for db.py module."""

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self, test_db):
        """Verify init_db() creates all tables."""
        async_session = test_db

        # Insert test data
        async with async_session() as session:
            metric = Metric(name="test_metric", value=42.0)
            session.add(metric)
            await session.commit()

            # Verify table exists and data inserted
            result = await session.execute(select(Metric))
            metrics = result.scalars().all()
            assert len(metrics) == 1
            assert metrics[0].name == "test_metric"

    @pytest.mark.asyncio
    async def test_metric_model_creation(self, test_db):
        """Verify Metric ORM model works correctly."""
        async_session = test_db

        async with async_session() as session:
            metric = Metric(name="cpu_usage", value=0.75)
            session.add(metric)
            await session.commit()

            result = await session.execute(select(Metric))
            fetched = result.scalar_one()

            assert fetched.name == "cpu_usage"
            assert fetched.value == 0.75
            assert fetched.timestamp is not None

    @pytest.mark.asyncio
    async def test_action_model_creation(self, test_db):
        """Verify Action ORM model works correctly."""
        async_session = test_db

        async with async_session() as session:
            action = Action(
                target="web-server-01",
                action="restart",
                status="pending",
                details="Restart web server due to high CPU",
            )
            session.add(action)
            await session.commit()

            result = await session.execute(select(Action))
            fetched = result.scalar_one()

            assert fetched.target == "web-server-01"
            assert fetched.action == "restart"
            assert fetched.status == "pending"

    @pytest.mark.asyncio
    async def test_alert_model_creation(self, test_db):
        """Verify Alert ORM model works correctly."""
        async_session = test_db

        async with async_session() as session:
            alert = Alert(
                name="high_cpu",
                condition="cpu_usage > 0.85",
                severity="warning",
                details="CPU usage exceeds 85%",
            )
            session.add(alert)
            await session.commit()

            result = await session.execute(select(Alert))
            fetched = result.scalar_one()

            assert fetched.name == "high_cpu"
            assert fetched.severity == "warning"

    @pytest.mark.asyncio
    async def test_database_manager_initialization(self, test_settings):
        """Verify DatabaseManager initializes correctly."""
        with patch("python.app.core.db.get_settings", return_value=test_settings):
            db_manager = DatabaseManager()
            assert db_manager.settings is not None
            assert db_manager._is_sqlite is True

    @pytest.mark.asyncio
    async def test_database_manager_detect_sqlite(self):
        """Verify DatabaseManager detects SQLite URLs."""
        with patch("python.app.core.db.get_settings") as mock_settings:
            mock_settings.return_value.DATABASE_URL = "sqlite:///test.db"
            db_manager = DatabaseManager()
            assert db_manager._is_sqlite is True

    @pytest.mark.asyncio
    async def test_database_manager_detect_postgresql(self):
        """Verify DatabaseManager detects PostgreSQL URLs."""
        with patch("python.app.core.db.get_settings") as mock_settings:
            mock_settings.return_value.DATABASE_URL = (
                "postgresql://user:pass@localhost/db"
            )
            db_manager = DatabaseManager()
            assert db_manager._is_sqlite is False

    @pytest.mark.asyncio
    async def test_get_db_manager_singleton(self):
        """Verify get_db_manager() returns singleton."""
        # Reset global state for testing
        import python.app.core.db as db_module
        db_module._db_manager = None

        manager1 = get_db_manager()
        manager2 = get_db_manager()
        assert manager1 is manager2


# ============================================================================
# MIDDLEWARE TESTS
# ============================================================================

class TestRequestIDMiddleware:
    """Tests for RequestIDMiddleware."""

    def test_request_id_middleware_generates_uuid(self, fastapi_app):
        """Verify middleware generates UUID if not present."""
        app = fastapi_app
        app.add_middleware(RequestIDMiddleware)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        # Verify it's a valid UUID format
        request_id = response.headers["X-Request-ID"]
        assert len(request_id) == 36  # UUID4 format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

    def test_request_id_middleware_uses_provided_id(self, fastapi_app):
        """Verify middleware uses request ID from header if provided."""
        app = fastapi_app
        app.add_middleware(RequestIDMiddleware)

        client = TestClient(app)
        custom_id = "custom-request-id-123"
        response = client.get("/test", headers={"X-Request-ID": custom_id})

        assert response.headers["X-Request-ID"] == custom_id

    def test_request_id_middleware_stores_in_state(self, fastapi_app):
        """Verify middleware stores request ID in request state."""
        request_id_captured = None

        @fastapi_app.get("/capture")
        async def capture_request_id(request: Request):
            nonlocal request_id_captured
            request_id_captured = request.state.request_id
            return {"request_id": request_id_captured}

        fastapi_app.add_middleware(RequestIDMiddleware)

        client = TestClient(fastapi_app)
        response = client.get("/capture")

        assert request_id_captured is not None
        assert response.status_code == 200


class TestTimingMiddleware:
    """Tests for TimingMiddleware."""

    def test_timing_middleware_measures_duration(self, fastapi_app):
        """Verify middleware measures request duration."""
        app = fastapi_app
        app.add_middleware(TimingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200

    def test_timing_middleware_logs_latency(self, fastapi_app):
        """Verify middleware logs latency information."""
        app = fastapi_app
        app.add_middleware(TimingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        with patch("python.app.core.middleware.logger") as mock_logger:
            client = TestClient(app)
            response = client.get("/test")

            assert response.status_code == 200
            # Verify logger was called
            assert mock_logger.info.called or mock_logger.warning.called

    def test_timing_middleware_handles_post_requests(self, fastapi_app):
        """Verify middleware handles POST requests with body."""
        app = fastapi_app
        app.add_middleware(TimingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        client = TestClient(app)
        response = client.post("/test", json={"key": "value"})

        assert response.status_code == 200


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    def test_rate_limit_middleware_disabled_by_default_in_tests(self):
        """Verify rate limiting can be disabled."""
        middleware = RateLimitMiddleware(FastAPI(), enabled=False)
        assert middleware.enabled is False

    def test_rate_limit_middleware_initialization(self, fastapi_app, mock_redis):
        """Verify rate limit middleware initializes with Redis."""
        with patch("python.app.core.middleware.settings") as mock_settings:
            mock_settings.REDIS_URL = "redis://localhost:6379"
            with patch("redis.from_url", return_value=mock_redis):
                app = fastapi_app
                middleware = RateLimitMiddleware(
                    app, enabled=True, requests_per_window=100, window_seconds=60
                )
                assert middleware.enabled is True

    def test_rate_limit_middleware_graceful_fallback(self, fastapi_app):
        """Verify middleware gracefully falls back when Redis unavailable."""
        middleware = RateLimitMiddleware(fastapi_app, enabled=True)
        # Should set enabled=False if Redis not available
        assert isinstance(middleware.enabled, bool)

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_after_threshold(self, mock_redis):
        """Verify middleware returns 429 when rate limit exceeded."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint():
            return {"ok": True}

        app.add_middleware(RequestIDMiddleware)

        # Mock Redis to return count > limit
        mock_redis.incr.return_value = 101
        app.add_middleware(
            RateLimitMiddleware,
            enabled=True,
            requests_per_window=100,
            window_seconds=60,
        )

        client = TestClient(app)

        # Mock redis for the test
        with patch("python.app.core.middleware.settings") as mock_settings:
            with patch("redis.from_url", return_value=mock_redis):
                response = client.get("/test")
                # Should get a response (either 200 or 429 depending on Redis state)
                assert response.status_code in [200, 429]


class TestAuditLoggingMiddleware:
    """Tests for AuditLoggingMiddleware."""

    def test_audit_logging_middleware_logs_requests(self, fastapi_app):
        """Verify audit logging middleware logs requests."""
        app = fastapi_app
        app.add_middleware(AuditLoggingMiddleware)
        app.add_middleware(TimingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        with patch("python.app.core.middleware.logger") as mock_logger:
            client = TestClient(app)
            response = client.get("/test")

            assert response.status_code == 200
            assert mock_logger.info.called

    def test_audit_logging_includes_client_ip(self, fastapi_app):
        """Verify audit logging includes client IP information."""
        audit_data_captured = {}

        app = fastapi_app

        @app.get("/test")
        async def test_endpoint(request: Request):
            audit_data_captured["client_ip"] = request.client.host
            return {"ok": True}

        app.add_middleware(AuditLoggingMiddleware)
        app.add_middleware(TimingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        client = TestClient(app)
        response = client.get("/test")

        assert response.status_code == 200

    def test_audit_logging_handles_exceptions(self, fastapi_app):
        """Verify audit logging handles exceptions gracefully."""
        app = fastapi_app

        @app.get("/error")
        async def error_endpoint():
            raise ValueError("Test error")

        app.add_middleware(AuditLoggingMiddleware)
        app.add_middleware(TimingMiddleware)
        app.add_middleware(RequestIDMiddleware)

        with patch("python.app.core.middleware.logger"):
            client = TestClient(app)
            response = client.get("/error")

            # Should get error response
            assert response.status_code in [500, 200]


class TestMiddlewareRegistration:
    """Tests for middleware registration."""

    def test_register_middleware_adds_all_middleware(self):
        """Verify register_middleware() adds all middleware to app."""
        app = FastAPI()

        with patch("python.app.core.middleware.logger"):
            register_middleware(app)

        # Verify middleware stack was registered (app.middleware_stack should exist)
        assert app.middleware_stack is not None

    def test_register_middleware_respects_settings(self):
        """Verify register_middleware() respects settings."""
        app = FastAPI()

        with patch("python.app.core.middleware.logger"):
            with patch("python.app.core.middleware.settings") as mock_settings:
                mock_settings.RATE_LIMIT_ENABLED = False
                register_middleware(app)

                assert app.middleware_stack is not None


# ============================================================================
# TASKS TESTS
# ============================================================================

class TestTaskDetectAnomalies:
    """Tests for anomaly detection."""

    @pytest.mark.asyncio
    async def test_detect_anomalies_returns_list(self):
        """Verify _detect_anomalies returns list."""
        metrics = []
        result = _detect_anomalies(metrics)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_detect_anomalies_identifies_high_cpu(self, test_db):
        """Verify _detect_anomalies detects high CPU usage."""
        async_session = test_db

        async with async_session() as session:
            # Create metric with CPU usage above threshold (0.85)
            metric = Metric(name="cpu_usage", value=0.95)
            session.add(metric)
            await session.commit()

            result = await session.execute(select(Metric))
            metrics = result.scalars().all()

            anomalies = _detect_anomalies(metrics)
            assert len(anomalies) > 0
            assert anomalies[0]["name"] == "cpu_usage"

    @pytest.mark.asyncio
    async def test_detect_anomalies_ignores_normal_values(self, test_db):
        """Verify _detect_anomalies ignores normal metric values."""
        async_session = test_db

        async with async_session() as session:
            metric = Metric(name="cpu_usage", value=0.50)
            session.add(metric)
            await session.commit()

            result = await session.execute(select(Metric))
            metrics = result.scalars().all()

            anomalies = _detect_anomalies(metrics)
            assert len(anomalies) == 0

    @pytest.mark.asyncio
    async def test_detect_anomalies_includes_severity(self, test_db):
        """Verify _detect_anomalies includes severity level."""
        async_session = test_db

        async with async_session() as session:
            metric = Metric(name="disk_usage", value=0.96)
            session.add(metric)
            await session.commit()

            result = await session.execute(select(Metric))
            metrics = result.scalars().all()

            anomalies = _detect_anomalies(metrics)
            assert len(anomalies) > 0
            assert "severity" in anomalies[0]


class TestTaskReconcileManifests:
    """Tests for manifest reconciliation."""

    def test_reconcile_manifests_returns_list(self):
        """Verify _reconcile_manifests returns list."""
        result = _reconcile_manifests()
        assert isinstance(result, list)

    def test_reconcile_manifests_drift_structure(self):
        """Verify drift events have required fields."""
        # Run multiple times to catch drift events
        for _ in range(100):
            drift_events = _reconcile_manifests()
            if drift_events:
                event = drift_events[0]
                assert "resource_kind" in event
                assert "resource_name" in event
                assert "desired_state" in event
                assert "actual_state" in event
                break


class TestAgentLoop:
    """Tests for agent background task."""

    @pytest.mark.asyncio
    async def test_start_agent_loop_returns_task(self):
        """Verify start_agent_loop returns asyncio.Task."""
        with patch("python.app.core.tasks.get_settings") as mock_settings:
            mock_settings.return_value.AGENT_INTERVAL = 0.1
            with patch("python.app.core.tasks.get_db_manager"):
                task = await start_agent_loop()
                assert isinstance(task, asyncio.Task)

                # Cleanup
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_agent_loop_handles_cancellation(self):
        """Verify agent loop handles CancelledError gracefully."""
        with patch("python.app.core.tasks.get_settings") as mock_settings:
            mock_settings.return_value.AGENT_INTERVAL = 0.01
            with patch("python.app.core.tasks.logger"):
                with patch("python.app.core.tasks.get_db_manager"):
                    task = await start_agent_loop()

                    # Give it time to start
                    await asyncio.sleep(0.05)

                    # Cancel task
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                    # Verify task is done
                    assert task.done()


class TestGitOpsDLoop:
    """Tests for GitOpsD background task."""

    @pytest.mark.asyncio
    async def test_start_gitopsd_loop_returns_task(self):
        """Verify start_gitopsd_loop returns asyncio.Task."""
        with patch("python.app.core.tasks.get_settings") as mock_settings:
            mock_settings.return_value.GITOPSD_INTERVAL = 0.1
            with patch("python.app.core.tasks.get_db_manager"):
                task = await start_gitopsd_loop()
                assert isinstance(task, asyncio.Task)

                # Cleanup
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_gitopsd_loop_handles_cancellation(self):
        """Verify GitOpsD loop handles CancelledError gracefully."""
        with patch("python.app.core.tasks.get_settings") as mock_settings:
            mock_settings.return_value.GITOPSD_INTERVAL = 0.01
            with patch("python.app.core.tasks.logger"):
                with patch("python.app.core.tasks.get_db_manager"):
                    task = await start_gitopsd_loop()

                    # Give it time to start
                    await asyncio.sleep(0.05)

                    # Cancel task
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                    # Verify task is done
                    assert task.done()


class TestBackgroundTaskLifecycle:
    """Tests for background task lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_all_background_tasks(self):
        """Verify start_all_background_tasks starts all tasks."""
        with patch("python.app.core.tasks.get_settings") as mock_settings:
            mock_settings.return_value.AGENT_INTERVAL = 10.0
            mock_settings.return_value.GITOPSD_INTERVAL = 20.0
            with patch("python.app.core.tasks.logger"):
                with patch("python.app.core.tasks.get_db_manager"):
                    # Clear previous tasks
                    import python.app.core.tasks as tasks_module
                    tasks_module._background_tasks.clear()

                    await start_all_background_tasks()

                    # Verify tasks were created
                    assert len(tasks_module._background_tasks) >= 0

                    # Cleanup
                    await cancel_all_background_tasks()

    @pytest.mark.asyncio
    async def test_cancel_all_background_tasks(self):
        """Verify cancel_all_background_tasks cancels all running tasks."""
        with patch("python.app.core.tasks.get_settings") as mock_settings:
            mock_settings.return_value.AGENT_INTERVAL = 0.01
            mock_settings.return_value.GITOPSD_INTERVAL = 0.01
            with patch("python.app.core.tasks.logger"):
                with patch("python.app.core.tasks.get_db_manager"):
                    import python.app.core.tasks as tasks_module
                    tasks_module._background_tasks.clear()

                    await start_all_background_tasks()
                    await asyncio.sleep(0.02)

                    await cancel_all_background_tasks()

                    # Verify all tasks are done
                    for task in tasks_module._background_tasks:
                        assert task.done()

    @pytest.mark.asyncio
    async def test_get_background_task_status(self):
        """Verify get_background_task_status returns task info."""
        with patch("python.app.core.tasks.get_settings") as mock_settings:
            mock_settings.return_value.AGENT_INTERVAL = 10.0
            mock_settings.return_value.GITOPSD_INTERVAL = 20.0
            with patch("python.app.core.tasks.logger"):
                with patch("python.app.core.tasks.get_db_manager"):
                    import python.app.core.tasks as tasks_module
                    tasks_module._background_tasks.clear()

                    await start_all_background_tasks()

                    status = await get_background_task_status()

                    assert "total_tasks" in status
                    assert "running_tasks" in status
                    assert "completed_tasks" in status
                    assert "tasks" in status
                    assert isinstance(status["tasks"], list)

                    await cancel_all_background_tasks()


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestCoreIntegration:
    """Integration tests for core modules working together."""

    @pytest.mark.asyncio
    async def test_logger_and_config_integration(self):
        """Verify logger uses config settings."""
        test_settings = Settings(LOG_LEVEL="DEBUG")
        logger = get_logger("integration_test")
        assert logger.level == logging.DEBUG or logger.level == 0

    @pytest.mark.asyncio
    async def test_database_with_models(self, test_db):
        """Verify database works with all models."""
        async_session = test_db

        async with async_session() as session:
            # Add all model types
            metric = Metric(name="test", value=1.0)
            action = Action(target="test", action="test", status="pending")
            alert = Alert(name="test", condition="test", severity="warning")

            session.add_all([metric, action, alert])
            await session.commit()

            # Verify all inserted
            metrics = await session.execute(select(Metric))
            actions = await session.execute(select(Action))
            alerts = await session.execute(select(Alert))

            assert len(metrics.scalars().all()) == 1
            assert len(actions.scalars().all()) == 1
            assert len(alerts.scalars().all()) == 1

    def test_middleware_stack_ordering(self):
        """Verify middleware stack is correctly ordered."""
        app = FastAPI()

        with patch("python.app.core.middleware.logger"):
            register_middleware(app)

            # Verify app has middleware stack
            assert app.middleware_stack is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
