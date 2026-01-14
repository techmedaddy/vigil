"""
Structured logging utility for Vigil monitoring system.

Provides JSON-formatted logging with structured output suitable for ELK/Prometheus ingestion.
Includes FastAPI middleware for request/response cycle tracking.
Includes dedicated audit logging for policies and remediations.
"""

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

# --- Audit Logger Configuration ---
# Separate dedicated audit logger for policy and remediation events
audit_logger = get_logger("vigil.audit")
audit_logger.setLevel(logging.INFO)


# --- Audit Logging Helper Functions ---

def get_request_id() -> str:
    """
    Get current request ID from context if available.
    
    Returns:
        Request ID string or "no-request-id" if not available
    """
    return getattr(RequestContextVar, "request_id", "no-request-id")


def log_policy_evaluation(
    policy_name: str,
    condition: str,
    result: bool,
    severity: str,
    request_id: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log a policy evaluation event for audit trail.
    
    Args:
        policy_name: Name of the policy evaluated
        condition: Condition expression or description
        result: Whether the condition evaluated to true
        severity: Policy severity level (INFO, WARNING, CRITICAL)
        request_id: Optional request ID (auto-fetched if not provided)
        additional_context: Optional dict with additional fields
    
    Example:
        log_policy_evaluation(
            policy_name="high_cpu_alert",
            condition="cpu_usage > 80%",
            result=True,
            severity="CRITICAL"
        )
    """
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
    """
    Log a policy violation event when a condition is triggered.
    
    Args:
        policy_name: Name of the policy that was violated
        metrics: Dict of metrics that triggered the violation
        action: Action to be taken (e.g., "SCALE_UP", "RESTART_SERVICE")
        severity: Violation severity level (INFO, WARNING, CRITICAL)
        request_id: Optional request ID (auto-fetched if not provided)
        additional_context: Optional dict with additional fields
    
    Example:
        log_policy_violation(
            policy_name="high_cpu_alert",
            metrics={"cpu_usage": 95.5, "threshold": 80},
            action="SCALE_UP",
            severity="CRITICAL"
        )
    """
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
    """
    Log a remediation action execution for audit trail.
    
    Args:
        target: Target resource (e.g., service name, pod name, instance ID)
        action: Action performed (e.g., "RESTART", "SCALE_UP", "DRAIN_POD")
        status: Status of the action (e.g., "SUCCESS", "FAILED", "IN_PROGRESS")
        detail: Detailed message about the action
        request_id: Optional request ID (auto-fetched if not provided)
        additional_context: Optional dict with additional fields
    
    Example:
        log_remediation(
            target="web-service-1",
            action="RESTART",
            status="SUCCESS",
            detail="Service restarted successfully after 2.5 seconds"
        )
    """
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
