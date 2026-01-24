"""Simulator API endpoints for generating synthetic metrics and testing system behavior."""

from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, validator

from app.core.logger import get_logger
from app.core.config import get_settings
from app.services.simulator import get_simulator, SimulatorMode

logger = get_logger(__name__)
settings = get_settings()

# Create router with /simulator prefix
router = APIRouter(
    prefix="/simulator",
    tags=["simulator"],
    responses={
        400: {"description": "Invalid request"},
        403: {"description": "Simulator not allowed in production"},
        500: {"description": "Internal server error"},
    },
)


# --- Enums ---

class SimulationModeEnum(str, Enum):
    """Simulation mode options."""
    STEADY = "steady"
    BURST = "burst"
    RAMP = "ramp"
    CHAOS = "chaos"


# --- Pydantic Models ---

class SimulatorStartRequest(BaseModel):
    """Request model for starting the simulator."""
    
    rate: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Metrics ingested per minute (1-10000)"
    )
    mode: SimulationModeEnum = Field(
        default=SimulationModeEnum.STEADY,
        description="Simulation mode: steady, burst, ramp, chaos"
    )
    failure_percent: float = Field(
        default=5.0,
        ge=0.0,
        le=100.0,
        alias="failure_rate",
        description="Percentage of events that should fail (0-100)"
    )
    timeout_percent: float = Field(
        default=2.0,
        ge=0.0,
        le=100.0,
        alias="timeout_rate",
        description="Percentage of events that should timeout (0-100)"
    )
    malformed_percent: float = Field(
        default=1.0,
        ge=0.0,
        le=100.0,
        alias="malformed_rate",
        description="Percentage of events that should be malformed (0-100)"
    )

    class Config:
        populate_by_name = True
        schema_extra = {
            "example": {
                "rate": 100,
                "mode": "steady",
                "failure_percent": 5.0,
                "timeout_percent": 2.0,
                "malformed_percent": 1.0
            }
        }


class SimulatorStartResponse(BaseModel):
    """Response model for simulator start."""
    
    ok: bool = Field(default=True, description="Success flag")
    message: str = Field(description="Status message")
    running: bool = Field(description="Whether simulator is running")
    configuration: Dict[str, Any] = Field(description="Active configuration")


class SimulatorStopResponse(BaseModel):
    """Response model for simulator stop."""
    
    ok: bool = Field(default=True, description="Success flag")
    message: str = Field(description="Status message")
    running: bool = Field(default=False, description="Whether simulator is running")
    summary: Dict[str, Any] = Field(description="Run summary statistics")


class RuntimeStats(BaseModel):
    """Runtime statistics for the simulator."""
    
    total_events: int = Field(default=0, description="Total events generated")
    success_count: int = Field(default=0, description="Successful events")
    success_rate: float = Field(default=100.0, description="Success rate percentage")
    failures: int = Field(default=0, description="Failed events")
    timeouts: int = Field(default=0, description="Timed out events")
    malformed: int = Field(default=0, description="Malformed events")
    rate_limited: int = Field(default=0, description="Rate limited events")
    uptime_seconds: float = Field(default=0.0, description="Runtime in seconds")
    actual_rate: float = Field(default=0.0, description="Actual events per minute")


class SimulatorStatusResponse(BaseModel):
    """Response model for simulator status."""
    
    running: bool = Field(description="Whether simulator is running")
    started_at: Optional[str] = Field(default=None, description="Start timestamp")
    configuration: Dict[str, Any] = Field(description="Current configuration")
    stats: RuntimeStats = Field(description="Runtime statistics")
    last_event_at: Optional[str] = Field(default=None, description="Last event timestamp")


class FrontendSimulatorStatus(BaseModel):
    """Flat response model matching frontend SimulatorStatus interface."""
    
    running: bool = Field(description="Whether simulator is running")
    rate: int = Field(default=0, description="Current rate (events per minute)")
    mode: str = Field(default="steady", description="Simulation mode")
    events_generated: int = Field(default=0, description="Total events generated")
    events_succeeded: int = Field(default=0, description="Successful events")
    events_failed: int = Field(default=0, description="Failed events")
    events_rate_limited: int = Field(default=0, description="Rate limited events")
    events_timeout: int = Field(default=0, description="Timed out events")
    events_malformed: int = Field(default=0, description="Malformed events")
    started_at: Optional[str] = Field(default=None, description="Start timestamp")
    last_event_at: Optional[str] = Field(default=None, description="Last event timestamp")
    uptime_seconds: float = Field(default=0.0, description="Runtime in seconds")


# --- Helper Functions ---

def check_production_guardrail():
    """
    Check if simulator is allowed in current environment.
    Raises HTTPException if in production mode.
    """
    if settings.ENVIRONMENT == "production":
        logger.warning(
            "Simulator access denied in production",
            extra={"environment": settings.ENVIRONMENT}
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Simulator is disabled in production environment. "
                   "Set ENVIRONMENT to 'development' or 'staging' to use the simulator."
        )


# --- API Endpoints ---

@router.post(
    "/start",
    response_model=SimulatorStartResponse,
    summary="Start the simulator",
    description="Start generating synthetic metrics at the configured rate and mode"
)
async def start_simulator(
    request: SimulatorStartRequest
) -> SimulatorStartResponse:
    """
    Start the load simulator.
    
    This endpoint starts the simulator which generates synthetic metrics
    and pushes them through the ingestion pipeline. The simulator supports
    different modes and can inject various types of failures for testing.
    
    **Modes:**
    - `steady`: Constant rate of events
    - `burst`: Periodic spikes in event rate
    - `ramp`: Gradually increasing rate
    - `chaos`: Random/unpredictable behavior
    
    **Safety:**
    - Only available in non-production environments
    - Metrics are tagged with `simulator=true`
    
    Args:
        request: Simulator configuration parameters
        
    Returns:
        SimulatorStartResponse with configuration and status
    """
    # Production guardrail
    check_production_guardrail()
    
    try:
        simulator = get_simulator()
        
        # Check if already running
        if simulator.running:
            logger.warning("Attempt to start simulator that is already running")
            return SimulatorStartResponse(
                ok=True,
                message="Simulator is already running",
                running=True,
                configuration={
                    "rate": simulator.target_rate,
                    "mode": simulator.mode.value,
                    "failure_percent": simulator.failure_rate * 100,
                    "timeout_percent": simulator.timeout_rate * 100,
                    "malformed_percent": simulator.malformed_rate * 100,
                }
            )
        
        # Map mode enum
        mode_map = {
            SimulationModeEnum.STEADY: SimulatorMode.STEADY,
            SimulationModeEnum.BURST: SimulatorMode.BURST,
            SimulationModeEnum.RAMP: SimulatorMode.RAMP,
            SimulationModeEnum.CHAOS: SimulatorMode.CHAOS,
        }
        
        # Configure simulator
        simulator.configure(
            rate=request.rate,
            mode=mode_map[request.mode],
            failure_rate=request.failure_percent / 100.0,
            timeout_rate=request.timeout_percent / 100.0,
            malformed_rate=request.malformed_percent / 100.0,
        )
        
        # Start simulator
        await simulator.start()
        
        logger.info(
            "Simulator started via API",
            extra={
                "rate": request.rate,
                "mode": request.mode.value,
                "failure_percent": request.failure_percent,
                "timeout_percent": request.timeout_percent,
                "malformed_percent": request.malformed_percent,
            }
        )
        
        return SimulatorStartResponse(
            ok=True,
            message="Simulator started successfully",
            running=True,
            configuration={
                "rate": request.rate,
                "mode": request.mode.value,
                "failure_percent": request.failure_percent,
                "timeout_percent": request.timeout_percent,
                "malformed_percent": request.malformed_percent,
            }
        )
        
    except Exception as e:
        logger.error(
            f"Failed to start simulator: {e}",
            exc_info=True,
            extra={"error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start simulator: {str(e)}"
        )


@router.post(
    "/stop",
    response_model=SimulatorStopResponse,
    summary="Stop the simulator",
    description="Stop the simulator and return run summary"
)
async def stop_simulator() -> SimulatorStopResponse:
    """
    Stop the load simulator.
    
    Gracefully stops the simulator, cancels background tasks, and returns
    a summary of the simulation run including total events, success rate,
    and failure breakdown.
    
    Returns:
        SimulatorStopResponse with run summary
    """
    # Production guardrail
    check_production_guardrail()
    
    try:
        simulator = get_simulator()
        
        # Check if running
        if not simulator.running:
            return SimulatorStopResponse(
                ok=True,
                message="Simulator is not running",
                running=False,
                summary={
                    "total_events": simulator.events_generated,
                    "events_succeeded": simulator.events_succeeded,
                    "events_failed": simulator.events_failed,
                    "events_timeout": simulator.events_timeout,
                    "events_malformed": simulator.events_malformed,
                    "events_rate_limited": simulator.events_rate_limited,
                }
            )
        
        # Get stats before stopping
        status_before = simulator.get_status()
        
        # Stop simulator
        await simulator.stop()
        
        logger.info(
            "Simulator stopped via API",
            extra={
                "total_events": simulator.events_generated,
                "success_rate": (
                    (simulator.events_succeeded / simulator.events_generated * 100)
                    if simulator.events_generated > 0 else 100.0
                ),
            }
        )
        
        return SimulatorStopResponse(
            ok=True,
            message="Simulator stopped successfully",
            running=False,
            summary={
                "runtime_seconds": status_before.get("runtime_seconds", 0),
                "total_events": simulator.events_generated,
                "events_succeeded": simulator.events_succeeded,
                "events_failed": simulator.events_failed,
                "events_timeout": simulator.events_timeout,
                "events_malformed": simulator.events_malformed,
                "events_rate_limited": simulator.events_rate_limited,
                "success_rate": (
                    round(simulator.events_succeeded / simulator.events_generated * 100, 2)
                    if simulator.events_generated > 0 else 100.0
                ),
                "actual_rate": status_before.get("metrics", {}).get("actual_rate", 0),
            }
        )
        
    except Exception as e:
        logger.error(
            f"Failed to stop simulator: {e}",
            exc_info=True,
            extra={"error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop simulator: {str(e)}"
        )


@router.get(
    "/status",
    response_model=FrontendSimulatorStatus,
    summary="Get simulator status",
    description="Get current simulator state and runtime statistics"
)
async def get_simulator_status() -> FrontendSimulatorStatus:
    """
    Get the current simulator status and runtime statistics.
    
    Returns a flat structure matching the frontend SimulatorStatus interface:
    - Running state
    - Configuration (rate, mode)
    - Event counts (generated, succeeded, failed, etc.)
    - Uptime information
    
    Returns:
        FrontendSimulatorStatus with current state and stats
    """
    # Production guardrail - but allow read access with warning
    if settings.ENVIRONMENT == "production":
        logger.debug("Simulator status checked in production")
    
    try:
        simulator = get_simulator()
        status_data = simulator.get_status()
        
        # Extract mode value
        mode = status_data["configuration"]["mode"]
        mode_str = mode.value if hasattr(mode, 'value') else str(mode)
        
        return FrontendSimulatorStatus(
            running=status_data["running"],
            rate=status_data["configuration"]["target_rate"],
            mode=mode_str,
            events_generated=status_data["metrics"]["events_generated"],
            events_succeeded=status_data["metrics"]["events_succeeded"],
            events_failed=status_data["metrics"]["events_failed"],
            events_rate_limited=status_data["metrics"]["events_rate_limited"],
            events_timeout=status_data["metrics"]["events_timeout"],
            events_malformed=status_data["metrics"]["events_malformed"],
            started_at=status_data["started_at"],
            last_event_at=status_data["last_event_at"],
            uptime_seconds=round(status_data["runtime_seconds"], 2),
        )
        
    except Exception as e:
        logger.error(
            f"Failed to get simulator status: {e}",
            exc_info=True,
            extra={"error": str(e)}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get simulator status: {str(e)}"
        )


@router.get(
    "/health",
    summary="Simulator health check",
    description="Check if the simulator service is operational"
)
async def simulator_health() -> Dict[str, Any]:
    """Health check for simulator service."""
    simulator = get_simulator()
    return {
        "status": "healthy",
        "service": "simulator",
        "running": simulator.running,
        "environment": settings.ENVIRONMENT,
        "production_blocked": settings.ENVIRONMENT == "production",
    }
