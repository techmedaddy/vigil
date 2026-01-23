"""Structured JSON logging with request tracking and audit logging."""

import json
import logging
import os
import time
import uuid
from datetime import datetime
from typing import Callable, Optional, Any, Dict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


# --- Configuration ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SERVICE_NAME = os.getenv("SERVICE_NAME", "vigil")


class JSONFormatter(logging.Formatter):
    """Formatter that outputs logs as JSON with structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string."""
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
    """Get a configured logger with JSON formatting."""
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
    """Filter that injects request ID into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = getattr(
                RequestContextVar, "request_id", "no-request-id"
            )
        return True


class RequestContextVar:
    """Simple context holder for request-scoped data."""

    request_id: str = "no-request-id"
    path: str = "/"
    method: str = "UNKNOWN"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware to log request/response cycles with timing."""

    def __init__(self, app, logger: logging.Logger = None):
        super().__init__(app)
        self.logger = logger or get_logger(__name__)
        self.request_id_header = "X-Request-ID"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request, log it, and add request ID to response."""
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
    """Configure root logger and suppress verbose third-party loggers."""
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

# --- Audit Logger Configuration ---
# Separate dedicated audit logger for policy and remediation events
audit_logger = get_logger("vigil.audit")
audit_logger.setLevel(logging.INFO)


# --- Audit Logging Helper Functions ---

def get_request_id() -> str:
    """Get current request ID from context."""
    return getattr(RequestContextVar, "request_id", "no-request-id")


def log_policy_evaluation(
    policy_name: str,
    condition: str,
    result: bool,
    severity: str,
    request_id: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> None:
    """Log a policy evaluation event for audit trail."""
    if request_id is None:
        request_id = get_request_id()
    
    audit_event = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": "policy_evaluation",
        "request_id": request_id,
        "policy_name": policy_name,
        "condition": condition,
        "evaluation_result": result,
        "severity": severity,
    }
    
    if additional_context:
        audit_event.update(additional_context)
    
    audit_logger.info(
        f"Policy evaluation: {policy_name} -> {result}",
        extra=audit_event
    )


def log_policy_violation(
    policy_name: str,
    metrics: Dict[str, Any],
    action: str,
    severity: str,
    request_id: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> None:
    """Log a policy violation event when a condition is triggered."""
    if request_id is None:
        request_id = get_request_id()
    
    # Serialize metrics safely
    try:
        metrics_str = json.dumps(metrics, default=str)
    except Exception:
        metrics_str = str(metrics)
    
    audit_event = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": "policy_violation",
        "request_id": request_id,
        "policy_name": policy_name,
        "metrics": metrics,
        "action_triggered": action,
        "severity": severity,
    }
    
    if additional_context:
        audit_event.update(additional_context)
    
    audit_logger.warning(
        f"Policy violation: {policy_name} triggered action {action}",
        extra=audit_event
    )


def log_remediation(
    target: str,
    action: str,
    status: str,
    detail: str,
    request_id: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> None:
    """Log a remediation action execution for audit trail."""
    if request_id is None:
        request_id = get_request_id()
    
    # Determine log level based on status
    log_level = logging.ERROR if status == "FAILED" else logging.INFO
    
    audit_event = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event_type": "remediation_action",
        "request_id": request_id,
        "target": target,
        "action": action,
        "status": status,
        "detail": detail,
    }
    
    if additional_context:
        audit_event.update(additional_context)
    
    # Log at appropriate level
    audit_logger.log(
        log_level,
        f"Remediation: {action} on {target} -> {status}",
        extra=audit_event
    )


# Module-level logger instance
logger = get_logger(__name__)

# --- Audit Logger Configuration ---
# Separate dedicated audit logger for policy and remediation events
audit_logger = get_logger("vigil.audit")
audit_logger.setLevel(logging.INFO)
