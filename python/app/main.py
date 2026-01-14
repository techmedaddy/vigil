"""
Vigil Monitoring System - FastAPI Application Entrypoint

Lightweight application factory that:
- Initializes configuration and logging
- Sets up database connections
- Registers API routers
- Configures middleware and startup/shutdown events
- Manages background tasks (agent, gitopsd)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from contextlib import asynccontextmanager

from python.app.core.config import get_settings
from python.app.core.logger import get_logger, configure_logging
from python.app.core.db import init_db, close_db, get_db_manager
from python.app.core.middleware import register_middleware
from python.app.core.tasks import start_all_background_tasks, cancel_all_background_tasks
from python.app.api.v1.ingest import router as ingest_router
from python.app.api.v1.actions import router as actions_router
from python.app.api.v1.ui import router as ui_router, mount_static_files

# Import policies router if available
try:
    from python.app.api.v1.policies import router as policies_router
    policies_router_available = True
except ImportError:
    policies_router_available = False

# Import metrics if available
try:
    from python.app.core import metrics
    metrics_available = True
except ImportError:
    metrics_available = False

# Import policy engine
try:
    from python.app.core.policy import initialize_policies
    policy_engine_available = True
except ImportError:
    policy_engine_available = False

# Import policy runner
try:
    from python.app.core.policy_runner import start_policy_runner, stop_policy_runner
    policy_runner_available = True
except ImportError:
    policy_runner_available = False

# Initialize logging
configure_logging()
logger = get_logger(__name__)

# Get configuration
settings = get_settings()


# --- Startup/Shutdown Events ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifecycle.
    
    Startup:
    - Initialize database and create tables
    - Start background tasks (agent, gitopsd)
    - Log startup information
    
    Shutdown:
    - Cancel background tasks
    - Close database connections
    - Clean up resources
    """
    # Startup
    logger.info(
        "Application starting",
        environment=settings.ENVIRONMENT,
        service=settings.SERVICE_NAME,
        version=settings.API_VERSION,
        database_url=settings.DATABASE_URL.split("://")[0]  # Log DB type only
    )
    
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(
            "Database initialization failed",
            error=str(e),
            exc_info=True
        )
        raise
    
    # Initialize policy engine
    if policy_engine_available:
        try:
            initialize_policies()
            logger.info("Policy engine initialized")
        except Exception as e:
            logger.warning(
                "Policy engine initialization failed",
                error=str(e),
                exc_info=True
            )
    
    # Start policy runner
    if policy_runner_available:
        try:
            await start_policy_runner()
            logger.info("Policy runner started")
        except Exception as e:
            logger.warning(
                "Policy runner startup failed",
                error=str(e),
                exc_info=True
            )
    
    # Start background tasks
    try:
        await start_all_background_tasks()
        logger.info("Background tasks initialized")
    except Exception as e:
        logger.error(
            "Failed to start background tasks",
            error=str(e),
            exc_info=True
        )
    
    yield
    
    # Shutdown
    logger.info("Application shutting down")
    
    # Stop policy runner
    if policy_runner_available:
        try:
            await stop_policy_runner()
            logger.info("Policy runner stopped")
        except Exception as e:
            logger.error(
                "Error stopping policy runner",
                error=str(e),
                exc_info=True
            )
    
    try:
        await cancel_all_background_tasks()
        logger.info("Background tasks cancelled")
    except Exception as e:
        logger.error(
            "Error cancelling background tasks",
            error=str(e),
            exc_info=True
        )
    
    try:
        await close_db()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(
            "Error during shutdown",
            error=str(e),
            exc_info=True
        )


# --- FastAPI Application ---

app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    lifespan=lifespan,
)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Register Custom Middleware ---
register_middleware(app)

# --- Mount Static Files ---
mount_static_files(app)

# --- Metrics Endpoint ---
if metrics_available and settings.METRICS_ENABLED:
    @app.get(settings.METRICS_ENDPOINT, include_in_schema=False)
    async def get_metrics():
        """
        Expose Prometheus metrics in text format.

        This endpoint returns metrics collected by the application for monitoring
        with Prometheus or compatible tools.
        """
        return Response(
            content=metrics.get_metrics(),
            media_type=metrics.get_metrics_content_type(),
        )

    logger.info(
        "Prometheus metrics endpoint registered",
        endpoint=settings.METRICS_ENDPOINT,
    )

# --- Include Routers ---
app.include_router(ingest_router, prefix="/api/v1")
app.include_router(actions_router, prefix="/api/v1")
app.include_router(ui_router, prefix="/api/v1")

if policies_router_available:
    app.include_router(policies_router, prefix="/api/v1")

logger.info(
    "Application initialized",
    routers=["ingest", "actions", "ui", "policies"] if policies_router_available else ["ingest", "actions", "ui"],
    background_tasks=["agent", "gitopsd"]
)
