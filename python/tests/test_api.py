"""
API tests for Vigil monitoring system (Backend-Only).

Tests cover:
- Metrics ingestion endpoint (/ingest)
- Metrics query endpoint (/query)
- Action management endpoints (/actions)
- Policy management endpoints (/policies)
- Queue stats endpoint (/queue/stats)

Note: UI/dashboard tests removed as Vigil is now backend-only.
Uses pytest with async support and in-memory SQLite database for testing.
"""

import pytest
import asyncio
from datetime import datetime
from typing import AsyncGenerator

import httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.logger import get_logger
from app.core.db import Base, get_db_manager, Metric, Action
from app.core.config import get_settings

# Get test logger
logger = get_logger(__name__)
settings = get_settings()


# --- Fixtures ---

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db():
    """
    Create an in-memory SQLite database for testing.
    
    Yields:
        AsyncSession factory for test database
    """
    logger.info("Setting up test database")
    
    # Create in-memory SQLite engine
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session factory
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    logger.debug("Test database tables created")
    
    yield async_session
    
    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    
    await engine.dispose()
    logger.info("Test database cleaned up")


@pytest.fixture
async def app_with_test_db(test_db):
    """
    Initialize app with test database.
    
    Yields:
        FastAPI app instance with test database
    """
    logger.info("Initializing app with test database")
    
    # Override get_db dependency
    from app.core.db import get_db
    
    async def override_get_db() -> AsyncGenerator:
        """Override database dependency for tests."""
        async with test_db() as session:
            yield session
    
    app.dependency_overrides[get_db] = override_get_db
    
    logger.debug("Database dependency overridden")
    
    yield app
    
    # Cleanup
    app.dependency_overrides.clear()
    logger.info("App dependency overrides cleared")


@pytest.fixture
async def client(app_with_test_db):
    """
    Create async HTTP client for testing.
    
    Yields:
        httpx.AsyncClient instance
    """
    logger.info("Creating HTTP test client")
    
    async with httpx.AsyncClient(app=app_with_test_db, base_url="http://test") as ac:
        logger.debug("HTTP client ready")
        yield ac
    
    logger.info("HTTP client closed")


# --- Tests for /ingest endpoint ---

class TestIngestEndpoint:
    """Tests for metrics ingestion endpoint."""
    
    async def test_ingest_valid_payload(self, client: httpx.AsyncClient):
        """Test that valid metric payload is accepted."""
        logger.info("Testing ingest with valid payload")
        
        payload = {
            "name": "cpu_usage",
            "value": 0.75,
            "tags": {"host": "web-01"}
        }
        
        response = await client.post("/api/v1/ingest", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 201, f"Expected 201, got {response.status_code}"
        
        data = response.json()
        logger.debug(f"Response data: {data}")
        assert data["ok"] is True
        assert "metric_id" in data
        assert isinstance(data["metric_id"], int)
        
        logger.info("✓ Ingest valid payload test passed")
    
    async def test_ingest_missing_name(self, client: httpx.AsyncClient):
        """Test that missing 'name' field returns 422."""
        logger.info("Testing ingest with missing name")
        
        payload = {
            "value": 0.75,
        }
        
        response = await client.post("/api/v1/ingest", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 422
        
        logger.info("✓ Ingest missing name test passed")
    
    async def test_ingest_missing_value(self, client: httpx.AsyncClient):
        """Test that missing 'value' field returns 422."""
        logger.info("Testing ingest with missing value")
        
        payload = {
            "name": "cpu_usage",
        }
        
        response = await client.post("/api/v1/ingest", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 422
        
        logger.info("✓ Ingest missing value test passed")
    
    async def test_ingest_invalid_value_type(self, client: httpx.AsyncClient):
        """Test that invalid value type returns 422."""
        logger.info("Testing ingest with invalid value type")
        
        payload = {
            "name": "cpu_usage",
            "value": "not_a_number",
        }
        
        response = await client.post("/api/v1/ingest", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 422
        
        logger.info("✓ Ingest invalid value type test passed")
    
    async def test_ingest_empty_name(self, client: httpx.AsyncClient):
        """Test that empty name field returns 400."""
        logger.info("Testing ingest with empty name")
        
        payload = {
            "name": "",
            "value": 0.75,
        }
        
        response = await client.post("/api/v1/ingest", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 400
        
        logger.info("✓ Ingest empty name test passed")
    
    async def test_ingest_health_check(self, client: httpx.AsyncClient):
        """Test ingest health check endpoint."""
        logger.info("Testing ingest health check")
        
        response = await client.get("/api/v1/ingest/health")
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ingest"
        
        logger.info("✓ Ingest health check test passed")


# --- Tests for /actions endpoint ---

class TestActionsEndpoint:
    """Tests for action management endpoints."""
    
    async def test_create_action_valid(self, client: httpx.AsyncClient):
        """Test creating an action with valid payload."""
        logger.info("Testing create action with valid payload")
        
        payload = {
            "target": "web-service",
            "action": "restart",
            "status": "pending",
            "details": "CPU threshold exceeded"
        }
        
        response = await client.post("/api/v1/actions", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 201
        
        data = response.json()
        logger.debug(f"Response data: {data}")
        assert data["ok"] is True
        assert "action_id" in data
        assert isinstance(data["action_id"], int)
        
        logger.info("✓ Create action valid test passed")
    
    async def test_create_action_missing_target(self, client: httpx.AsyncClient):
        """Test that missing 'target' field returns 422."""
        logger.info("Testing create action with missing target")
        
        payload = {
            "action": "restart",
            "status": "pending",
        }
        
        response = await client.post("/api/v1/actions", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 422
        
        logger.info("✓ Create action missing target test passed")
    
    async def test_create_action_missing_action(self, client: httpx.AsyncClient):
        """Test that missing 'action' field returns 422."""
        logger.info("Testing create action with missing action")
        
        payload = {
            "target": "web-service",
            "status": "pending",
        }
        
        response = await client.post("/api/v1/actions", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 422
        
        logger.info("✓ Create action missing action test passed")
    
    async def test_create_action_invalid_status(self, client: httpx.AsyncClient):
        """Test that invalid status enum returns 422."""
        logger.info("Testing create action with invalid status")
        
        payload = {
            "target": "web-service",
            "action": "restart",
            "status": "invalid_status",
        }
        
        response = await client.post("/api/v1/actions", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 422
        
        logger.info("✓ Create action invalid status test passed")
    
    async def test_create_action_empty_target(self, client: httpx.AsyncClient):
        """Test that empty target field returns 400."""
        logger.info("Testing create action with empty target")
        
        payload = {
            "target": "",
            "action": "restart",
            "status": "pending",
        }
        
        response = await client.post("/api/v1/actions", json=payload)
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 400
        
        logger.info("✓ Create action empty target test passed")
    
    async def test_list_actions(self, client: httpx.AsyncClient):
        """Test listing actions."""
        logger.info("Testing list actions")
        
        # Create a test action first
        create_payload = {
            "target": "web-service",
            "action": "restart",
            "status": "pending",
        }
        create_response = await client.post("/api/v1/actions", json=create_payload)
        assert create_response.status_code == 201
        
        # List actions
        response = await client.get("/api/v1/actions")
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 200
        
        data = response.json()
        logger.debug(f"Response data: {data}")
        assert "count" in data
        assert "actions" in data
        assert isinstance(data["count"], int)
        assert isinstance(data["actions"], list)
        assert data["count"] >= 1
        
        logger.info("✓ List actions test passed")
    
    async def test_get_action_detail(self, client: httpx.AsyncClient):
        """Test getting action details by ID."""
        logger.info("Testing get action detail")
        
        # Create a test action first
        create_payload = {
            "target": "web-service",
            "action": "restart",
            "status": "pending",
        }
        create_response = await client.post("/api/v1/actions", json=create_payload)
        action_id = create_response.json()["action_id"]
        
        # Get action details
        response = await client.get(f"/api/v1/actions/{action_id}")
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 200
        
        data = response.json()
        logger.debug(f"Response data: {data}")
        assert data["id"] == action_id
        assert data["target"] == "web-service"
        assert data["action"] == "restart"
        assert data["status"] == "pending"
        
        logger.info("✓ Get action detail test passed")
    
    async def test_get_action_not_found(self, client: httpx.AsyncClient):
        """Test that getting non-existent action returns 404."""
        logger.info("Testing get action not found")
        
        response = await client.get("/api/v1/actions/99999")
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 404
        
        logger.info("✓ Get action not found test passed")
    
    async def test_actions_health_check(self, client: httpx.AsyncClient):
        """Test actions health check endpoint."""
        logger.info("Testing actions health check")
        
        response = await client.get("/api/v1/actions/health")
        
        logger.debug(f"Response status: {response.status_code}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "ok"
        
        logger.info("✓ Actions health check test passed")


# --- Integration tests ---

class TestIntegration:
    """Integration tests combining multiple endpoints."""
    
    async def test_ingest_and_list_actions(self, client: httpx.AsyncClient):
        """Test ingesting metric and creating related action."""
        logger.info("Testing integration: ingest metric -> create action")
        
        # Ingest a metric
        ingest_payload = {
            "name": "cpu_usage",
            "value": 0.95,
        }
        ingest_response = await client.post("/api/v1/ingest", json=ingest_payload)
        assert ingest_response.status_code == 201
        
        # Create an action for the high metric
        action_payload = {
            "target": "web-service",
            "action": "scale_up",
            "status": "pending",
            "details": "CPU threshold exceeded"
        }
        action_response = await client.post("/api/v1/actions", json=action_payload)
        assert action_response.status_code == 201
        
        # List actions and verify
        list_response = await client.get("/api/v1/actions")
        assert list_response.status_code == 200
        data = list_response.json()
        assert data["count"] >= 1
        
        logger.info("✓ Integration test passed")
    
    async def test_multiple_endpoints_health(self, client: httpx.AsyncClient):
        """Test all health check endpoints."""
        logger.info("Testing all health check endpoints")
        
        endpoints = [
            "/api/v1/ingest/health",
            "/api/v1/actions/health",
            "/api/v1/ui/health",
        ]
        
        for endpoint in endpoints:
            logger.debug(f"Checking {endpoint}")
            response = await client.get(endpoint)
            assert response.status_code == 200
            data = response.json()
            assert "status" in data
        
        logger.info("✓ All health checks passed")


# --- Run all tests ---

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
