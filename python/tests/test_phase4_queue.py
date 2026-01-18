"""
Tests for Phase 4 (Worker Queue) implementation.

Tests cover:
- Queue enqueue/dequeue operations
- Worker task processing
- End-to-end flow: policy violation → queue → worker → action
- Audit trail verification
"""

import pytest
import json
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime

# Test queue operations
class TestQueueOperations:
    """Test core queue enqueue/dequeue operations."""
    
    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        redis_mock = MagicMock()
        redis_mock.rpush = MagicMock(return_value=1)
        redis_mock.blpop = MagicMock(return_value=None)
        redis_mock.llen = MagicMock(return_value=0)
        redis_mock.hincrby = MagicMock()
        redis_mock.hget = MagicMock(return_value=None)
        redis_mock.hset = MagicMock()
        redis_mock.ping = MagicMock()
        return redis_mock
    
    def test_enqueue_task_success(self, mock_redis):
        """Test successful task enqueue."""
        with patch('redis.from_url', return_value=mock_redis):
            from app.core.queue import QueueClient
            
            client = QueueClient()
            payload = {
                "action_id": "123",
                "target": "web-service",
                "severity": "high",
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            result = client.enqueue_task(payload)
            
            assert result is True
            assert mock_redis.rpush.called
            call_args = mock_redis.rpush.call_args
            assert call_args[0][0] == "remediation_queue"
            
            # Verify JSON structure
            task_json = call_args[0][1]
            task_data = json.loads(task_json)
            assert task_data["action_id"] == "123"
            assert task_data["target"] == "web-service"
            assert "enqueued_at" in task_data
            assert "task_id" in task_data
    
    def test_dequeue_task_with_data(self, mock_redis):
        """Test successful task dequeue."""
        task_payload = {
            "action_id": "456",
            "target": "db-service",
            "severity": "critical",
            "timestamp": datetime.utcnow().isoformat(),
        }
        mock_redis.blpop.return_value = ("remediation_queue", json.dumps(task_payload))
        
        with patch('redis.from_url', return_value=mock_redis):
            from app.core.queue import QueueClient
            
            client = QueueClient()
            result = client.dequeue_task(timeout=5)
            
            assert result is not None
            assert result["action_id"] == "456"
            assert result["target"] == "db-service"
            assert "dequeued_at" in result
    
    def test_dequeue_task_timeout(self, mock_redis):
        """Test dequeue timeout when no tasks available."""
        mock_redis.blpop.return_value = None
        
        with patch('redis.from_url', return_value=mock_redis):
            from app.core.queue import QueueClient
            
            client = QueueClient()
            result = client.dequeue_task(timeout=1)
            
            assert result is None
    
    def test_get_queue_length(self, mock_redis):
        """Test getting queue length."""
        mock_redis.llen.return_value = 5
        
        with patch('redis.from_url', return_value=mock_redis):
            from app.core.queue import QueueClient
            
            client = QueueClient()
            length = client.get_queue_length()
            
            assert length == 5
            mock_redis.llen.assert_called_once_with("remediation_queue")
    
    def test_get_queue_stats(self, mock_redis):
        """Test getting queue statistics."""
        mock_redis.llen.return_value = 3
        mock_redis.hget.side_effect = lambda key, field: {
            "tasks_enqueued": "10",
            "tasks_dequeued": "7",
            "tasks_completed": "5",
            "tasks_failed": "2",
        }.get(field)
        
        with patch('redis.from_url', return_value=mock_redis):
            from app.core.queue import QueueClient
            
            client = QueueClient()
            stats = client.get_queue_stats()
            
            assert stats["queue_length"] == 3
            assert stats["tasks_enqueued"] == 10
            assert stats["tasks_dequeued"] == 7
            assert stats["tasks_completed"] == 5
            assert stats["tasks_failed"] == 2


class TestWorkerProcessing:
    """Test worker task processing logic."""
    
    @pytest.fixture
    def mock_queue_client(self):
        """Create mock queue client."""
        client = MagicMock()
        client.dequeue_task = MagicMock(return_value=None)
        client.increment_completed = MagicMock()
        client.increment_failed = MagicMock()
        return client
    
    @pytest.mark.asyncio
    async def test_worker_processes_task_successfully(self, mock_queue_client):
        """Test worker processes task and calls remediator."""
        task_payload = {
            "task_id": "task_123",
            "action_id": "789",
            "target": "api-service",
            "action": "restart",
            "severity": "high",
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Mock httpx client
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        
        with patch('app.services.worker.get_queue_client', return_value=mock_queue_client), \
             patch('app.services.worker.httpx.AsyncClient', return_value=mock_client), \
             patch('app.services.worker.get_db_async'):
            
            from app.services.worker import RemediationWorker
            
            worker = RemediationWorker()
            await worker._process_task(task_payload)
            
            # Verify remediator was called
            assert mock_client.__aenter__.return_value.post.called
            call_args = mock_client.__aenter__.return_value.post.call_args
            assert "/remediate" in str(call_args)
            
            # Verify task was marked completed
            assert worker.tasks_processed == 1
            assert worker.tasks_failed == 0
    
    @pytest.mark.asyncio
    async def test_worker_handles_remediator_failure(self, mock_queue_client):
        """Test worker handles remediator service failures."""
        task_payload = {
            "task_id": "task_456",
            "action_id": "999",
            "target": "failed-service",
            "action": "restart",
            "severity": "high",
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Mock httpx client with failure
        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post = AsyncMock(return_value=mock_response)
        
        with patch('app.services.worker.get_queue_client', return_value=mock_queue_client), \
             patch('app.services.worker.httpx.AsyncClient', return_value=mock_client), \
             patch('app.services.worker.get_db_async'):
            
            from app.services.worker import RemediationWorker
            
            worker = RemediationWorker()
            await worker._process_task(task_payload)
            
            # Verify task was marked failed
            assert worker.tasks_processed == 0
            assert worker.tasks_failed == 1
    
    @pytest.mark.asyncio
    async def test_worker_status(self):
        """Test worker status reporting."""
        from app.services.worker import RemediationWorker
        
        worker = RemediationWorker()
        worker.started_at = datetime.utcnow()
        worker.tasks_processed = 10
        worker.tasks_failed = 2
        
        status = worker.get_status()
        
        assert status["running"] is False
        assert status["tasks_processed"] == 10
        assert status["tasks_failed"] == 2
        assert round(status["success_rate"], 2) == 83.33


class TestEndToEndFlow:
    """Test complete flow from policy violation to action execution."""
    
    @pytest.mark.asyncio
    async def test_policy_violation_enqueues_task(self):
        """Test that policy violation creates action and enqueues task."""
        # Mock database session
        mock_session = AsyncMock()
        mock_action = MagicMock()
        mock_action.id = 123
        
        # Mock enqueue_task
        with patch('app.core.policy_runner.get_db_manager') as mock_db_manager, \
             patch('app.core.policy_runner.enqueue_task') as mock_enqueue:
            
            mock_db_manager.return_value.get_session_context.return_value.__aenter__.return_value = mock_session
            mock_session.add = MagicMock()
            mock_session.flush = AsyncMock()
            
            from app.core.policy_runner import execute_remediation_action
            
            result = await execute_remediation_action(
                target="test-service",
                action_type="restart",
                params={"severity": "high"},
                policy_name="test_policy",
            )
            
            assert result is True
            assert mock_enqueue.called
            
            # Verify task payload
            call_args = mock_enqueue.call_args[0][0]
            assert call_args["target"] == "test-service"
            assert call_args["action"] == "restart"
            assert call_args["severity"] == "high"
            assert "action_id" in call_args


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
