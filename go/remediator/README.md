# Vigil Remediator

The Vigil Remediator is an automated remediation engine that executes remediation actions in response to policy violations detected by the Vigil monitoring system.

## Architecture

The Remediator operates as an independent service that:

1. **Polls the Vigil API** for remediation tasks every 10 seconds
2. **Queues tasks** in a buffered channel for processing
3. **Executes tasks concurrently** using a configurable worker pool (default: 5 workers)
4. **Reports results** back to the API with detailed success/failure information
5. **Handles graceful shutdown** ensuring in-flight tasks are completed before exiting

## Implementation Files

### `cmd/remediator/main.go` (638 lines)
Core Remediator implementation with:
- **HTTP Server**: Listens on configurable port (default 8081)
  - `GET /remediator/tasks` - Receives task requests
  - `GET /remediator/health` - Health check endpoint
- **Task Polling**: Fetches tasks from API every 10 seconds
- **Worker Pool**: Concurrent task execution (configurable workers)
- **Remediation Actions**: 5 action types with dedicated executors
  - `restart_pod` - Restarts a Kubernetes pod
  - `scale_deployment` - Scales deployment replicas
  - `apply_manifest` - Applies Kubernetes manifests
  - `cordon_node` - Cordons nodes from scheduling
  - `execute_command` - Runs custom commands
- **Result Reporting**: HTTP POST to API with exponential backoff retry (5 attempts, 1-16s delays)
- **Graceful Shutdown**: Waits up to 30s for active tasks, then shuts down

### `cmd/remediator/config.go` (111 lines)
Configuration management with:
- **YAML file support** from standard paths:
  - `./configs/remediator.yaml`
  - `/etc/vigil/remediator/config/remediator.yaml`
  - Environment variable: `CONFIG_PATH`
- **Environment variable overrides**:
  - `REMEDIATOR_PORT` - Server port (default: 8081)
  - `API_HOST` - API hostname (default: localhost)
  - `API_PORT` - API port (default: 8000)
  - `LOG_LEVEL` - Logging level (default: INFO)
  - `MAX_CONCURRENT` - Worker count (default: 5)
  - `TASK_QUEUE_SIZE` - Task queue size (default: 100)
  - `POLLING_INTERVAL` - Task polling interval (default: 10)

### `cmd/remediator/logger.go` (127 lines)
Structured JSON logging with:
- **Log Levels**: DEBUG, INFO, WARN, ERROR
- **JSON Output**: Timestamp (RFC3339Nano), level, message, optional fields
- **Log Interface**: Debug(), Info(), Warn(), Error() methods
- **Startup Banner**: ASCII art banner printed on startup

## Configuration

### Environment Variables
```bash
export REMEDIATOR_PORT=8081
export API_HOST=localhost
export API_PORT=8000
export LOG_LEVEL=INFO
export MAX_CONCURRENT=5
export TASK_QUEUE_SIZE=100
```

### YAML Configuration File
```yaml
port: 8081
api_host: localhost
api_port: 8000
log_level: INFO
max_concurrent: 5
task_queue_size: 100
interval: 10
```

## Data Structures

### RemediationTask
```json
{
  "id": "task-uuid",
  "timestamp": 1234567890,
  "resource": "deployment/my-app",
  "namespace": "default",
  "action": "restart_pod",
  "parameters": {
    "pod_name": "my-app-xyz",
    "timeout": 30
  },
  "priority": "high",
  "policy_id": "policy-123",
  "timeout": 60,
  "max_retries": 3
}
```

### RemediationResult
```json
{
  "task_id": "task-uuid",
  "timestamp": 1234567890,
  "status": "success",
  "resource": "deployment/my-app",
  "namespace": "default",
  "action": "restart_pod",
  "duration": 5000,
  "details": {
    "pod_restarted": true,
    "restart_time_ms": 4500
  },
  "remediator_id": "remediator-hostname-1234",
  "remediator_version": "1.0.0"
}
```

## API Integration

### Task Polling
```
GET /remediator/tasks?limit=10&remediator_id=remediator-hostname-1234
```

### Result Reporting
```
POST /remediator/results
Content-Type: application/json

{
  "task_id": "task-uuid",
  "status": "success",
  "duration": 5000,
  ...
}
```

## Building

```bash
cd /home/techmedaddy/projects/vigil/go/remediator/cmd/remediator
go build -o remediator .
```

## Running

```bash
# With environment variables
export API_HOST=vigil-api.default.svc.cluster.local
export LOG_LEVEL=INFO
./remediator

# Or with config file
./remediator  # Uses ./configs/remediator.yaml or /etc/vigil/remediator/config/remediator.yaml
```

## Kubernetes Deployment

See [k8s/remediate-deployment.yaml](../../k8s/remediate-deployment.yaml) for complete Kubernetes deployment configuration including:
- RBAC permissions for remediation actions
- Pod disruption budgets
- Resource limits and requests
- Health check probes
- Service configuration

## Features

- ✅ Concurrent task execution with configurable worker pool
- ✅ Exponential backoff retry for API communication
- ✅ Structured JSON logging for observability
- ✅ Graceful shutdown with task completion
- ✅ Health check endpoint for liveness/readiness probes
- ✅ Multiple remediation action types
- ✅ YAML and environment variable configuration
- ✅ Unique remediator ID (hostname + PID)
- ✅ Comprehensive error handling and reporting

## Version

Vigil Remediator v1.0.0
