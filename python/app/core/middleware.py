"""
Middleware utilities for Vigil monitoring system.

Provides production-ready middleware for:
- Request ID tracking
- Request/response timing and logging
- Rate limiting (Redis-based)
- Audit logging (database storage)
"""

import time
import uuid
from typing import Callable
from datetime import datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logger import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)
settings = get_settings()

# Import metrics module (optional - will use if metrics enabled)
try:
    from app.core import metrics
    metrics_available = True
except ImportError:
    metrics_available = False


# --- Request ID Middleware ---

class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware that generates a unique request ID for each request.

    - Generates UUID if not present
    - Attaches to response headers (X-Request-ID)
    - Logs request ID with context
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request with request ID tracking.

        Args:
            request: FastAPI Request object
            call_next: Next middleware/endpoint handler

        Returns:
            Response with X-Request-ID header
        """
        # Get or generate request ID
        request_id = request.headers.get("X-Request-ID")
        if not request_id:
            request_id = str(uuid.uuid4())

        # Store in request state for access downstream
        request.state.request_id = request_id

        # Log request start
        logger.debug(
            "Request received",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query_string": str(request.url.query) if request.url.query else None,
            }
        )

        # Process request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        logger.debug(
            "Response sent",
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
            }
        )

        return response


# --- Timing Middleware ---

class TimingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that measures and logs request duration.

    - Measures request processing time
    - Logs path, method, status code, and latency
    - Calculates request/response sizes
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and measure timing.

        Args:
            request: FastAPI Request object
            call_next: Next middleware/endpoint handler

        Returns:
            Response with timing metadata in request.state
        """
        start_time = time.time()
        request_id = getattr(request.state, "request_id", "unknown")

        # Calculate request size
        request_size = 0
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                request_size = len(body)
            except Exception:
                pass

        # Process request
        response = await call_next(request)

        # Calculate response time
        process_time = (time.time() - start_time) * 1000  # Convert to milliseconds
        process_time_seconds = process_time / 1000  # For metrics in seconds

        # Get response size
        response_size = 0
        if response.headers.get("content-length"):
            try:
                response_size = int(response.headers["content-length"])
            except ValueError:
                pass

        # Log timing information
        log_level = "info" if response.status_code < 400 else "warning"
        logger_func = getattr(logger, log_level)

        logger_func(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(process_time, 2),
                "request_size_bytes": request_size,
                "response_size_bytes": response_size,
            }
        )

        # Record Prometheus metrics if enabled
        if metrics_available and getattr(settings, "METRICS_ENABLED", True):
            try:
                metrics.record_request(
                    method=request.method,
                    endpoint=request.url.path,
                    status=response.status_code,
                    latency_seconds=process_time_seconds,
                )
            except Exception as e:
                logger.warning("Failed to record metrics", extra={"error": str(e)})

        # Store in request state for audit logging
        request.state.response_time_ms = process_time
        request.state.request_size_bytes = request_size
        request.state.response_size_bytes = response_size

        return response


# --- Metrics Middleware ---

class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware for collecting Prometheus metrics.

    - Tracks request counts by method, endpoint, and status code
    - Records request latency by endpoint
    - Configurable via settings (METRICS_ENABLED)
    - Graceful fallback if prometheus_client unavailable
    """

    def __init__(self, app, enabled: bool = True):
        """
        Initialize metrics middleware.

        Args:
            app: FastAPI application
            enabled: Whether metrics collection is enabled
        """
        super().__init__(app)
        self.enabled = enabled and metrics_available

        if self.enabled:
            logger.info("Metrics middleware initialized")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and collect metrics.

        Args:
            request: FastAPI Request object
            call_next: Next middleware/endpoint handler

        Returns:
            Response with metrics recorded
        """
        if not self.enabled:
            return await call_next(request)

        start_time = time.time()

        # Process request
        response = await call_next(request)

        # Calculate latency
        latency_seconds = time.time() - start_time

        # Record metrics
        try:
            metrics.record_request(
                method=request.method,
                endpoint=request.url.path,
                status=response.status_code,
                latency_seconds=latency_seconds,
            )
        except Exception as e:
            logger.warning(
                "Failed to record metrics in middleware",
                extra={"error": str(e)}
            )

        return response


# --- Rate Limiting Middleware ---

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for rate limiting requests per IP address.

    - Uses Redis for distributed rate limiting
    - Configurable via settings (RATE_LIMIT_ENABLED, RATE_LIMIT_REQUESTS, RATE_LIMIT_PERIOD)
    - Graceful fallback if Redis unavailable
    """

    def __init__(self, app, enabled: bool = True, requests_per_window: int = 100, window_seconds: int = 60):
        """
        Initialize rate limit middleware.

        Args:
            app: FastAPI application
            enabled: Whether rate limiting is enabled
            requests_per_window: Maximum requests per time window
            window_seconds: Time window in seconds
        """
        super().__init__(app)
        self.enabled = enabled
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.redis_client = None

        if self.enabled:
            try:
                import redis
                self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
                self.redis_client.ping()
                logger.info(
                    "Rate limiting middleware initialized",
                    extra={
                        "requests_per_window": requests_per_window,
                        "window_seconds": window_seconds,
                    }
                )
            except Exception as e:
                logger.warning(
                    "Rate limiting middleware disabled - Redis unavailable",
                    extra={"error": str(e)}
                )
                self.enabled = False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request with rate limiting.

        Args:
            request: FastAPI Request object
            call_next: Next middleware/endpoint handler

        Returns:
            Response (429 if rate limited)
        """
        request_id = getattr(request.state, "request_id", "unknown")

        if not self.enabled or not self.redis_client:
            return await call_next(request)

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        rate_limit_key = f"rate_limit:{client_ip}"

        try:
            # Get current count
            current = self.redis_client.incr(rate_limit_key)

            # Set expiry on first request
            if current == 1:
                self.redis_client.expire(rate_limit_key, self.window_seconds)

            # Check if limit exceeded
            if current > self.requests_per_window:
                logger.warning(
                    "Rate limit exceeded",
                    extra={
                        "request_id": request_id,
                        "client_ip": client_ip,
                        "requests": current,
                        "limit": self.requests_per_window,
                    }
                )
                return Response(
                    content='{"error": "Rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                    headers={"X-RateLimit-Limit": str(self.requests_per_window)},
                )

            # Store remaining quota in request state
            request.state.rate_limit_remaining = self.requests_per_window - current

        except Exception as e:
            logger.error(
                "Rate limiting check failed",
                exc_info=True,
                extra={
                    "request_id": request_id,
                    "error": str(e),
                }
            )

        return await call_next(request)


# --- Audit Logging Middleware ---

class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for audit logging request/response metadata to database.

    - Records all request/response details
    - Supports compliance and monitoring requirements
    - Includes error tracking and client information
    - Graceful fallback if database unavailable
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and log to audit table.

        Args:
            request: FastAPI Request object
            call_next: Next middleware/endpoint handler

        Returns:
            Response with audit log recorded
        """
        request_id = getattr(request.state, "request_id", "unknown")

        try:
            # Process request
            response = await call_next(request)

            # Collect audit data
            client_ip = request.client.host if request.client else "unknown"
            response_time_ms = getattr(request.state, "response_time_ms", 0)
            request_size_bytes = getattr(request.state, "request_size_bytes", None)
            response_size_bytes = getattr(request.state, "response_size_bytes", None)

            # Extract query parameters
            query_params = str(dict(request.query_params)) if request.query_params else None

            # Log audit information (structured)
            logger.info(
                "Audit log entry",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query_params": query_params,
                    "client_ip": client_ip,
                    "status_code": response.status_code,
                    "response_time_ms": response_time_ms,
                    "request_size_bytes": request_size_bytes,
                    "response_size_bytes": response_size_bytes,
                    "user_agent": request.headers.get("user-agent"),
                }
            )

            return response

        except Exception as e:
            logger.error(
                "Audit logging middleware error",
                exc_info=True,
                extra={
                    "request_id": request_id,
                    "error": str(e),
                }
            )
            return Response(
                content='{"error": "Internal server error"}',
                status_code=500,
                media_type="application/json",
            )


# --- Middleware Registration Function ---

def register_middleware(app) -> None:
    """
    Register all middleware with FastAPI application.

    Should be called in main.py after creating the FastAPI app instance.

    Args:
        app: FastAPI application instance

    Example:
        from fastapi import FastAPI
        from app.core.middleware import register_middleware

        app = FastAPI()
        register_middleware(app)
    """
    # Order matters: register in reverse order (last registered runs first)
    # 1. Audit logging (innermost - runs first on request, last on response)
    app.add_middleware(AuditLoggingMiddleware)

    # 2. Metrics collection
    app.add_middleware(
        MetricsMiddleware,
        enabled=getattr(settings, "METRICS_ENABLED", True),
    )

    # 3. Rate limiting
    app.add_middleware(
        RateLimitMiddleware,
        enabled=getattr(settings, "RATE_LIMIT_ENABLED", True),
        requests_per_window=getattr(settings, "RATE_LIMIT_REQUESTS", 100),
        window_seconds=getattr(settings, "RATE_LIMIT_PERIOD", 60),
    )

    # 4. Timing
    app.add_middleware(TimingMiddleware)

    # 5. Request ID (outermost - runs last on request, first on response)
    app.add_middleware(RequestIDMiddleware)

    logger.info(
        "Middleware stack registered: RequestID, Timing, RateLimit, Metrics, AuditLogging"
    )

