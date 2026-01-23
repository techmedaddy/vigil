"""Load simulator for generating synthetic events to test system behavior."""

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from enum import Enum

import httpx
from app.core.logger import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)


class SimulatorMode(str, Enum):
    STEADY = "steady"           # Constant rate
    BURST = "burst"             # Periodic spikes
    RAMP = "ramp"               # Gradually increase
    CHAOS = "chaos"             # Random failures and spikes


class EventSeverity(str, Enum):
    NORMAL = "normal"           # 0-70% resource usage
    WARNING = "warning"         # 70-85% resource usage
    CRITICAL = "critical"       # 85-100% resource usage


class Simulator:
    """Load simulator for generating synthetic events."""
    
    def __init__(self):
        self.settings = get_settings()
        self.running = False
        self.task: Optional[asyncio.Task] = None
        
        # Metrics
        self.events_generated = 0
        self.events_succeeded = 0
        self.events_failed = 0
        self.events_rate_limited = 0
        self.events_timeout = 0
        self.events_malformed = 0
        self.started_at: Optional[datetime] = None
        self.last_event_at: Optional[datetime] = None
        
        # Configuration
        self.target_rate = 100  # events per minute
        self.mode = SimulatorMode.STEADY
        self.failure_rate = 0.0  # 0.0 to 1.0
        self.timeout_rate = 0.0
        self.malformed_rate = 0.0
        
        # API endpoint
        self.api_url = f"http://localhost:{self.settings.PORT}"
        
    def configure(
        self,
        rate: int = 100,
        mode: SimulatorMode = SimulatorMode.STEADY,
        failure_rate: float = 0.0,
        timeout_rate: float = 0.0,
        malformed_rate: float = 0.0
    ):
        """Configure simulator parameters."""
        self.target_rate = max(1, rate)
        self.mode = mode
        self.failure_rate = max(0.0, min(1.0, failure_rate))
        self.timeout_rate = max(0.0, min(1.0, timeout_rate))
        self.malformed_rate = max(0.0, min(1.0, malformed_rate))
        
        logger.info(
            "Simulator configured",
            extra={
                "event": "simulator_configured",
                "rate": self.target_rate,
                "mode": self.mode,
                "failure_rate": self.failure_rate,
                "timeout_rate": self.timeout_rate,
                "malformed_rate": self.malformed_rate,
            }
        )
    
    async def start(self):
        """Start the simulator."""
        if self.running:
            logger.warning("Simulator already running")
            return
        
        self.running = True
        self.started_at = datetime.utcnow()
        self.events_generated = 0
        self.events_succeeded = 0
        self.events_failed = 0
        self.events_rate_limited = 0
        self.events_timeout = 0
        self.events_malformed = 0
        
        logger.info(
            "Simulator started",
            extra={
                "event": "simulator_started",
                "rate": self.target_rate,
                "mode": self.mode,
            }
        )
        
        # Start background task
        self.task = asyncio.create_task(self._run())
    
    async def stop(self):
        """Stop the simulator."""
        if not self.running:
            logger.warning("Simulator not running")
            return
        
        self.running = False
        
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        runtime = (datetime.utcnow() - self.started_at).total_seconds() if self.started_at else 0
        
        logger.info(
            "Simulator stopped",
            extra={
                "event": "simulator_stopped",
                "runtime_seconds": runtime,
                "events_generated": self.events_generated,
                "events_succeeded": self.events_succeeded,
                "events_failed": self.events_failed,
                "events_rate_limited": self.events_rate_limited,
                "events_timeout": self.events_timeout,
                "events_malformed": self.events_malformed,
            }
        )
    
    def get_status(self) -> Dict:
        """Get current simulator status."""
        if self.started_at:
            runtime = (datetime.utcnow() - self.started_at).total_seconds()
            actual_rate = (self.events_generated / runtime * 60) if runtime > 0 else 0
        else:
            runtime = 0
            actual_rate = 0
        
        return {
            "running": self.running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "runtime_seconds": runtime,
            "configuration": {
                "target_rate": self.target_rate,
                "mode": self.mode,
                "failure_rate": self.failure_rate,
                "timeout_rate": self.timeout_rate,
                "malformed_rate": self.malformed_rate,
            },
            "metrics": {
                "events_generated": self.events_generated,
                "events_succeeded": self.events_succeeded,
                "events_failed": self.events_failed,
                "events_rate_limited": self.events_rate_limited,
                "events_timeout": self.events_timeout,
                "events_malformed": self.events_malformed,
                "actual_rate": round(actual_rate, 2),
            },
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
        }
    
    async def _run(self):
        """Main simulator loop"""
        try:
            while self.running:
                # Calculate delay based on mode and target rate
                delay = self._calculate_delay()
                
                # Generate and send event
                await self._generate_event()
                
                # Wait before next event
                await asyncio.sleep(delay)
                
        except asyncio.CancelledError:
            logger.info("Simulator task cancelled")
            raise
        except Exception as e:
            logger.error(
                "Simulator error",
                extra={
                    "event": "simulator_error",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
    
    def _calculate_delay(self) -> float:
        """
        Calculate delay between events based on mode.
        
        Returns:
            Delay in seconds
        """
        base_delay = 60.0 / self.target_rate  # seconds per event
        
        if self.mode == SimulatorMode.STEADY:
            return base_delay
        
        elif self.mode == SimulatorMode.BURST:
            # Alternate between high and low rates
            if random.random() < 0.1:  # 10% of time in burst
                return base_delay * 0.1  # 10x faster
            else:
                return base_delay * 1.1  # Slightly slower to compensate
        
        elif self.mode == SimulatorMode.RAMP:
            # Gradually decrease delay (increase rate) over time
            if self.started_at:
                runtime = (datetime.utcnow() - self.started_at).total_seconds()
                ramp_factor = min(2.0, 1.0 + (runtime / 300.0))  # Double rate over 5 min
                return base_delay / ramp_factor
            return base_delay
        
        elif self.mode == SimulatorMode.CHAOS:
            # Random delays with high variance
            return base_delay * random.uniform(0.1, 3.0)
        
        return base_delay
    
    async def _generate_event(self):
        """Generate and send a single event"""
        self.events_generated += 1
        self.last_event_at = datetime.utcnow()
        
        # Decide if this should be a malformed request
        if random.random() < self.malformed_rate:
            await self._send_malformed_event()
            return
        
        # Decide if this should timeout
        timeout = 1.0 if random.random() < self.timeout_rate else 30.0
        
        # Generate payload
        payload = self._generate_payload()
        
        # Send to API
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self.api_url}/api/v1/ingest",
                    json=payload
                )
                
                if response.status_code == 200:
                    self.events_succeeded += 1
                elif response.status_code == 429:
                    self.events_rate_limited += 1
                    logger.warning(
                        "Rate limit hit",
                        extra={
                            "event": "simulator_rate_limited",
                            "status": response.status_code,
                        }
                    )
                else:
                    self.events_failed += 1
                    logger.error(
                        "Event failed",
                        extra={
                            "event": "simulator_event_failed",
                            "status": response.status_code,
                            "metric_name": payload.get("name"),
                        }
                    )
                    
        except httpx.TimeoutException:
            self.events_timeout += 1
            logger.warning(
                "Event timeout",
                extra={
                    "event": "simulator_timeout",
                    "metric_name": payload.get("name"),
                }
            )
        except Exception as e:
            self.events_failed += 1
            logger.error(
                "Event error",
                extra={
                    "event": "simulator_error",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )
    
    def _generate_payload(self) -> Dict:
        """
        Generate realistic metric payload.
        
        Returns:
            Metric payload dict
        """
        # Choose severity based on distribution
        severity = self._choose_severity()
        
        # Choose metric type
        metric_types = [
            ("cpu_usage", 0, 100),
            ("memory_usage", 0, 100),
            ("disk_usage", 0, 100),
            ("request_latency", 0, 5000),
            ("error_rate", 0, 100),
        ]
        
        metric_name, min_val, max_val = random.choice(metric_types)
        
        # Generate value based on severity
        if severity == EventSeverity.CRITICAL:
            value = random.uniform(max_val * 0.85, max_val)
        elif severity == EventSeverity.WARNING:
            value = random.uniform(max_val * 0.70, max_val * 0.85)
        else:  # NORMAL
            value = random.uniform(min_val, max_val * 0.70)
        
        return {
            "name": metric_name,
            "value": round(value, 2),
            "timestamp": time.time(),
            "labels": {
                "service": random.choice(["web", "api", "worker", "db"]),
                "environment": "test",
                "simulator": "true",
            }
        }
    
    def _choose_severity(self) -> EventSeverity:
        """
        Choose event severity with realistic distribution.
        
        Returns:
            Event severity
        """
        if self.mode == SimulatorMode.CHAOS:
            # Equal distribution in chaos mode
            return random.choice(list(EventSeverity))
        
        # Normal distribution: 70% normal, 20% warning, 10% critical
        rand = random.random()
        if rand < 0.70:
            return EventSeverity.NORMAL
        elif rand < 0.90:
            return EventSeverity.WARNING
        else:
            return EventSeverity.CRITICAL
    
    async def _send_malformed_event(self):
        """Send a malformed event to test error handling"""
        self.events_malformed += 1
        
        # Generate various types of malformed payloads
        malformed_payloads = [
            {},  # Empty payload
            {"name": "test"},  # Missing value
            {"value": 123},  # Missing name
            {"name": "", "value": "not_a_number"},  # Invalid types
            {"name": "test", "value": None},  # None value
            "not_a_dict",  # Wrong type
        ]
        
        payload = random.choice(malformed_payloads)
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{self.api_url}/api/v1/ingest",
                    json=payload
                )
        except Exception:
            pass  # Expected to fail


# Global simulator instance
_simulator: Optional[Simulator] = None


def get_simulator() -> Simulator:
    """Get the global simulator instance"""
    global _simulator
    if _simulator is None:
        _simulator = Simulator()
    return _simulator
