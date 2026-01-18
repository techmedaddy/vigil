"""
Pytest configuration and fixtures for Vigil monitoring system tests.

This file provides:
- Async test support configuration
- Shared fixtures for all test modules
- Test database configuration
"""

import pytest
import asyncio
import logging

from app.core.logger import get_logger

# Configure pytest for async tests
pytest_plugins = ('pytest_asyncio',)


# Configure logging for tests
@pytest.fixture(scope="session", autouse=True)
def configure_test_logging():
    """Configure logging for test suite."""
    logger = get_logger(__name__)
    logger.info("=" * 80)
    logger.info("Starting Vigil API Test Suite")
    logger.info("=" * 80)
    
    yield
    
    logger.info("=" * 80)
    logger.info("Vigil API Test Suite Completed")
    logger.info("=" * 80)


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


# Fixture for capturing test timing
@pytest.fixture
def test_timer():
    """Time individual tests."""
    import time
    start_time = time.time()
    yield
    duration = time.time() - start_time
    logger = get_logger(__name__)
    logger.debug(f"Test completed in {duration:.3f} seconds")
