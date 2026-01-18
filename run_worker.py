#!/usr/bin/env python3
"""
Standalone worker script for Vigil remediation queue.

Run this script to start the worker that processes remediation tasks from Redis.

Usage:
    python run_worker.py

Environment Variables:
    REDIS_URL - Redis connection URL (default: redis://localhost:6379/0)
    REMEDIATOR_URL - Remediator service URL (default: http://localhost:8081)
"""

import asyncio
import sys
import signal
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent / "python"))

from app.services.worker import start_worker
from app.core.logger import get_logger

logger = get_logger(__name__)


def handle_signal(signum, frame):
    """Handle termination signals gracefully."""
    logger.info(f"Received signal {signum}, shutting down worker...")
    sys.exit(0)


def main():
    """Main entry point for worker."""
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    logger.info("Starting Vigil remediation worker...")
    logger.info("Press Ctrl+C to stop")
    
    try:
        asyncio.run(start_worker())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
