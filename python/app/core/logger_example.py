"""
Example usage of the structured logging utility with FastAPI.

This demonstrates how to integrate the logging system into your FastAPI application.
"""

from fastapi import FastAPI
from python.app.core.logger import (
    get_logger,
    configure_logging,
    RequestLoggingMiddleware,
)

# Configure logging at startup
configure_logging()

# Create logger instance
logger = get_logger(__name__)

# Initialize FastAPI app
app = FastAPI(title="Vigil API")

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware, logger=logger)


@app.on_event("startup")
async def startup_event():
    """Log application startup."""
    logger.info("Vigil API starting up...")


@app.on_event("shutdown")
async def shutdown_event():
    """Log application shutdown."""
    logger.info("Vigil API shutting down...")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    logger.debug("Health check requested")
    return {"status": "healthy"}


@app.post("/ingest")
async def ingest_metric(payload: dict):
    """
    Ingest metrics endpoint.

    Args:
        payload: Metric payload with name and value

    Returns:
        Acknowledgment response
    """
    logger.info(f"Ingesting metric: {payload.get('name')}")
    return {"status": "received", "metric": payload.get("name")}


@app.post("/drift")
async def report_drift(payload: dict):
    """
    Report GitOps drift endpoint.

    Args:
        payload: Drift report with manifest path and metadata

    Returns:
        Acknowledgment response
    """
    manifest_path = payload.get("path", "unknown")
    logger.warning(f"Drift detected in manifest: {manifest_path}")
    return {"status": "drift_recorded", "manifest": manifest_path}


# Usage example in other modules:
#
# from python.app.core.logger import get_logger
#
# logger = get_logger(__name__)
#
# # Log at different levels
# logger.debug("This is a debug message")
# logger.info("This is an info message")
# logger.warning("This is a warning message")
# logger.error("This is an error message")
#
# # Log with extra context (automatically converted to JSON)
# logger.info(
#     "Processing started",
#     extra={
#         "user_id": 123,
#         "action": "process_metric"
#     }
# )
