# Vigil Monitoring System — Complete Documentation

> **Version:** 1.0.0  
> **Purpose:** Comprehensive technical documentation 
---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture (HLD & LLD)](#2-architecture-hld--lld)
3. [Backend API Reference (22 Endpoints)](#3-backend-api-reference-22-endpoints)
4. [Frontend Integration Map](#4-frontend-integration-map)
5. [Simulator and Queue Flow](#5-simulator-and-queue-flow)
6. [Policy Engine Logic](#6-policy-engine-logic)
7. [Deployment Guide](#7-deployment-guide)
8. [Runbooks for Common Incidents](#8-runbooks-for-common-incidents)
9. [System Status Indicators and Metrics](#9-system-status-indicators-and-metrics)
10. [Versioning and Changelog](#10-versioning-and-changelog)

---

## 1. Project Overview

### What is Vigil?

**Vigil** is a backend-first, self-healing control plane that keeps services healthy by watching metrics, evaluating policies, and triggering automated remediation. Unlike traditional monitoring tools that only alert humans, Vigil actively closes the loop between detection and action.

### Core Value Proposition

| Benefit | Description |
|---------|-------------|
| **Automated Remediation** | Responds to incidents automatically without human intervention |
| **Policy-as-Code** | Define alerting and reaction logic in YAML or through API |
| **Backend-First Design** | Clean REST API that integrates with any frontend, CLI, or CI/CD pipeline |
| **Observable** | Full audit trail with Prometheus metrics and structured logging |

### Technology Stack

| Layer | Technology |
|-------|------------|
| **API Server** | Python 3.12, FastAPI, Uvicorn |
| **Database** | PostgreSQL 15 (async via `asyncpg`) |
| **Queue** | Redis 7 (task queue + caching) |
| **Agents** | Go 1.22 (Agent, GitOpsD, Remediator) |
| **Observability** | Prometheus, Grafana |
| **Deployment** | Docker Compose, Kubernetes |

### Core Features

| Area | What It Does |
|------|--------------|
| **Metrics Ingestion** | Accepts structured metrics from agents and services |
| **Policy Engine** | Evaluates metrics against human-friendly rules to spot issues |
| **Action Management** | Tracks remediation actions with full history and status updates |
| **Queue & Worker** | Uses Redis-backed queue and async workers to process tasks safely |
| **Remediator Integration** | Talks to Go remediator services to execute real changes |
| **Simulator** | Generates synthetic load to test the system end-to-end |
| **Audit & Logging** | Captures everything for later review |

---

## 2. Architecture (HLD & LLD)

### 2.1 High-Level Design (HLD)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           VIGIL MONITORING SYSTEM                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐        ┌──────────────────┐        ┌─────────────────┐   │
│   │   Agents    │───────▶│   FastAPI        │───────▶│   Prometheus    │   │
│   │ (Go/Python) │ HTTP   │   Collector      │ Export │   + Grafana     │   │
│   └─────────────┘        └────────┬─────────┘        └─────────────────┘   │
│                                   │                                         │
│                                   ▼                                         │
│                          ┌────────────────┐                                 │
│                          │  Policy Engine │                                 │
│                          │  (In-Memory)   │                                 │
│                          └────────┬───────┘                                 │
│                                   │                                         │
│                     ┌─────────────┴─────────────┐                           │
│                     ▼                           ▼                           │
│            ┌─────────────────┐         ┌──────────────┐                     │
│            │   PostgreSQL    │         │    Redis     │                     │
│            │   (Actions DB)  │         │   (Queue)    │                     │
│            └─────────────────┘         └───────┬──────┘                     │
│                                                │                            │
│                                                ▼                            │
│                                        ┌──────────────┐                     │
│                                        │   Worker     │                     │
│                                        │  (Async)     │                     │
│                                        └───────┬──────┘                     │
│                                                │                            │
│                                                ▼                            │
│                                       ┌───────────────┐                     │
│                                       │  Remediator   │                     │
│                                       │  (Go Service) │                     │
│                                       └───────────────┘                     │
│                                                │                            │
│                                                ▼                            │
│                                     ┌───────────────────┐                   │
│                                     │  Infrastructure   │                   │
│                                     │  (K8s/Docker/VM)  │                   │
│                                     └───────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow Diagram

```
┌─────────┐     ┌─────────┐     ┌────────┐     ┌───────┐     ┌────────┐     ┌────────────┐
│  Agent  │────▶│  API    │────▶│ Policy │────▶│ Queue │────▶│ Worker │────▶│ Remediator │
└─────────┘     └─────────┘     └────────┘     └───────┘     └────────┘     └────────────┘
    │               │               │              │              │               │
    │ POST          │ Store         │ Evaluate     │ Enqueue      │ Dequeue       │ Execute
    │ /ingest       │ Metric        │ Conditions   │ Task         │ Task          │ Action
    │               │               │              │              │               │
    ▼               ▼               ▼              ▼              ▼               ▼
  Metric         PostgreSQL      Violations     Redis List    Action Update    Restart/
  Payload        (metrics)       Detected       (FIFO)        to DB            Scale/Drain
```

### 2.3 Low-Level Design (LLD)

#### Component Breakdown

| Component | Location | Responsibility |
|-----------|----------|----------------|
| **FastAPI Collector** | `python/app/main.py` | HTTP server, request validation, routing |
| **Ingest Router** | `python/app/api/v1/ingest.py` | Metric ingestion, policy trigger |
| **Actions Router** | `python/app/api/v1/actions.py` | CRUD for remediation actions |
| **Policies Router** | `python/app/api/v1/policies.py` | Policy management API |
| **Policy Engine** | `python/app/core/policy.py` | Condition evaluation, action dispatch |
| **Queue Client** | `python/app/core/queue.py` | Redis queue operations |
| **Worker** | `python/app/services/worker.py` | Async task processor |
| **Simulator** | `python/app/services/simulator.py` | Load/stress testing |
| **Metrics** | `python/app/core/metrics.py` | Prometheus instrumentation |
| **Go Agent** | `go/agent/cmd/agent/` | Host metrics collection |
| **Go Remediator** | `go/remediator/cmd/remediator/` | Infrastructure actions |
| **Go GitOpsD** | `go/gitopsd/cmd/gitopsd/` | Manifest drift detection |

#### Database Schema

```sql
-- Metrics Table
CREATE TABLE metrics (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    value FLOAT NOT NULL,
    tags JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Actions Table  
CREATE TABLE actions (
    id SERIAL PRIMARY KEY,
    target VARCHAR(255) NOT NULL,
    action VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    details TEXT,
    started_at TIMESTAMP DEFAULT NOW()
);
```

#### Queue Structure (Redis)

```
Key: remediation_queue (LIST)
Value: JSON-encoded task objects

{
  "task_id": "task_1705753200123",
  "action_id": 456,
  "target": "web-service",
  "action": "restart",
  "severity": "critical",
  "enqueued_at": "2026-01-20T12:00:00Z"
}
```

---

## 3. Backend API Reference (22 Endpoints)

**Base URL:** `http://localhost:8000`  
**Content-Type:** `application/json`

### 3.1 Health & Admin Endpoints

#### GET `/health`
Check if the Vigil API service is running.

| Property | Value |
|----------|-------|
| Auth Required | No |
| Dependencies | None |

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "vigil"
}
```

---

#### GET `/metrics`
Prometheus-formatted metrics for monitoring.

**Response (200 OK):**
```text
# HELP vigil_requests_total Total HTTP requests
# TYPE vigil_requests_total counter
vigil_requests_total{method="POST",endpoint="/api/v1/ingest"} 1234
vigil_queue_length 5
vigil_action_count{target="web-service",action="restart",status="completed"} 89
```

---

### 3.2 Metrics & Ingestion Endpoints

#### POST `/api/v1/ingest`
Store a metric and trigger policy evaluation.

**Request:**
```json
{
  "name": "cpu_usage",
  "value": 85.5,
  "tags": {
    "host": "web-server-01",
    "region": "us-east-1"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Metric name (1-255 chars) |
| `value` | number | ✅ | Numeric metric value |
| `tags` | object | ❌ | Key-value tags |

**Response (201 Created):**
```json
{
  "ok": true,
  "metric_id": 123,
  "message": "Metric ingested successfully"
}
```

---

#### GET `/api/v1/ingest/health`
Check ingest service health.

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "ingest"
}
```

---

#### POST `/api/v1/ingest/agent/metrics`
Agent-specific ingestion endpoint (alias for `/ingest`).

---

### 3.3 Actions Endpoints

#### POST `/api/v1/actions`
Create a remediation action record.

**Request:**
```json
{
  "target": "web-service",
  "action": "restart",
  "status": "pending",
  "details": "Triggered by high CPU policy"
}
```

| Field | Type | Required | Values |
|-------|------|----------|--------|
| `target` | string | ✅ | Resource identifier |
| `action` | string | ✅ | `restart`, `scale-up`, `drain-pod` |
| `status` | string | ❌ | `pending`, `running`, `completed`, `failed`, `cancelled` |
| `details` | string | ❌ | Additional context |

**Response (201 Created):**
```json
{
  "ok": true,
  "action_id": 1,
  "message": "Action created successfully"
}
```

---

#### GET `/api/v1/actions`
List recent actions with optional filters.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max results (1-500) |
| `status` | string | - | Filter by status |
| `target` | string | - | Filter by target |

**Response (200 OK):**
```json
{
  "count": 2,
  "actions": [
    {
      "id": 1,
      "target": "web-service",
      "action": "restart",
      "status": "completed",
      "details": "Service restarted successfully",
      "started_at": "2026-01-20T12:34:56Z"
    }
  ]
}
```

---

#### GET `/api/v1/actions/{action_id}`
Get details of a specific action.

**Response (200 OK):**
```json
{
  "id": 1,
  "target": "web-service",
  "action": "restart",
  "status": "completed",
  "details": "Service restarted successfully",
  "started_at": "2026-01-20T12:34:56Z"
}
```

---

#### GET `/api/v1/actions/status/{status}`
Filter actions by status.

**Valid Statuses:** `pending`, `running`, `completed`, `failed`, `cancelled`

---

#### GET `/api/v1/actions/health`
Check actions service health.

---

### 3.4 Policies Endpoints

#### POST `/api/v1/policies`
Create a new monitoring policy.

**Request:**
```json
{
  "name": "high-cpu-alert",
  "description": "Alert when CPU exceeds 80%",
  "severity": "warning",
  "target": "web-*",
  "enabled": true,
  "auto_remediate": false,
  "condition": {
    "type": "metric_exceeds",
    "metric": "cpu_percent",
    "threshold": 80
  },
  "action": "restart",
  "params": {
    "cooldown_seconds": 300
  }
}
```

**Condition Types:**
```json
// Single conditions
{ "type": "metric_exceeds", "metric": "cpu_percent", "threshold": 80 }
{ "type": "metric_below", "metric": "disk_free_percent", "threshold": 10 }

// Compound conditions (AND)
{
  "type": "all",
  "conditions": [
    { "type": "metric_exceeds", "metric": "cpu_percent", "threshold": 80 },
    { "type": "metric_exceeds", "metric": "memory_percent", "threshold": 90 }
  ]
}

// Compound conditions (OR)
{
  "type": "any",
  "conditions": [
    { "type": "metric_exceeds", "metric": "cpu_percent", "threshold": 95 },
    { "type": "metric_below", "metric": "disk_free_percent", "threshold": 5 }
  ]
}
```

---

#### GET `/api/v1/policies`
List all registered policies.

**Response (200 OK):**
```json
{
  "ok": true,
  "policies": {
    "high-cpu-alert": {
      "name": "high-cpu-alert",
      "description": "Alert when CPU exceeds 80%",
      "severity": "warning",
      "target": "web-*",
      "enabled": true,
      "params": {},
      "auto_remediate": false
    }
  },
  "total": 2,
  "enabled_count": 2
}
```

---

#### GET `/api/v1/policies/{policy_name}`
Get details of a specific policy.

---

#### PUT `/api/v1/policies/{policy_name}`
Update an existing policy (partial update supported).

**Request:**
```json
{
  "description": "Updated description",
  "severity": "critical",
  "enabled": false
}
```

---

#### DELETE `/api/v1/policies/{policy_name}`
Remove a policy.

**Response (200 OK):**
```json
{
  "ok": true,
  "message": "Policy 'high-cpu-alert' deleted"
}
```

---

#### PUT `/api/v1/policies/{policy_name}/enable`
Enable a disabled policy.

---

#### PUT `/api/v1/policies/{policy_name}/disable`
Disable an enabled policy.

---

#### POST `/api/v1/policies/reload`
Reload policies from configuration files.

**Response (200 OK):**
```json
{
  "ok": true,
  "message": "Policies reloaded successfully (5 policies)"
}
```

---

#### GET `/api/v1/policies/severity/{severity}`
Filter policies by severity level (`info`, `warning`, `critical`).

---

#### GET `/api/v1/policies/runner/status`
Get background policy runner status.

**Response (200 OK):**
```json
{
  "ok": true,
  "runner": {
    "enabled": true,
    "running": true,
    "interval_seconds": 30,
    "batch_size": 100
  }
}
```

---

#### POST `/api/v1/policies/evaluate`
Test policies against provided metrics (sandbox mode).

**Request:**
```json
{
  "metrics": {
    "cpu_percent": 95,
    "memory_percent": 88
  },
  "target": "web-server-01"
}
```

**Response (200 OK):**
```json
{
  "ok": true,
  "violations": [
    {
      "policy_name": "high-cpu-alert",
      "severity": "warning",
      "description": "Alert when CPU exceeds 80%",
      "target": "web-server-01",
      "timestamp": "2026-01-20T12:34:56Z"
    }
  ],
  "actions_triggered": [
    {
      "action": "restart",
      "target": "web-server-01",
      "status": "triggered",
      "params": {}
    }
  ],
  "timestamp": "2026-01-20T12:34:56Z"
}
```

---

### 3.5 Endpoint Summary Table

| # | Endpoint | Method | Description | Status |
|---|----------|--------|-------------|--------|
| 1 | `/health` | GET | API health check | ✅ Ready |
| 2 | `/metrics` | GET | Prometheus metrics | ✅ Ready |
| 3 | `/api/v1/ingest` | POST | Ingest metric | ✅ Ready |
| 4 | `/api/v1/ingest/health` | GET | Ingest health | ✅ Ready |
| 5 | `/api/v1/ingest/agent/metrics` | POST | Agent ingest alias | ✅ Ready |
| 6 | `/api/v1/actions` | POST | Create action | ✅ Ready |
| 7 | `/api/v1/actions` | GET | List actions | ✅ Ready |
| 8 | `/api/v1/actions/{id}` | GET | Get action by ID | ✅ Ready |
| 9 | `/api/v1/actions/status/{status}` | GET | Actions by status | ✅ Ready |
| 10 | `/api/v1/actions/health` | GET | Actions health | ✅ Ready |
| 11 | `/api/v1/policies` | POST | Create policy | ✅ Ready |
| 12 | `/api/v1/policies` | GET | List policies | ✅ Ready |
| 13 | `/api/v1/policies/{name}` | GET | Get policy | ✅ Ready |
| 14 | `/api/v1/policies/{name}` | PUT | Update policy | ✅ Ready |
| 15 | `/api/v1/policies/{name}` | DELETE | Delete policy | ✅ Ready |
| 16 | `/api/v1/policies/{name}/enable` | PUT | Enable policy | ✅ Ready |
| 17 | `/api/v1/policies/{name}/disable` | PUT | Disable policy | ✅ Ready |
| 18 | `/api/v1/policies/evaluate` | POST | Evaluate policies | ✅ Ready |
| 19 | `/api/v1/policies/reload` | POST | Reload policies | ✅ Ready |
| 20 | `/api/v1/policies/severity/{sev}` | GET | Policies by severity | ✅ Ready |
| 21 | `/api/v1/policies/runner/status` | GET | Runner status | ✅ Ready |
| 22 | `/api/v1/ui/queue/stats` | GET | Queue statistics | ⚠️ Planned |

---

## 4. Frontend Integration Map

Use this map to wire React/Vue/Angular components to backend data.

### UI → Endpoint Mapping

| UI Component | Backend Action | Endpoint | Payload | Response |
|--------------|----------------|----------|---------|----------|
| **Connection Badge** | Check API status | `GET /health` | None | `{status: "healthy"}` |
| **Activity Feed** | Poll recent actions | `GET /api/v1/actions?limit=20` | None | `{actions: [...]}` |
| **Metric Chart** | Fetch Prometheus data | `GET /metrics` | None | Prometheus text |
| **Manual Trigger** | User clicks Restart | `POST /api/v1/actions` | `{target, action}` | `{action_id}` |
| **Policy Table** | List active rules | `GET /api/v1/policies` | None | `{policies: {...}}` |
| **Policy Form** | Create new rule | `POST /api/v1/policies` | Policy JSON | Policy object |
| **Policy Toggle** | Enable/disable | `PUT .../enable` or `PUT .../disable` | None | `{ok, message}` |
| **Policy Sandbox** | Test conditions | `POST /api/v1/policies/evaluate` | `{metrics}` | `{violations}` |
| **Status by Type** | Filter pending actions | `GET /api/v1/actions/status/pending` | None | `{actions: [...]}` |
| **Severity Filter** | Critical policies only | `GET /api/v1/policies/severity/critical` | None | `{policies: {...}}` |

### TypeScript Interfaces

```typescript
interface Policy {
  name: string;
  description: string;
  severity: 'info' | 'warning' | 'critical';
  target: string;
  enabled: boolean;
  params: Record<string, any>;
  auto_remediate: boolean;
}

interface Action {
  id: number;
  target: string;
  action: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  details: string | null;
  started_at: string;
}

interface Metric {
  name: string;
  value: number;
  tags?: Record<string, string>;
}
```

### CORS Configuration

Allowed origins (development):
- `http://localhost:3000` (React)
- `http://localhost:5173` (Vite)
- `http://127.0.0.1:3000`
- `http://127.0.0.1:5173`

---

## 5. Simulator and Queue Flow

### 5.1 Simulator Overview

The **Simulator** (`python/app/services/simulator.py`) is a built-in load testing tool used to validate Vigil under stress.

#### Operating Modes

| Mode | Behavior |
|------|----------|
| `STEADY` | Constant rate of events per minute |
| `BURST` | Periodic traffic spikes |
| `RAMP` | Gradually increasing load |
| `CHAOS` | Random failures and unpredictable spikes |

#### Failure Injection

| Parameter | Range | Description |
|-----------|-------|-------------|
| `failure_rate` | 0.0 - 1.0 | Probability of generating failed requests |
| `timeout_rate` | 0.0 - 1.0 | Probability of simulated timeouts |
| `malformed_rate` | 0.0 - 1.0 | Probability of malformed payloads |

#### Simulator Metrics

```python
events_generated = 0     # Total events sent
events_succeeded = 0     # Successful ingestions
events_failed = 0        # Failed requests
events_rate_limited = 0  # 429 responses received
events_timeout = 0       # Timeout errors
events_malformed = 0     # Malformed payloads sent
```

### 5.2 Queue Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       REDIS QUEUE FLOW                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐       ┌─────────────────┐       ┌──────────────┐ │
│  │ Policy   │──────▶│ remediation_    │──────▶│   Worker     │ │
│  │ Engine   │ RPUSH │ queue (LIST)    │ BLPOP │   (Async)    │ │
│  └──────────┘       └─────────────────┘       └──────────────┘ │
│                              │                       │          │
│                              ▼                       ▼          │
│                     ┌─────────────────┐     ┌──────────────┐   │
│                     │ Stats Key       │     │ Remediator   │   │
│                     │ (tasks_enqueued │     │ (HTTP POST)  │   │
│                     │  tasks_dequeued)│     └──────────────┘   │
│                     └─────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Queue Task Lifecycle

```
┌──────────┐     ┌─────────┐     ┌────────────┐     ┌───────────┐     ┌──────────┐
│ Waiting  │────▶│ Enqueue │────▶│  Pending   │────▶│ Processing│────▶│ Complete │
└──────────┘     └─────────┘     └────────────┘     └───────────┘     └──────────┘
                                       │                  │
                                       │                  ▼
                                       │           ┌───────────┐
                                       │           │  Failed   │
                                       │           └─────┬─────┘
                                       │                 │
                                       └─────────────────┘
                                         Retry with backoff
```

### 5.4 Queue Operations

```python
# Enqueue a task
queue_client.enqueue_task({
    "task_id": "task_1705753200123",
    "action_id": 456,
    "target": "web-service",
    "severity": "critical",
    "enqueued_at": "2026-01-20T12:00:00Z"
})

# Dequeue (blocking with timeout)
task = queue_client.dequeue_task(timeout=5)

# Get queue length
length = queue_client.get_queue_length()
```

---

## 6. Policy Engine Logic

### 6.1 Policy Structure

A policy consists of:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Unique identifier |
| `condition` | Callable | Function that evaluates to True/False |
| `action` | ActionType | What to do on violation |
| `severity` | Enum | `info`, `warning`, `critical` |
| `target` | string | Resource pattern (supports wildcards) |
| `enabled` | bool | Active or disabled |
| `auto_remediate` | bool | Execute action automatically |
| `params` | dict | Parameters passed to action |

### 6.2 Built-in Conditions

```python
# Metric exceeds threshold
condition = metric_exceeds("cpu_percent", 80)
# Returns True if metrics["cpu_percent"] > 80

# Metric below threshold
condition = metric_below("disk_free_percent", 10)
# Returns True if metrics["disk_free_percent"] < 10

# Combine with AND
condition = all_conditions(
    metric_exceeds("cpu_percent", 80),
    metric_exceeds("memory_percent", 90)
)

# Combine with OR
condition = any_condition(
    metric_exceeds("cpu_percent", 95),
    metric_below("disk_free_percent", 5)
)
```

### 6.3 Built-in Actions

| Action Type | Description |
|-------------|-------------|
| `SCALE_UP` | Increase replicas/capacity |
| `SCALE_DOWN` | Decrease replicas/capacity |
| `RESTART_SERVICE` | Restart the target service |
| `DRAIN_POD` | Gracefully drain a K8s pod |
| `REBALANCE` | Redistribute workload |
| `SNAPSHOT` | Create a backup/snapshot |
| `CUSTOM` | Webhook or custom handler |

### 6.4 Policy Evaluation Flow

```python
def evaluate(self, metrics: Dict[str, Any]) -> bool:
    # Skip if policy is disabled
    if not self.enabled:
        return False
    
    # Evaluate condition against metrics
    try:
        return self.condition(metrics)
    except Exception as e:
        logger.error(f"Policy evaluation failed: {e}")
        return False
```

### 6.5 Target Matching

```python
# Exact match
policy.target = "web-service"
policy.matches_target("web-service")  # True
policy.matches_target("api-service")  # False

# Wildcard match
policy.target = "web-*"
policy.matches_target("web-frontend")  # True
policy.matches_target("web-backend")   # True
policy.matches_target("api-gateway")   # False

# Match all
policy.target = "all"  # or "*"
policy.matches_target("anything")  # True
```

---

## 7. Deployment Guide

### 7.1 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./vigil.db` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `COLLECTOR_PORT` | `8000` | API server port |
| `REMEDIATOR_URL` | `http://127.0.0.1:8081/remediate` | Remediator service URL |
| `AGENT_INTERVAL` | `10.0` | Agent metric collection interval (seconds) |
| `GITOPSD_INTERVAL` | `30.0` | GitOps drift check interval (seconds) |
| `CONFIG_PATH` | `configs/collector.yaml` | Path to YAML config |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `METRICS_ENABLED` | `true` | Enable Prometheus metrics |

### 7.2 Docker Compose (Local Development)

```bash
# Start all services
docker-compose up -d --build

# Check service health
docker-compose ps

# View logs
docker-compose logs -f api

# Stop all services
docker-compose down
```

#### Service Dependencies

```yaml
services:
  redis:        # Port 6380:6379
  postgres:     # Port 5432
  api:          # Port 8000 (depends on redis, postgres)
  gitopsd:      # (depends on api)
  agent:        # (depends on api)
  remediator:   # (depends on api)
  prometheus:   # Port 9090
  grafana:      # Port 3000
```

### 7.3 Health Checks

| Service | Health Check Command |
|---------|---------------------|
| **Redis** | `redis-cli ping` |
| **Postgres** | `pg_isready -U vigil -d vigil` |
| **API** | `curl http://localhost:8000/health` |
| **GitOpsD** | `pgrep -f gitopsd` |
| **Agent** | `pgrep -f agent` |
| **Remediator** | `pgrep -f remediator` |

### 7.4 Kubernetes Deployment

Manifests located in `k8s/`:

```bash
# Apply all manifests
kubectl apply -f k8s/

# Check deployments
kubectl get pods -l app=vigil

# View API logs
kubectl logs -l app=vigil-api -f
```

| Manifest | Description |
|----------|-------------|
| `api-deployment.yaml` | FastAPI collector (Deployment + Service) |
| `remediator-deployment.yaml` | Go remediator |
| `agent-deployment.yaml` | Metrics agent (DaemonSet) |
| `gitopsd-deployment.yaml` | GitOps daemon |

### 7.5 CI/CD Pipeline

Pipeline stages (defined in `ci/pipeline.yml`):

1. **Lint** - Code style and static analysis
2. **Test** - Unit and integration tests
3. **Build** - Docker image creation
4. **Push** - Push to container registry
5. **Deploy** - Deploy to Kubernetes

---

## 8. Runbooks for Common Incidents

### 8.1 Queue Backlog High

**Symptoms:**
- `vigil_queue_length` metric > 100
- Remediation actions delayed
- Worker logs show slow processing

**Diagnosis:**
```bash
# Check Redis health
docker exec vigil_redis redis-cli ping

# Check queue length
docker exec vigil_redis redis-cli llen remediation_queue

# Check worker logs
docker logs vigil_worker --tail 100

# Check if remediator is responding
curl http://localhost:8081/health
```

**Resolution:**
1. Scale up worker instances
2. Check remediator connectivity
3. Clear stale tasks if necessary
4. Investigate slow remediation actions

---

### 8.2 Database Connection Lost

**Symptoms:**
- API returns 500 errors
- Logs show `OperationalError` or `Connection refused`
- `/api/v1/actions` and `/api/v1/ingest` fail

**Diagnosis:**
```bash
# Check Postgres health
docker exec vigil_postgres pg_isready -U vigil

# Check connection from API container
docker exec vigil_api python -c "
from app.core.db import get_db_manager
import asyncio
asyncio.run(get_db_manager().check_connection())
"

# Check environment variable
docker exec vigil_api env | grep DATABASE_URL
```

**Resolution:**
1. Restart Postgres container
2. Verify credentials in `DATABASE_URL`
3. Check network connectivity
4. Increase connection pool size if overwhelmed

---

### 8.3 High CPU on API

**Symptoms:**
- Response latency > 1s on `/ingest`
- `vigil_request_latency_seconds` histogram shows high p99
- Container CPU utilization > 80%

**Diagnosis:**
```bash
# Check if simulator is running
curl http://localhost:8000/api/v1/ui/simulator/status

# Check request rate
curl -s http://localhost:8000/metrics | grep requests_total

# Profile the API
docker exec vigil_api python -m cProfile app/main.py
```

**Resolution:**
1. Stop the simulator if in `CHAOS` or `BURST` mode
2. Scale up API replicas
3. Enable rate limiting
4. Optimize slow policy conditions

---

### 8.4 Policy Not Triggering

**Symptoms:**
- Metrics are being ingested
- Expected violations not appearing
- No actions created for threshold breaches

**Diagnosis:**
```bash
# Check if policy exists and is enabled
curl http://localhost:8000/api/v1/policies | jq

# Test policy manually
curl -X POST http://localhost:8000/api/v1/policies/evaluate \
  -H "Content-Type: application/json" \
  -d '{"metrics": {"cpu_percent": 95}, "target": "web-server"}'

# Check policy runner status
curl http://localhost:8000/api/v1/policies/runner/status
```

**Resolution:**
1. Verify policy is `enabled: true`
2. Check condition thresholds
3. Verify target pattern matches incoming metrics
4. Reload policies with `POST /api/v1/policies/reload`

---

### 8.5 Redis Connection Failed

**Symptoms:**
- Queue operations fail
- `ConnectionRefusedError` in logs
- Actions not being enqueued

**Diagnosis:**
```bash
# Check Redis is running
docker ps | grep redis

# Test connection
docker exec vigil_redis redis-cli ping

# Check REDIS_URL
docker exec vigil_api env | grep REDIS_URL
```

**Resolution:**
1. Restart Redis container
2. Verify `REDIS_URL` format
3. Check Redis memory usage
4. Clear Redis if corrupted: `FLUSHALL`

---

## 9. System Status Indicators and Metrics

### 9.1 Prometheus Metrics

Vigil exposes metrics at `/metrics` in Prometheus format.

#### Counters

| Metric | Labels | Description |
|--------|--------|-------------|
| `requests_total` | method, endpoint, status | Total HTTP requests |
| `actions_total` | target, action, status | Remediation actions executed |
| `ingest_total` | metric_name | Metrics ingested |
| `policy_evaluation_total` | policy_name, result | Policy evaluations |
| `worker_tasks_total` | status | Tasks processed by worker |
| `queue_operations_total` | operation | Queue enqueue/dequeue ops |

#### Gauges

| Metric | Description |
|--------|-------------|
| `queue_length` | Current tasks in queue |
| `worker_active` | Worker status (1=running, 0=stopped) |

#### Histograms

| Metric | Labels | Buckets |
|--------|--------|---------|
| `request_latency_seconds` | endpoint | 5ms - 10s |
| `drift_detection_latency_seconds` | manifest_type, status | 10ms - 60s |

### 9.2 Key Health Indicators

| Indicator | Healthy Range | Alert Threshold |
|-----------|---------------|-----------------|
| API Response Time | < 100ms p95 | > 500ms p95 |
| Queue Length | < 10 | > 50 |
| Error Rate | < 1% | > 5% |
| Worker Uptime | 100% | < 99% |
| Ingest Throughput | > 100/min | < 50/min |

### 9.3 Grafana Dashboard

Pre-configured dashboard available at `configs/grafana_dashboard.json`.

**Panels:**
- Request rate and latency
- Queue depth over time
- Actions by status (pie chart)
- Policy violations timeline
- Error rate percentage
- Worker health status

---

## 10. Versioning and Changelog

### 10.1 Versioning Scheme

Vigil follows **Semantic Versioning (SemVer)**: `MAJOR.MINOR.PATCH`

- **MAJOR:** Breaking API changes
- **MINOR:** New features, backward compatible
- **PATCH:** Bug fixes, performance improvements

Current version: **1.0.0** (defined in `python/app/core/config.py`)

### 10.2 API Versioning

- API routes are prefixed with `/api/v1/`
- New major versions will use `/api/v2/`, etc.
- Version is exposed via `/health` response

### 10.3 Changelog

#### v1.0.0 (January 2026)
**Initial Release**

- ✅ FastAPI-based collector with async support
- ✅ PostgreSQL storage for metrics and actions
- ✅ Redis-backed remediation queue
- ✅ Policy engine with condition DSL
- ✅ Go agents (Agent, GitOpsD, Remediator)
- ✅ Prometheus metrics integration
- ✅ Docker Compose deployment
- ✅ Kubernetes manifests
- ✅ 21 REST API endpoints
- ✅ TypeScript SDK for frontend
- ✅ Simulator for load testing

**Planned for v1.1.0:**
- Queue stats API endpoint
- Simulator control API
- WebSocket real-time updates
- Multi-tenant support

---

## Quick Reference Card

### Essential Commands

```bash
# Start Vigil
docker-compose up -d

# Check health
curl http://localhost:8000/health

# Ingest a metric
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"name": "cpu_usage", "value": 85}'

# Create a policy
curl -X POST http://localhost:8000/api/v1/policies \
  -H "Content-Type: application/json" \
  -d '{"name": "high-cpu", "condition": {"type": "metric_exceeds", "metric": "cpu_usage", "threshold": 80}, "action": "restart"}'

# List actions
curl http://localhost:8000/api/v1/actions

# View queue metrics
curl http://localhost:8000/metrics | grep queue
```

### Important URLs

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Swagger Docs | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

---

*Documentation generated on January 22, 2026*
