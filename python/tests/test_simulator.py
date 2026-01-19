"""
Tests for Phase 5 Simulator Service
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.services.simulator import Simulator, SimulatorMode, EventSeverity, get_simulator


class TestSimulator:
    """Test cases for Simulator service"""
    
    @pytest.fixture
    def simulator(self):
        """Create simulator instance"""
        return Simulator()
    
    def test_simulator_initialization(self, simulator):
        """Test simulator initializes with correct defaults"""
        assert not simulator.running
        assert simulator.target_rate == 100
        assert simulator.mode == SimulatorMode.STEADY
        assert simulator.events_generated == 0
        assert simulator.events_succeeded == 0
        assert simulator.events_failed == 0
    
    def test_configure_simulator(self, simulator):
        """Test simulator configuration"""
        simulator.configure(
            rate=500,
            mode=SimulatorMode.BURST,
            failure_rate=0.1,
            timeout_rate=0.05,
            malformed_rate=0.02
        )
        
        assert simulator.target_rate == 500
        assert simulator.mode == SimulatorMode.BURST
        assert simulator.failure_rate == 0.1
        assert simulator.timeout_rate == 0.05
        assert simulator.malformed_rate == 0.02
    
    def test_configure_clamps_rates(self, simulator):
        """Test configuration clamps rates to 0.0-1.0"""
        simulator.configure(
            rate=100,
            failure_rate=1.5,  # Should be clamped to 1.0
            timeout_rate=-0.5,  # Should be clamped to 0.0
        )
        
        assert simulator.failure_rate == 1.0
        assert simulator.timeout_rate == 0.0
    
    @pytest.mark.asyncio
    async def test_start_simulator(self, simulator):
        """Test starting the simulator"""
        await simulator.start()
        
        assert simulator.running
        assert simulator.started_at is not None
        assert simulator.task is not None
        
        # Clean up
        await simulator.stop()
    
    @pytest.mark.asyncio
    async def test_stop_simulator(self, simulator):
        """Test stopping the simulator"""
        await simulator.start()
        await asyncio.sleep(0.1)  # Let it run briefly
        await simulator.stop()
        
        assert not simulator.running
        assert simulator.task.cancelled()
    
    @pytest.mark.asyncio
    async def test_start_already_running(self, simulator, caplog):
        """Test starting simulator when already running"""
        await simulator.start()
        await simulator.start()  # Try to start again
        
        assert "already running" in caplog.text.lower()
        
        # Clean up
        await simulator.stop()
    
    @pytest.mark.asyncio
    async def test_stop_not_running(self, simulator, caplog):
        """Test stopping simulator when not running"""
        await simulator.stop()
        
        assert "not running" in caplog.text.lower()
    
    def test_get_status_not_started(self, simulator):
        """Test status when simulator not started"""
        status = simulator.get_status()
        
        assert not status["running"]
        assert status["started_at"] is None
        assert status["runtime_seconds"] == 0
        assert status["metrics"]["events_generated"] == 0
    
    @pytest.mark.asyncio
    async def test_get_status_running(self, simulator):
        """Test status when simulator is running"""
        await simulator.start()
        await asyncio.sleep(0.1)
        
        status = simulator.get_status()
        
        assert status["running"]
        assert status["started_at"] is not None
        assert status["runtime_seconds"] > 0
        assert status["configuration"]["target_rate"] == 100
        
        # Clean up
        await simulator.stop()
    
    def test_calculate_delay_steady(self, simulator):
        """Test delay calculation in steady mode"""
        simulator.configure(rate=60)  # 1 event per second
        delay = simulator._calculate_delay()
        
        assert delay == 1.0
    
    def test_calculate_delay_burst(self, simulator):
        """Test delay calculation in burst mode"""
        simulator.configure(rate=60, mode=SimulatorMode.BURST)
        
        # Test multiple times to hit both cases
        delays = [simulator._calculate_delay() for _ in range(100)]
        
        # Should have both fast and slow delays
        assert min(delays) < 0.2  # Some fast (burst)
        assert max(delays) > 0.5  # Some slow (normal)
    
    def test_generate_payload(self, simulator):
        """Test payload generation"""
        payload = simulator._generate_payload()
        
        assert "name" in payload
        assert "value" in payload
        assert "timestamp" in payload
        assert "labels" in payload
        assert payload["labels"]["simulator"] == "true"
    
    def test_generate_payload_severities(self, simulator):
        """Test payload generation with different severities"""
        # Generate many payloads and check distribution
        payloads = [simulator._generate_payload() for _ in range(100)]
        
        # All should have valid metrics
        for payload in payloads:
            assert payload["name"] in [
                "cpu_usage",
                "memory_usage",
                "disk_usage",
                "request_latency",
                "error_rate"
            ]
            assert isinstance(payload["value"], (int, float))
    
    def test_choose_severity_distribution(self, simulator):
        """Test severity distribution in normal mode"""
        # Generate many severities and check distribution
        severities = [simulator._choose_severity() for _ in range(1000)]
        
        normal_count = severities.count(EventSeverity.NORMAL)
        warning_count = severities.count(EventSeverity.WARNING)
        critical_count = severities.count(EventSeverity.CRITICAL)
        
        # Should be approximately 70%, 20%, 10%
        assert normal_count > 600  # ~70%
        assert 100 < warning_count < 300  # ~20%
        assert critical_count < 200  # ~10%
    
    def test_choose_severity_chaos(self, simulator):
        """Test severity distribution in chaos mode"""
        simulator.configure(mode=SimulatorMode.CHAOS)
        
        severities = [simulator._choose_severity() for _ in range(300)]
        
        # Should be more evenly distributed in chaos mode
        normal_count = severities.count(EventSeverity.NORMAL)
        warning_count = severities.count(EventSeverity.WARNING)
        critical_count = severities.count(EventSeverity.CRITICAL)
        
        # Each should appear reasonable number of times
        assert normal_count > 50
        assert warning_count > 50
        assert critical_count > 50
    
    @pytest.mark.asyncio
    async def test_generate_event_with_mock_client(self, simulator):
        """Test event generation with mocked HTTP client"""
        simulator.events_generated = 0
        simulator.events_succeeded = 0
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            
            await simulator._generate_event()
        
        assert simulator.events_generated == 1
        assert simulator.events_succeeded == 1
        assert simulator.last_event_at is not None
    
    @pytest.mark.asyncio
    async def test_generate_event_rate_limited(self, simulator):
        """Test event generation with rate limiting"""
        simulator.events_generated = 0
        simulator.events_rate_limited = 0
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 429
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            
            await simulator._generate_event()
        
        assert simulator.events_generated == 1
        assert simulator.events_rate_limited == 1
    
    @pytest.mark.asyncio
    async def test_generate_event_timeout(self, simulator):
        """Test event generation with timeout"""
        simulator.events_generated = 0
        simulator.events_timeout = 0
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=asyncio.TimeoutError()
            )
            
            await simulator._generate_event()
        
        assert simulator.events_generated == 1
        assert simulator.events_timeout == 1
    
    @pytest.mark.asyncio
    async def test_send_malformed_event(self, simulator):
        """Test sending malformed events"""
        simulator.events_malformed = 0
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock()
            
            await simulator._send_malformed_event()
        
        assert simulator.events_malformed == 1


class TestSimulatorSingleton:
    """Test simulator singleton pattern"""
    
    def test_get_simulator_singleton(self):
        """Test get_simulator returns same instance"""
        sim1 = get_simulator()
        sim2 = get_simulator()
        
        assert sim1 is sim2
    
    @pytest.mark.asyncio
    async def test_simulator_state_persists(self):
        """Test simulator state persists across get_simulator calls"""
        sim1 = get_simulator()
        sim1.configure(rate=999)
        
        sim2 = get_simulator()
        assert sim2.target_rate == 999


class TestSimulatorIntegration:
    """Integration tests for simulator with API"""
    
    @pytest.mark.asyncio
    async def test_simulator_generates_events(self):
        """Test simulator generates events over time"""
        simulator = Simulator()
        simulator.configure(rate=600)  # 10 events per second
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            
            await simulator.start()
            await asyncio.sleep(0.5)  # Run for 0.5 seconds
            await simulator.stop()
        
        # Should have generated some events
        assert simulator.events_generated > 0
        assert simulator.events_succeeded > 0
    
    @pytest.mark.asyncio
    async def test_simulator_handles_mixed_responses(self):
        """Test simulator handles mix of success/failure responses"""
        simulator = Simulator()
        simulator.configure(rate=600)
        
        responses = [200, 429, 500, 200, 429]  # Mix of responses
        response_iter = iter(responses)
        
        def get_status_code(*args, **kwargs):
            mock_response = AsyncMock()
            try:
                mock_response.status_code = next(response_iter)
            except StopIteration:
                mock_response.status_code = 200
            return mock_response
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=get_status_code
            )
            
            await simulator.start()
            await asyncio.sleep(0.3)
            await simulator.stop()
        
        # Should have mix of results
        assert simulator.events_generated > 0
        assert simulator.events_succeeded > 0
        assert (simulator.events_failed + simulator.events_rate_limited) > 0
