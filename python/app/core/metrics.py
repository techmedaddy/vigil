"""
Prometheus metrics for Vigil monitoring system.

Provides metrics for:
- HTTP request counting (method, endpoint, status)
- HTTP request latency (endpoint)
- Remediation action tracking (target, action, status)
- Configurable via core/config.py
"""

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry
from app.core.logger import get_logger

logger = get_logger(__name__)

# Create a default registry for all metrics
_registry = CollectorRegistry()

# --- Counters ---

requests_total = Counter(
    name="requests_total",
    documentation="Total HTTP requests received",
    labelnames=["method", "endpoint", "status"],
    registry=_registry,
)

actions_total = Counter(
    name="actions_total",
    documentation="Total remediation actions executed",
    labelnames=["target", "action", "status"],
    registry=_registry,
)

ingest_total = Counter(
    name="ingest_total",
    documentation="Total metrics ingested into Vigil",
    labelnames=["metric_name"],
    registry=_registry,
)

policy_evaluation_total = Counter(
    name="policy_evaluation_total",
    documentation="Total policy evaluations performed",
    labelnames=["policy_name", "result"],
    registry=_registry,
)

# --- Histograms ---

request_latency = Histogram(
    name="request_latency_seconds",
    documentation="HTTP request latency in seconds",
    labelnames=["endpoint"],
    registry=_registry,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
)

drift_detection_latency = Histogram(
    name="drift_detection_latency_seconds",
    documentation="Time taken for GitOpsD drift detection operations in seconds",
    labelnames=["manifest_type", "status"],
    registry=_registry,
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)


def get_metrics() -> bytes:
    """
    Get Prometheus metrics in text format.

    Returns:
        Prometheus text format metrics as bytes
    """
    return generate_latest(_registry)


def get_metrics_content_type() -> str:
    """
    Get MIME type for Prometheus metrics.

    Returns:
        MIME type string for Prometheus text format
    """
    return CONTENT_TYPE_LATEST


def record_request(method: str, endpoint: str, status: int, latency_seconds: float) -> None:
    """
    Record HTTP request metrics.

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: Request path/endpoint
        status: HTTP status code
        latency_seconds: Request latency in seconds
    """
    try:
        requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
        request_latency.labels(endpoint=endpoint).observe(latency_seconds)
    except Exception as e:
        logger.error(
            "Failed to record request metrics",
            method=method,
            endpoint=endpoint,
            status=status,
            error=str(e),
        )


def record_action(target: str, action: str, status: str) -> None:
    """
    Record remediation action metrics.

    Args:
        target: Target system or resource
        action: Action name/type
        status: Action status (success, failure, pending)
    """
    try:
        actions_total.labels(target=target, action=action, status=status).inc()
    except Exception as e:
        logger.error(
            "Failed to record action metrics",
            target=target,
            action=action,
            status=status,
            error=str(e),
        )


def record_ingest(metric_name: str) -> None:
    """
    Record metric ingestion event.

    Args:
        metric_name: Name of the metric being ingested (e.g., 'cpu_usage', 'memory_usage')
    """
    try:
        ingest_total.labels(metric_name=metric_name).inc()
    except Exception as e:
        logger.error(
            "Failed to record ingest metrics",
            extra={"metric_name": metric_name, "error": str(e)}
        )


def record_policy_evaluation(policy_name: str, result: str) -> None:
    """
    Record policy evaluation event.

    Args:
        policy_name: Name of the policy evaluated
        result: Evaluation result ('triggered', 'passed', 'error')
    """
    try:
        policy_evaluation_total.labels(policy_name=policy_name, result=result).inc()
    except Exception as e:
        logger.error(
            "Failed to record policy evaluation metrics",
            extra={"policy_name": policy_name, "result": result, "error": str(e)}
        )


def record_drift_detection(manifest_type: str, status: str, latency_seconds: float) -> None:
    """
    Record GitOpsD drift detection operation metrics.

    Args:
        manifest_type: Type of manifest checked (e.g., 'service', 'alert', 'policy')
        status: Detection status ('drift_found', 'no_drift', 'error')
        latency_seconds: Time taken for drift detection in seconds
    """
    try:
        drift_detection_latency.labels(manifest_type=manifest_type, status=status).observe(latency_seconds)
    except Exception as e:
        logger.error(
            "Failed to record drift detection metrics",
            extra={"manifest_type": manifest_type, "status": status, "error": str(e)}
        )
