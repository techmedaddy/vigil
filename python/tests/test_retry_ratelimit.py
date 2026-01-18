"""
Tests for retry logic and rate limiting in Vigil.

Tests cover:
- Retry decorator functionality
- Exponential backoff calculation
- Rate limiting middleware
- Integration with DB operations
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.core.utils import retry, calculate_delay
from app.core.config import Settings


# --- Retry Decorator Tests ---

class TestRetryDecorator:
    """Test suite for retry decorator functionality."""

    @pytest.mark.asyncio
    async def test_retry_success_first_attempt(self):
        """Test function succeeds on first attempt without retry."""
        call_count = 0

        @retry(max_attempts=3, log_retries=False)
        async def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await successful_function()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_success_after_failures(self):
        """Test function succeeds after transient failures."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, log_retries=False)
        async def eventually_successful():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OperationalError("Transient error", None, None)
            return "success"

        result = await eventually_successful()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        """Test function fails after all retries exhausted."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, log_retries=False)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise OperationalError("Permanent error", None, None)

        with pytest.raises(OperationalError):
            await always_fails()
        
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_specific_exceptions(self):
        """Test retry only catches specified exception types."""
        call_count = 0

        @retry(
            max_attempts=3, 
            base_delay=0.01, 
            exceptions=(ValueError,),
            log_retries=False
        )
        async def raises_different_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("Different error type")

        with pytest.raises(TypeError):
            await raises_different_error()
        
        # Should not retry for non-matching exceptions
        assert call_count == 1

    def test_retry_sync_function(self):
        """Test retry decorator works with synchronous functions."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, log_retries=False)
        def sync_eventually_successful():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Transient error")
            return "success"

        result = sync_eventually_successful()
        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_backoff_timing(self):
        """Test exponential backoff delays are applied."""
        call_times = []

        @retry(
            max_attempts=3, 
            backoff_strategy="exponential",
            base_delay=0.1,
            log_retries=False
        )
        async def timed_function():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise ValueError("Retry needed")
            return "success"

        await timed_function()
        
        assert len(call_times) == 3
        # Check delays between attempts (allowing for timing variance)
        delay1 = call_times[1] - call_times[0]
        delay2 = call_times[2] - call_times[1]
        
        # First delay should be ~0.1s, second ~0.2s (exponential)
        assert 0.08 < delay1 < 0.15
        assert 0.15 < delay2 < 0.30


class TestBackoffCalculation:
    """Test suite for backoff delay calculation."""

    def test_exponential_backoff(self):
        """Test exponential backoff calculation."""
        assert calculate_delay(1, "exponential", 1.0, 2.0, 60.0) == 1.0
        assert calculate_delay(2, "exponential", 1.0, 2.0, 60.0) == 2.0
        assert calculate_delay(3, "exponential", 1.0, 2.0, 60.0) == 4.0
        assert calculate_delay(4, "exponential", 1.0, 2.0, 60.0) == 8.0

    def test_linear_backoff(self):
        """Test linear backoff calculation."""
        assert calculate_delay(1, "linear", 2.0, 2.0, 60.0) == 2.0
        assert calculate_delay(2, "linear", 2.0, 2.0, 60.0) == 4.0
        assert calculate_delay(3, "linear", 2.0, 2.0, 60.0) == 6.0

    def test_constant_backoff(self):
        """Test constant backoff calculation."""
        assert calculate_delay(1, "constant", 5.0, 2.0, 60.0) == 5.0
        assert calculate_delay(2, "constant", 5.0, 2.0, 60.0) == 5.0
        assert calculate_delay(10, "constant", 5.0, 2.0, 60.0) == 5.0

    def test_max_delay_cap(self):
        """Test delay is capped at max_delay."""
        # Exponential would calculate 1 * 2^9 = 512, but capped at 10
        delay = calculate_delay(10, "exponential", 1.0, 2.0, 10.0)
        assert delay == 10.0


# --- Rate Limiting Tests ---

class TestRateLimitMiddleware:
    """Test suite for rate limiting middleware."""

    @pytest.fixture
    def mock_redis(self):
        """Create a mock Redis client."""
        redis_mock = Mock()
        redis_mock.ping.return_value = True
        redis_mock.incr.return_value = 1
        redis_mock.expire.return_value = True
        
        # Mock pipeline
        pipeline_mock = Mock()
        pipeline_mock.incr.return_value = pipeline_mock
        pipeline_mock.ttl.return_value = pipeline_mock
        pipeline_mock.execute.return_value = [1, 60]  # [count, ttl]
        redis_mock.pipeline.return_value = pipeline_mock
        
        return redis_mock

    @pytest.mark.asyncio
    async def test_rate_limit_allows_under_limit(self, mock_redis):
        """Test requests under rate limit are allowed."""
        from app.core.middleware import RateLimitMiddleware
        
        mock_app = Mock()
        middleware = RateLimitMiddleware(
            mock_app,
            enabled=True,
            requests_per_window=100,
            window_seconds=60
        )
        middleware.redis_client = mock_redis
        
        # Mock request and response
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.request_id = "test-123"
        request.client = Mock()
        request.client.host = "192.168.1.1"
        request.url = Mock()
        request.url.path = "/api/v1/ingest"
        
        async def mock_call_next(req):
            response = Response(content="OK", status_code=200)
            return response
        
        # Set pipeline to return count under limit
        pipeline_mock = mock_redis.pipeline.return_value
        pipeline_mock.execute.return_value = [50, 60]  # 50 requests, 60s TTL
        
        response = await middleware.dispatch(request, mock_call_next)
        
        assert response.status_code == 200
        assert "X-RateLimit-Limit" in response.headers
        assert response.headers["X-RateLimit-Limit"] == "100"

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_over_limit(self, mock_redis):
        """Test requests over rate limit are blocked with 429."""
        from app.core.middleware import RateLimitMiddleware
        
        mock_app = Mock()
        middleware = RateLimitMiddleware(
            mock_app,
            enabled=True,
            requests_per_window=100,
            window_seconds=60
        )
        middleware.redis_client = mock_redis
        
        # Mock request
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.request_id = "test-456"
        request.client = Mock()
        request.client.host = "192.168.1.2"
        request.url = Mock()
        request.url.path = "/api/v1/ingest"
        
        async def mock_call_next(req):
            return Response(content="OK", status_code=200)
        
        # Set pipeline to return count over limit
        pipeline_mock = mock_redis.pipeline.return_value
        pipeline_mock.execute.return_value = [101, 30]  # 101 requests, 30s TTL
        
        response = await middleware.dispatch(request, mock_call_next)
        
        assert response.status_code == 429
        assert "Retry-After" in response.headers

    @pytest.mark.asyncio
    async def test_rate_limit_endpoint_specific(self, mock_redis):
        """Test endpoint-specific rate limits."""
        from app.core.middleware import RateLimitMiddleware
        
        mock_app = Mock()
        middleware = RateLimitMiddleware(
            mock_app,
            enabled=True,
            requests_per_window=100,
            window_seconds=60,
            endpoint_limits={
                "/api/v1/ingest": (200, 60),
                "/api/v1/actions": (50, 60)
            }
        )
        middleware.redis_client = mock_redis
        
        # Test ingest endpoint gets higher limit
        limits = middleware.get_endpoint_limits("/api/v1/ingest")
        assert limits == (200, 60)
        
        # Test actions endpoint gets lower limit
        limits = middleware.get_endpoint_limits("/api/v1/actions")
        assert limits == (50, 60)
        
        # Test default for unknown endpoint
        limits = middleware.get_endpoint_limits("/api/v1/unknown")
        assert limits == (100, 60)

    @pytest.mark.asyncio
    async def test_rate_limit_redis_failure_allows_request(self):
        """Test requests are allowed if Redis fails (fail-open)."""
        from app.core.middleware import RateLimitMiddleware
        
        mock_app = Mock()
        middleware = RateLimitMiddleware(
            mock_app,
            enabled=True,
            requests_per_window=100,
            window_seconds=60
        )
        
        # Simulate Redis failure
        mock_redis = Mock()
        mock_redis.pipeline.side_effect = Exception("Redis connection failed")
        middleware.redis_client = mock_redis
        
        request = Mock(spec=Request)
        request.state = Mock()
        request.state.request_id = "test-789"
        request.client = Mock()
        request.client.host = "192.168.1.3"
        request.url = Mock()
        request.url.path = "/api/v1/ingest"
        
        async def mock_call_next(req):
            return Response(content="OK", status_code=200)
        
        response = await middleware.dispatch(request, mock_call_next)
        
        # Should allow request despite Redis failure
        assert response.status_code == 200


# --- Integration Tests ---

class TestRetryIntegration:
    """Integration tests for retry with database operations."""

    @pytest.mark.asyncio
    async def test_db_operation_with_retry(self):
        """Test database operation succeeds with retry on transient error."""
        from app.core.utils import retry
        
        call_count = 0
        
        @retry(max_attempts=3, base_delay=0.01, log_retries=False)
        async def mock_db_operation():
            nonlocal call_count
            call_count += 1
            
            if call_count < 2:
                # Simulate transient DB error
                raise OperationalError("Connection lost", None, None)
            
            return {"id": 123, "name": "test"}
        
        result = await mock_db_operation()
        assert result["id"] == 123
        assert call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
