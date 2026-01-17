"""
Configuration usage examples and integration patterns for Vigil API.

Demonstrates how to use the Settings object in various contexts.
"""

from fastapi import FastAPI, Depends
from app.core.config import get_settings, Settings


# --- Usage Pattern 1: Basic FastAPI Integration ---

app = FastAPI(
    title="Vigil Monitoring API",
    description="Advanced monitoring and remediation system",
    version="1.0.0",
)


@app.get("/config")
async def get_config(settings: Settings = Depends(get_settings)):
    """
    Endpoint to retrieve current configuration (for debugging/monitoring).

    Args:
        settings: Injected settings via FastAPI dependency

    Returns:
        Current configuration dictionary
    """
    return {
        "database_url": settings.DATABASE_URL,
        "collector_port": settings.COLLECTOR_PORT,
        "agent_interval": settings.AGENT_INTERVAL,
        "gitopsd_interval": settings.GITOPSD_INTERVAL,
        "environment": settings.ENVIRONMENT,
        "debug": settings.DEBUG,
    }


# --- Usage Pattern 2: Direct Access ---

from app.core.config import settings

# Access settings directly in module-level code
print(f"Collector running on port {settings.COLLECTOR_PORT}")
print(f"Database: {settings.DATABASE_URL}")


# --- Usage Pattern 3: In Service Classes ---

class MetricsCollector:
    """Example service that uses settings via dependency injection."""

    def __init__(self, settings: Settings = Depends(get_settings)):
        self.settings = settings
        self.port = settings.COLLECTOR_PORT
        self.db_url = settings.DATABASE_URL

    async def collect_metric(self, metric_name: str, value: float):
        """Collect a metric with configured database."""
        print(f"Storing {metric_name}={value} to {self.db_url}")


# --- Usage Pattern 4: Environment Variable Overrides ---

"""
Override configuration via environment variables:

    export DATABASE_URL="postgresql://user:pass@localhost/vigil"
    export COLLECTOR_PORT=9000
    export AGENT_INTERVAL=5.0
    export GITOPSD_INTERVAL=15.0
    export LOG_LEVEL=DEBUG
    export ENVIRONMENT=production

Or via YAML config file:

    configs/collector.yaml:
    ---
    database_url: "sqlite:///./vigil.db"
    port: 8000
    remediator_url: "http://127.0.0.1:8081/remediate"

Priority order (highest to lowest):
1. Environment variables: export DATABASE_URL=...
2. YAML config file: configs/collector.yaml
3. Pydantic defaults in Settings class
"""


# --- Usage Pattern 5: Testing with Reloaded Settings ---

def test_with_custom_config():
    """Example of reloading settings for testing."""
    import os
    from app.core.config import reload_settings

    # Set environment variable
    os.environ["COLLECTOR_PORT"] = "9999"
    os.environ["ENVIRONMENT"] = "testing"

    # Reload to pick up changes
    fresh_settings = reload_settings()

    assert fresh_settings.COLLECTOR_PORT == 9999
    assert fresh_settings.ENVIRONMENT == "testing"

    # Clean up
    del os.environ["COLLECTOR_PORT"]
    del os.environ["ENVIRONMENT"]


# --- Usage Pattern 6: Conditional Logic Based on Environment ---

@app.on_event("startup")
async def startup():
    """Configure application based on environment."""
    config = get_settings()

    if config.ENVIRONMENT == "development":
        print("Running in development mode - debug logging enabled")
    elif config.ENVIRONMENT == "production":
        print("Running in production mode - error logging only")

    print(f"Connecting to database: {config.DATABASE_URL}")
    print(f"Redis: {config.REDIS_URL}")
    print(f"Remediator: {config.REMEDIATOR_URL}")


# --- Usage Pattern 7: Configuration Validation ---

def validate_config():
    """Example of validating configuration at startup."""
    settings = get_settings()

    # Check required services are reachable
    required_urls = {
        "remediator": settings.REMEDIATOR_URL,
        "redis": settings.REDIS_URL,
    }

    for name, url in required_urls.items():
        print(f"Validating {name} URL: {url}")
        # In production, you would actually test connectivity here
