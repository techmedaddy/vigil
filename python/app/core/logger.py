"""
Structured logging utility for Vigil monitoring system.

Provides JSON-formatted logging with structured output suitable for ELK/Prometheus ingestion.
Includes FastAPI middleware for request/response cycle tracking.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


# --- Configuration ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SERVICE_NAME = os.getenv("SERVICE_NAME", "vigil")


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs logs in JSON format.
    Includes timestamp, level, service, logger name, and message.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: LogRecord to format

        Returns:
            JSON-formatted log string
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service": SERVICE_NAME,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Include any additional context fields
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        if hasattr(record, "path"):
            log_data["path"] = record.path
        if hasattr(record, "method"):
            log_data["method"] = record.method
        if hasattr(record, "status_code"):
            log_data["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms

        return json.dumps(log_data, default=str)


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance with JSON formatting.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(LOG_LEVEL)

        # Console handler with JSON formatter
        console_handler = logging.StreamHandler()
        console_handler.setLevel(LOG_LEVEL)
        json_formatter = JSONFormatter()
        console_handler.setFormatter(json_formatter)

        logger.addHandler(console_handler)

        # Prevent propagation to avoid duplicate logs
        logger.propagate = False

    return logger


class RequestIDFilter(logging.Filter):
    """
    Filter that injects request ID from context into log records.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add request_id to log record if available in context."""
        if not hasattr(record, "request_id"):
            record.request_id = getattr(
                RequestContextVar, "request_id", "no-request-id"
            )
        return True


class RequestContextVar:
    """
    Simple context variable holder for request-scoped data.
    In production, use contextvars.ContextVar for thread-safe context.
    """

    request_id: str = "no-request-id"
    path: str = "/"
    method: str = "UNKNOWN"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware to log request/response cycles.

    Logs:
    - Request ID (auto-generated UUID or from header)
    - HTTP method and path
    - Status code
    - Response duration in milliseconds
    """

    def __init__(self, app, logger: logging.Logger = None):
        """
        Initialize middleware.

        Args:
            app: FastAPI application
            logger: Logger instance (uses default if not provided)
        """
        super().__init__(app)
        self.logger = logger or get_logger(__name__)
        self.request_id_header = "X-Request-ID"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and response, logging relevant information.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response with logged information
        """
        # Generate or extract request ID
        request_id = request.headers.get(self.request_id_header, str(uuid.uuid4()))
        RequestContextVar.request_id = request_id
        RequestContextVar.path = request.url.path
        RequestContextVar.method = request.method

        # Record request start time
        start_time = time.time()

        # Log incoming request
        self.logger.info(
            f"Incoming request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query) if request.url.query else None,
            },
        )

        try:
            # Process request
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Log response
            self.logger.info(
                f"Request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": f"{duration_ms:.2f}",
                },
            )

            # Add request ID to response headers
            response.headers[self.request_id_header] = request_id

            return response

        except Exception as e:
            # Calculate duration on error
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            self.logger.error(
                f"Request failed: {str(e)}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": f"{duration_ms:.2f}",
                },
                exc_info=True,
            )

            raise

        finally:
            # Reset context
            RequestContextVar.request_id = "no-request-id"
            RequestContextVar.path = "/"
            RequestContextVar.method = "UNKNOWN"


def configure_logging() -> None:
    """
    Configure root logger and suppress verbose third-party loggers.
    Call once at application startup.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)

    # Suppress verbose third-party loggers
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("starlette").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# Module-level logger instance
logger = get_logger(__name__)
