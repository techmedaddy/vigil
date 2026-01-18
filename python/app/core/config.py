"""
Configuration management for Vigil monitoring system.

Uses pydantic BaseSettings to manage environment variables and configuration files.
Supports loading defaults from YAML config files with environment variable overrides.
"""

import os
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables and YAML config files.

    Hierarchy (highest to lowest priority):
    1. Environment variables
    2. YAML config files (from CONFIG_PATH)
    3. Pydantic defaults
    """

    # Database configuration
    DATABASE_URL: str = Field(
        default="sqlite:///./vigil.db",
        description="Database connection URL. Format: dialect+driver://user:password@host:port/database"
    )

    # Redis configuration
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL. Format: redis://[:password]@host:port/db"
    )

    # Collector configuration
    COLLECTOR_PORT: int = Field(
        default=8000,
        description="Port for the metrics collector API"
    )

    # Remediator configuration
    REMEDIATOR_URL: str = Field(
        default="http://127.0.0.1:8081/remediate",
        description="URL of the remediator service for executing remediation actions"
    )

    # Agent configuration
    AGENT_INTERVAL: float = Field(
        default=10.0,
        description="Interval in seconds for the monitoring agent to collect metrics"
    )

    # GitOps daemon configuration
    GITOPSD_INTERVAL: float = Field(
        default=30.0,
        description="Interval in seconds for the GitOps daemon to check for drift"
    )

    # Configuration path
    CONFIG_PATH: str = Field(
        default="configs/collector.yaml",
        description="Path to YAML configuration file"
    )

    # Service name (for logging)
    SERVICE_NAME: str = Field(
        default="vigil",
        description="Service name for logging and identification"
    )

    # Log level
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )

    # API documentation
    API_TITLE: str = Field(
        default="Vigil Monitoring API",
        description="Title for API documentation"
    )

    API_DESCRIPTION: str = Field(
        default="Advanced monitoring and remediation system",
        description="Description for API documentation"
    )

    API_VERSION: str = Field(
        default="1.0.0",
        description="API version"
    )

    # Environment
    ENVIRONMENT: str = Field(
        default="development",
        description="Environment name (development, staging, production)"
    )

    # Debug mode
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode"
    )

    # Retry configuration
    RETRY_MAX_ATTEMPTS: int = Field(
        default=3,
        description="Maximum number of retry attempts for transient errors"
    )

    RETRY_BACKOFF: str = Field(
        default="exponential",
        description="Backoff strategy for retries (exponential, linear, constant)"
    )

    RETRY_BASE_DELAY: float = Field(
        default=1.0,
        description="Base delay in seconds for retry backoff"
    )

    RETRY_MAX_DELAY: float = Field(
        default=60.0,
        description="Maximum delay in seconds between retry attempts"
    )

    # Rate limiting configuration
    RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="Enable rate limiting middleware"
    )

    RATE_LIMIT_REQUESTS: int = Field(
        default=100,
        description="Maximum number of requests allowed per time window per IP"
    )

    RATE_LIMIT_PERIOD: int = Field(
        default=60,
        description="Time window in seconds for rate limiting"
    )

    # Rate limits for specific endpoints
    RATE_LIMIT_INGEST_REQUESTS: int = Field(
        default=200,
        description="Maximum requests per minute for /ingest endpoint"
    )

    RATE_LIMIT_INGEST_WINDOW: int = Field(
        default=60,
        description="Time window in seconds for /ingest rate limiting"
    )

    RATE_LIMIT_ACTIONS_REQUESTS: int = Field(
        default=50,
        description="Maximum requests per minute for /actions endpoint"
    )

    RATE_LIMIT_ACTIONS_WINDOW: int = Field(
        default=60,
        description="Time window in seconds for /actions rate limiting"
    )

    # Audit logging configuration
    AUDIT_LOGGING_ENABLED: bool = Field(
        default=True,
        description="Enable audit logging middleware"
    )

    # Metrics configuration
    METRICS_ENABLED: bool = Field(
        default=True,
        description="Enable Prometheus metrics collection and endpoint"
    )

    METRICS_ENDPOINT: str = Field(
        default="/metrics",
        description="HTTP endpoint path for exposing Prometheus metrics"
    )

    # Policy runner configuration
    POLICY_RUNNER_ENABLED: bool = Field(
        default=True,
        description="Enable policy runner for continuous policy evaluation"
    )

    POLICY_RUNNER_INTERVAL: float = Field(
        default=30.0,
        description="Interval in seconds for policy evaluation checks"
    )

    POLICY_RUNNER_BATCH_SIZE: int = Field(
        default=100,
        description="Number of recent metrics to fetch per evaluation cycle"
    )

    @validator("COLLECTOR_PORT", "AGENT_INTERVAL", "GITOPSD_INTERVAL", "POLICY_RUNNER_INTERVAL")
    def validate_positive(cls, v):
        """Ensure numeric values are positive."""
        if isinstance(v, (int, float)) and v <= 0:
            raise ValueError("Value must be positive")
        return v

    @validator("LOG_LEVEL")
    def validate_log_level(cls, v):
        """Ensure log level is valid."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"LOG_LEVEL must be one of {valid_levels}")
        return v.upper()

    @validator("ENVIRONMENT")
    def validate_environment(cls, v):
        """Ensure environment is valid."""
        valid_envs = {"development", "staging", "production"}
        if v.lower() not in valid_envs:
            raise ValueError(f"ENVIRONMENT must be one of {valid_envs}")
        return v.lower()

    @staticmethod
    def load_yaml_config(config_path: str) -> dict:
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            Dictionary of configuration values or empty dict if file not found
        """
        if not os.path.exists(config_path):
            return {}

        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}
                return config
        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")
            return {}

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "allow"
    }

    def __init__(self, **data):
        """
        Initialize settings with YAML config defaults.

        Priority order:
        1. Environment variables (passed via os.environ)
        2. YAML file (if CONFIG_PATH exists)
        3. Pydantic defaults
        """
        # First, load YAML config if specified
        config_path = data.get("CONFIG_PATH") or os.getenv(
            "CONFIG_PATH", "configs/collector.yaml"
        )

        yaml_config = self.load_yaml_config(config_path)

        # Merge YAML config with provided data (provided data takes precedence)
        merged_data = {**yaml_config, **data}

        super().__init__(**merged_data)

    def to_dict(self) -> dict:
        """
        Export settings as dictionary.

        Returns:
            Dictionary of all settings
        """
        return self.dict()

    def to_json(self) -> str:
        """
        Export settings as JSON string.

        Returns:
            JSON string of all settings
        """
        return json.dumps(self.dict(), indent=2, default=str)


# Global settings instance (singleton)
_settings_instance: Optional[Settings] = None


@lru_cache()
def get_settings() -> Settings:
    """
    Get or create singleton settings instance.

    This function is cached, so it returns the same instance on subsequent calls.
    Suitable for FastAPI dependency injection: `Depends(get_settings)`.

    Returns:
        Singleton Settings instance
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def reload_settings() -> Settings:
    """
    Reload settings instance (clears cache).

    Useful for testing or when configuration needs to be refreshed at runtime.

    Returns:
        New Settings instance
    """
    global _settings_instance
    get_settings.cache_clear()
    _settings_instance = None
    return get_settings()


# Module-level convenience access
settings = get_settings()
