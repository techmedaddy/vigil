"""
Utility functions for Vigil monitoring system.

Provides:
- Retry decorator with exponential backoff
- Helper functions for common operations
"""

import asyncio
import functools
import time
from typing import Callable, Optional, Tuple, Type
from datetime import datetime

from app.core.logger import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)


def retry(
    max_attempts: Optional[int] = None,
    backoff_strategy: str = "exponential",
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    log_retries: bool = True,
):
    """
    Decorator that retries a function on failure with configurable backoff.

    Supports both sync and async functions. Uses exponential backoff by default.

    Args:
        max_attempts: Maximum number of retry attempts (None uses config default)
        backoff_strategy: Strategy for retry delays ('exponential', 'linear', 'constant')
        base_delay: Base delay in seconds for backoff calculation
        max_delay: Maximum delay between retries in seconds
        exponential_base: Base for exponential backoff (default 2.0)
        exceptions: Tuple of exception types to catch and retry
        log_retries: Whether to log retry attempts

    Returns:
        Decorated function with retry logic

    Example:
        @retry(max_attempts=3, backoff_strategy="exponential")
        async def fetch_data():
            # Database or API call
            pass
    """
    def decorator(func: Callable):
        # Determine if function is async
        is_async = asyncio.iscoroutinefunction(func)

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            settings = get_settings()
            attempts = max_attempts if max_attempts is not None else settings.RETRY_MAX_ATTEMPTS
            
            last_exception = None
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == attempts:
                        if log_retries:
                            logger.error(
                                f"Function {func.__name__} failed after {attempts} attempts",
                                extra={
                                    "function": func.__name__,
                                    "attempts": attempts,
                                    "error": str(e),
                                    "error_type": type(e).__name__,
                                }
                            )
                        raise
                    
                    # Calculate delay based on strategy
                    delay = calculate_delay(
                        attempt, 
                        backoff_strategy, 
                        base_delay, 
                        exponential_base, 
                        max_delay
                    )
                    
                    if log_retries:
                        logger.warning(
                            f"Function {func.__name__} failed, retrying in {delay:.2f}s",
                            extra={
                                "function": func.__name__,
                                "attempt": attempt,
                                "max_attempts": attempts,
                                "delay": delay,
                                "error": str(e),
                                "error_type": type(e).__name__,
                            }
                        )
                    
                    await asyncio.sleep(delay)
            
            # Should never reach here, but just in case
            if last_exception:
                raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            settings = get_settings()
            attempts = max_attempts if max_attempts is not None else settings.RETRY_MAX_ATTEMPTS
            
            last_exception = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == attempts:
                        if log_retries:
                            logger.error(
                                f"Function {func.__name__} failed after {attempts} attempts",
                                extra={
                                    "function": func.__name__,
                                    "attempts": attempts,
                                    "error": str(e),
                                    "error_type": type(e).__name__,
                                }
                            )
                        raise
                    
                    # Calculate delay based on strategy
                    delay = calculate_delay(
                        attempt, 
                        backoff_strategy, 
                        base_delay, 
                        exponential_base, 
                        max_delay
                    )
                    
                    if log_retries:
                        logger.warning(
                            f"Function {func.__name__} failed, retrying in {delay:.2f}s",
                            extra={
                                "function": func.__name__,
                                "attempt": attempt,
                                "max_attempts": attempts,
                                "delay": delay,
                                "error": str(e),
                                "error_type": type(e).__name__,
                            }
                        )
                    
                    time.sleep(delay)
            
            # Should never reach here, but just in case
            if last_exception:
                raise last_exception

        return async_wrapper if is_async else sync_wrapper
    
    return decorator


def calculate_delay(
    attempt: int,
    strategy: str,
    base_delay: float,
    exponential_base: float,
    max_delay: float
) -> float:
    """
    Calculate retry delay based on the backoff strategy.

    Args:
        attempt: Current attempt number (1-indexed)
        strategy: Backoff strategy ('exponential', 'linear', 'constant')
        base_delay: Base delay in seconds
        exponential_base: Base for exponential calculation
        max_delay: Maximum allowed delay

    Returns:
        Delay in seconds
    """
    if strategy == "exponential":
        delay = base_delay * (exponential_base ** (attempt - 1))
    elif strategy == "linear":
        delay = base_delay * attempt
    elif strategy == "constant":
        delay = base_delay
    else:
        logger.warning(f"Unknown backoff strategy '{strategy}', using constant")
        delay = base_delay
    
    # Cap at max_delay
    return min(delay, max_delay)


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds to a human-readable string.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "2.5s", "1m 30s")
    """
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.0f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def sanitize_tags(tags: dict) -> dict:
    """
    Sanitize tags dictionary by removing invalid characters and ensuring valid types.

    Args:
        tags: Dictionary of tags

    Returns:
        Sanitized tags dictionary
    """
    if not tags:
        return {}
    
    sanitized = {}
    for key, value in tags.items():
        # Convert key and value to strings
        key_str = str(key).strip()
        value_str = str(value).strip()
        
        # Skip empty keys or values
        if not key_str or not value_str:
            continue
        
        # Remove special characters from keys (only allow alphanumeric, underscore, dash)
        key_clean = ''.join(c for c in key_str if c.isalnum() or c in ('_', '-'))
        
        if key_clean:
            sanitized[key_clean] = value_str
    
    return sanitized
