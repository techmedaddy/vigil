"""Settings API for managing frontend configuration updates."""

import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator, root_validator
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import get_db, Setting
from app.core.logger import get_logger
from app.core.config import get_settings, reload_settings, set_runtime_override, clear_runtime_overrides

logger = get_logger(__name__)

# Create router with /settings prefix
router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    responses={
        400: {"description": "Invalid request"},
        422: {"description": "Validation error"},
        500: {"description": "Internal server error"},
    },
)


# --- Enums ---

class LogLevel(str, Enum):
    """Valid log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class BackoffStrategy(str, Enum):
    """Valid backoff strategies for retries."""
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    CONSTANT = "constant"


class Environment(str, Enum):
    """Valid environment names."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


# --- Pydantic Models ---

class RemediationSettings(BaseModel):
    """Remediation-specific settings based on RemediationConfig."""
    
    remediator_url: Optional[str] = Field(
        default=None,
        description="URL for the remediator service"
    )
    max_concurrent: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="Maximum concurrent remediation tasks (1-100)"
    )
    task_queue_size: Optional[int] = Field(
        default=None,
        ge=10,
        le=10000,
        description="Size of the task queue (10-10000)"
    )
    interval: Optional[int] = Field(
        default=None,
        ge=1,
        le=3600,
        description="Polling interval in seconds (1-3600)"
    )


class RetrySettings(BaseModel):
    """Retry configuration settings."""
    
    max_attempts: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Maximum retry attempts (1-10)"
    )
    backoff: Optional[BackoffStrategy] = Field(
        default=None,
        description="Backoff strategy for retries"
    )
    base_delay: Optional[float] = Field(
        default=None,
        ge=0.1,
        le=60.0,
        description="Base delay in seconds for retry backoff (0.1-60)"
    )
    max_delay: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=300.0,
        description="Maximum delay in seconds between retries (1-300)"
    )


class RateLimitSettings(BaseModel):
    """Rate limiting configuration settings."""
    
    enabled: Optional[bool] = Field(
        default=None,
        description="Enable or disable rate limiting"
    )
    requests: Optional[int] = Field(
        default=None,
        ge=1,
        le=10000,
        description="Maximum requests per time window (1-10000)"
    )
    period: Optional[int] = Field(
        default=None,
        ge=1,
        le=3600,
        description="Time window in seconds (1-3600)"
    )
    ingest_requests: Optional[int] = Field(
        default=None,
        ge=1,
        le=10000,
        description="Maximum requests for /ingest endpoint (1-10000)"
    )
    actions_requests: Optional[int] = Field(
        default=None,
        ge=1,
        le=10000,
        description="Maximum requests for /actions endpoint (1-10000)"
    )


class PolicySettings(BaseModel):
    """Policy runner configuration settings."""
    
    enabled: Optional[bool] = Field(
        default=None,
        description="Enable or disable policy runner"
    )
    interval: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=3600.0,
        description="Policy evaluation interval in seconds (1-3600)"
    )
    batch_size: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000,
        description="Metrics batch size per evaluation (1-1000)"
    )


class SettingsSchema(BaseModel):
    """Complete settings schema for frontend configuration."""
    
    # Logging
    log_level: Optional[LogLevel] = Field(
        default=None,
        description="Application log level"
    )
    
    # Environment
    environment: Optional[Environment] = Field(
        default=None,
        description="Deployment environment"
    )
    
    # Debug mode
    debug: Optional[bool] = Field(
        default=None,
        description="Enable debug mode"
    )
    
    # Agent settings
    agent_interval: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=3600.0,
        description="Agent metrics collection interval in seconds (1-3600)"
    )
    
    # GitOps settings
    gitopsd_interval: Optional[float] = Field(
        default=None,
        ge=1.0,
        le=3600.0,
        description="GitOps drift check interval in seconds (1-3600)"
    )
    
    # Metrics
    metrics_enabled: Optional[bool] = Field(
        default=None,
        description="Enable Prometheus metrics collection"
    )
    
    # Audit logging
    audit_logging_enabled: Optional[bool] = Field(
        default=None,
        description="Enable audit logging"
    )
    
    # Nested settings
    remediation: Optional[RemediationSettings] = Field(
        default=None,
        description="Remediation service settings"
    )
    
    retry: Optional[RetrySettings] = Field(
        default=None,
        description="Retry configuration settings"
    )
    
    rate_limit: Optional[RateLimitSettings] = Field(
        default=None,
        description="Rate limiting settings"
    )
    
    policy: Optional[PolicySettings] = Field(
        default=None,
        description="Policy runner settings"
    )

    class Config:
        use_enum_values = True


class SettingsResponse(BaseModel):
    """Response model for settings retrieval."""
    
    settings: SettingsSchema
    updated_at: Optional[datetime] = None
    source: str = Field(description="Source of settings: 'database' or 'defaults'")


class SettingsUpdateRequest(BaseModel):
    """Request model for updating settings."""
    
    settings: SettingsSchema


class SettingsUpdateResponse(BaseModel):
    """Response model for settings update."""
    
    success: bool
    message: str
    settings: SettingsSchema
    updated_at: datetime
    reload_applied: bool = Field(description="Whether config was reloaded in memory")


# --- In-Memory Settings Cache ---

_settings_cache: Dict[str, Any] = {}
_cache_updated_at: Optional[datetime] = None


def get_settings_cache() -> Dict[str, Any]:
    """Get the current in-memory settings cache."""
    return _settings_cache.copy()


def update_settings_cache(settings: Dict[str, Any]) -> None:
    """Update the in-memory settings cache."""
    global _settings_cache, _cache_updated_at
    _settings_cache = settings.copy()
    _cache_updated_at = datetime.utcnow()
    logger.info("Settings cache updated", extra={"updated_at": _cache_updated_at})


def clear_settings_cache() -> None:
    """Clear the in-memory settings cache."""
    global _settings_cache, _cache_updated_at
    _settings_cache = {}
    _cache_updated_at = None


# --- Settings Mapping Utilities ---

# Mapping from API settings keys to environment/config keys
SETTINGS_KEY_MAP = {
    "log_level": "LOG_LEVEL",
    "environment": "ENVIRONMENT",
    "debug": "DEBUG",
    "agent_interval": "AGENT_INTERVAL",
    "gitopsd_interval": "GITOPSD_INTERVAL",
    "metrics_enabled": "METRICS_ENABLED",
    "audit_logging_enabled": "AUDIT_LOGGING_ENABLED",
    "remediation.remediator_url": "REMEDIATOR_URL",
    "remediation.max_concurrent": "REMEDIATION_MAX_CONCURRENT",
    "remediation.task_queue_size": "REMEDIATION_TASK_QUEUE_SIZE",
    "remediation.interval": "REMEDIATION_INTERVAL",
    "retry.max_attempts": "RETRY_MAX_ATTEMPTS",
    "retry.backoff": "RETRY_BACKOFF",
    "retry.base_delay": "RETRY_BASE_DELAY",
    "retry.max_delay": "RETRY_MAX_DELAY",
    "rate_limit.enabled": "RATE_LIMIT_ENABLED",
    "rate_limit.requests": "RATE_LIMIT_REQUESTS",
    "rate_limit.period": "RATE_LIMIT_PERIOD",
    "rate_limit.ingest_requests": "RATE_LIMIT_INGEST_REQUESTS",
    "rate_limit.actions_requests": "RATE_LIMIT_ACTIONS_REQUESTS",
    "policy.enabled": "POLICY_RUNNER_ENABLED",
    "policy.interval": "POLICY_RUNNER_INTERVAL",
    "policy.batch_size": "POLICY_RUNNER_BATCH_SIZE",
}


def flatten_settings(settings: SettingsSchema) -> Dict[str, Any]:
    """Flatten nested settings into dot-notation keys."""
    flat = {}
    data = settings.dict(exclude_none=True)
    
    for key, value in data.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if nested_value is not None:
                    flat[f"{key}.{nested_key}"] = nested_value
        else:
            flat[key] = value
    
    return flat


def unflatten_settings(flat: Dict[str, Any]) -> Dict[str, Any]:
    """Unflatten dot-notation keys back into nested structure."""
    result: Dict[str, Any] = {}
    
    for key, value in flat.items():
        parts = key.split(".")
        current = result
        
        for i, part in enumerate(parts[:-1]):
            if part not in current:
                current[part] = {}
            current = current[part]
        
        current[parts[-1]] = value
    
    return result


def get_value_type(value: Any) -> str:
    """Determine the type string for a value."""
    if isinstance(value, bool):
        return "boolean"
    elif isinstance(value, int):
        return "integer"
    elif isinstance(value, float):
        return "float"
    else:
        return "string"


def convert_value(value: str, value_type: str) -> Any:
    """Convert a string value back to its proper type."""
    if value_type == "boolean":
        return value.lower() in ("true", "1", "yes")
    elif value_type == "integer":
        return int(value)
    elif value_type == "float":
        return float(value)
    else:
        return value


# --- Helper Functions ---

async def load_settings_from_db(db: AsyncSession) -> Dict[str, Any]:
    """Load all settings from the database."""
    try:
        result = await db.execute(select(Setting))
        settings_rows = result.scalars().all()
        
        flat_settings = {}
        for row in settings_rows:
            flat_settings[row.key] = convert_value(row.value, row.value_type)
        
        return unflatten_settings(flat_settings)
    except SQLAlchemyError as e:
        logger.error(f"Failed to load settings from database: {e}")
        raise


async def save_settings_to_db(db: AsyncSession, settings: SettingsSchema) -> datetime:
    """Save settings to the database."""
    try:
        flat_settings = flatten_settings(settings)
        now = datetime.utcnow()
        
        for key, value in flat_settings.items():
            # Check if setting exists
            result = await db.execute(
                select(Setting).where(Setting.key == key)
            )
            existing = result.scalar_one_or_none()
            
            value_type = get_value_type(value)
            value_str = str(value).lower() if isinstance(value, bool) else str(value)
            
            if existing:
                existing.value = value_str
                existing.value_type = value_type
                existing.updated_at = now
            else:
                new_setting = Setting(
                    key=key,
                    value=value_str,
                    value_type=value_type,
                    description=f"Setting for {SETTINGS_KEY_MAP.get(key, key)}",
                    updated_at=now
                )
                db.add(new_setting)
        
        await db.commit()
        return now
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Failed to save settings to database: {e}")
        raise


def get_current_settings_from_config() -> SettingsSchema:
    """Get current settings from the application config."""
    config = get_settings()
    
    return SettingsSchema(
        log_level=LogLevel(config.LOG_LEVEL) if config.LOG_LEVEL in [e.value for e in LogLevel] else None,
        environment=Environment(config.ENVIRONMENT) if config.ENVIRONMENT in [e.value for e in Environment] else None,
        debug=config.DEBUG,
        agent_interval=config.AGENT_INTERVAL,
        gitopsd_interval=config.GITOPSD_INTERVAL,
        metrics_enabled=config.METRICS_ENABLED,
        audit_logging_enabled=config.AUDIT_LOGGING_ENABLED,
        remediation=RemediationSettings(
            remediator_url=config.REMEDIATOR_URL,
        ),
        retry=RetrySettings(
            max_attempts=config.RETRY_MAX_ATTEMPTS,
            backoff=BackoffStrategy(config.RETRY_BACKOFF) if config.RETRY_BACKOFF in [e.value for e in BackoffStrategy] else None,
            base_delay=config.RETRY_BASE_DELAY,
            max_delay=config.RETRY_MAX_DELAY,
        ),
        rate_limit=RateLimitSettings(
            enabled=config.RATE_LIMIT_ENABLED,
            requests=config.RATE_LIMIT_REQUESTS,
            period=config.RATE_LIMIT_PERIOD,
            ingest_requests=config.RATE_LIMIT_INGEST_REQUESTS,
            actions_requests=config.RATE_LIMIT_ACTIONS_REQUESTS,
        ),
        policy=PolicySettings(
            enabled=config.POLICY_RUNNER_ENABLED,
            interval=config.POLICY_RUNNER_INTERVAL,
            batch_size=config.POLICY_RUNNER_BATCH_SIZE,
        ),
    )


def apply_settings_to_memory(settings: SettingsSchema) -> bool:
    """
    Apply settings changes to in-memory configuration.
    Returns True if settings were applied successfully.
    """
    try:
        # Update the settings cache
        flat_settings = flatten_settings(settings)
        update_settings_cache(flat_settings)
        
        # Apply runtime overrides for immediate effect
        for key, value in flat_settings.items():
            config_key = SETTINGS_KEY_MAP.get(key)
            if config_key:
                set_runtime_override(config_key, value)
        
        # Trigger config reload to pick up new values
        # Note: This reloads from env/yaml, but our runtime overrides take precedence
        reload_settings()
        
        logger.info("Settings applied to memory", extra={
            "settings_count": len(flat_settings)
        })
        return True
    except Exception as e:
        logger.error(f"Failed to apply settings to memory: {e}")
        return False


# --- API Endpoints ---

@router.get(
    "",
    response_model=SettingsResponse,
    summary="Get current settings",
    description="Retrieve the current application settings from the database or defaults."
)
async def get_all_settings(
    db: AsyncSession = Depends(get_db)
) -> SettingsResponse:
    """
    Get current application settings.
    
    Returns settings from the database if available, otherwise returns defaults
    from the application configuration.
    """
    try:
        # Try to load from database first
        db_settings = await load_settings_from_db(db)
        
        if db_settings:
            # Get the latest update timestamp
            result = await db.execute(
                select(Setting.updated_at).order_by(Setting.updated_at.desc()).limit(1)
            )
            latest_update = result.scalar_one_or_none()
            
            settings = SettingsSchema(**db_settings)
            
            # Merge with defaults for any missing values
            default_settings = get_current_settings_from_config()
            merged = merge_settings(default_settings, settings)
            
            return SettingsResponse(
                settings=merged,
                updated_at=latest_update,
                source="database"
            )
        else:
            # Return defaults from config
            settings = get_current_settings_from_config()
            return SettingsResponse(
                settings=settings,
                updated_at=None,
                source="defaults"
            )
            
    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching settings: {e}")
        # Fallback to config defaults
        settings = get_current_settings_from_config()
        return SettingsResponse(
            settings=settings,
            updated_at=None,
            source="defaults"
        )


@router.put(
    "",
    response_model=SettingsUpdateResponse,
    summary="Update settings",
    description="Update application settings and persist to database."
)
async def update_settings(
    request: SettingsUpdateRequest,
    db: AsyncSession = Depends(get_db)
) -> SettingsUpdateResponse:
    """
    Update application settings.
    
    Validates the settings, persists them to the database, and applies
    changes to the running application without requiring a restart.
    """
    try:
        settings = request.settings
        
        # Validate cross-field constraints
        validate_settings_constraints(settings)
        
        # Save to database
        updated_at = await save_settings_to_db(db, settings)
        
        # Apply to memory for immediate effect
        reload_applied = apply_settings_to_memory(settings)
        
        # Get the merged settings (with defaults)
        default_settings = get_current_settings_from_config()
        merged = merge_settings(default_settings, settings)
        
        logger.info("Settings updated successfully", extra={
            "updated_at": updated_at.isoformat(),
            "reload_applied": reload_applied
        })
        
        return SettingsUpdateResponse(
            success=True,
            message="Settings updated successfully",
            settings=merged,
            updated_at=updated_at,
            reload_applied=reload_applied
        )
        
    except ValueError as e:
        logger.warning(f"Settings validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
    except SQLAlchemyError as e:
        logger.error(f"Database error while updating settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist settings to database"
        )
    except Exception as e:
        logger.error(f"Unexpected error updating settings: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred"
        )


@router.delete(
    "",
    summary="Reset settings to defaults",
    description="Remove all custom settings and revert to application defaults."
)
async def reset_settings(
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Reset all settings to application defaults.
    
    Removes all custom settings from the database and clears the in-memory cache.
    """
    try:
        # Delete all settings from database
        await db.execute(delete(Setting))
        await db.commit()
        
        # Clear the in-memory cache
        clear_settings_cache()
        
        # Clear runtime overrides
        clear_runtime_overrides()
        
        # Reload config to reset to defaults
        reload_settings()
        
        logger.info("Settings reset to defaults")
        
        return {
            "success": True,
            "message": "Settings reset to defaults",
            "settings": get_current_settings_from_config().dict(exclude_none=True)
        }
        
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"Database error while resetting settings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset settings"
        )


@router.get(
    "/schema",
    summary="Get settings schema",
    description="Get the JSON schema for settings validation."
)
async def get_settings_schema() -> Dict[str, Any]:
    """
    Get the JSON schema for settings.
    
    Useful for frontend form generation and validation.
    """
    return SettingsSchema.schema()


# --- Validation Functions ---

def validate_settings_constraints(settings: SettingsSchema) -> None:
    """
    Validate cross-field constraints that can't be expressed in Pydantic.
    Raises ValueError if validation fails.
    """
    # Validate retry settings consistency
    if settings.retry:
        if settings.retry.base_delay and settings.retry.max_delay:
            if settings.retry.base_delay > settings.retry.max_delay:
                raise ValueError(
                    "retry.base_delay cannot be greater than retry.max_delay"
                )
    
    # Validate rate limit settings consistency
    if settings.rate_limit:
        if settings.rate_limit.requests and settings.rate_limit.period:
            # Warn if rate limit seems too restrictive
            if settings.rate_limit.requests < 10 and settings.rate_limit.period > 60:
                logger.warning(
                    "Rate limit settings are very restrictive",
                    extra={
                        "requests": settings.rate_limit.requests,
                        "period": settings.rate_limit.period
                    }
                )


def merge_settings(defaults: SettingsSchema, overrides: SettingsSchema) -> SettingsSchema:
    """
    Merge override settings with defaults.
    Override values take precedence over defaults.
    """
    defaults_dict = defaults.dict()
    overrides_dict = overrides.dict(exclude_none=True)
    
    def deep_merge(base: dict, override: dict) -> dict:
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    merged = deep_merge(defaults_dict, overrides_dict)
    return SettingsSchema(**merged)
