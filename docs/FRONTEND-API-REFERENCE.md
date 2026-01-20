# Vigil Backend API Reference for Frontend Integration

> **Generated:** January 20, 2026  
> **Base URL:** `http://localhost:8000`  
> **API Version:** 1.0.0  
> **Content-Type:** `application/json`

This document provides a complete reference for wiring frontend components to Vigil backend endpoints with correct payloads and responses.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Admin/Health Endpoints](#1-adminhealth-endpoints)
3. [Metrics & Ingestion Endpoints](#2-metrics--ingestion-endpoints)
4. [Actions Endpoints](#3-actions-endpoints)
5. [Policies Endpoints](#4-policies-endpoints)
6. [Queue Monitor Endpoints](#5-queue-monitor-endpoints-planned)
7. [Simulator Endpoints](#6-simulator-endpoints-planned)
8. [Policy Tester Endpoints](#7-policy-tester-endpoints)
9. [Endpoint Summary](#endpoint-summary)
10. [Error Handling](#error-handling)
11. [Dependencies](#dependencies)

---

## Quick Start

```typescript
// Base configuration
const API_BASE = 'http://localhost:8000';
const API_VERSION = '/api/v1';

// Standard headers
const headers = {
  'Content-Type': 'application/json',
};

// Example fetch
const response = await fetch(`${API_BASE}${API_VERSION}/policies`, { headers });
```

---

## 1. Admin/Health Endpoints

### 1.1 Root Health Check

| Property | Value |
|----------|-------|
| **Route** | `/health` |
| **Method** | `GET` |
| **Description** | Check if the Vigil API service is running |
| **Auth Required** | No |
| **Dependencies** | None |

**Request:**
```http
GET /health
```

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "vigil"
}
```

**Frontend Use Case:** App-level health indicator, connection status badge

---

### 1.2 Prometheus Metrics

| Property | Value |
|----------|-------|
| **Route** | `/metrics` |
| **Method** | `GET` |
| **Description** | Prometheus-formatted metrics for monitoring |
| **Auth Required** | No |
| **Dependencies** | Metrics module |

**Request:**
```http
GET /metrics
```

**Response (200 OK):**
```text
# HELP vigil_requests_total Total HTTP requests
# TYPE vigil_requests_total counter
vigil_requests_total{method="POST",endpoint="/api/v1/ingest"} 1234
vigil_ingest_count{metric_name="cpu_usage"} 567
vigil_action_count{target="web-service",action="restart",status="completed"} 89
vigil_queue_length 5
```

**Frontend Use Case:** Dashboard metrics visualization, Grafana integration

---

## 2. Metrics & Ingestion Endpoints

### 2.1 Ingest Metric

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/ingest` |
| **Method** | `POST` |
| **Description** | Store a metric and trigger policy evaluation |
| **Auth Required** | No |
| **Dependencies** | PostgreSQL, Policy Engine, Redis (for queue) |

**Request Payload:**
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
| `tags` | object | ❌ | Key-value tags for categorization |

**Response (201 Created):**
```json
{
  "ok": true,
  "metric_id": 123,
  "message": "Metric ingested successfully"
}
```

**Error Response (400/500):**
```json
{
  "detail": "Validation error: Metric name cannot be empty"
}
```

**Frontend Use Case:** Manual metric injection form, testing policy triggers

---

### 2.2 Ingest Health Check

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/ingest/health` |
| **Method** | `GET` |
| **Description** | Check ingest service health |
| **Auth Required** | No |
| **Dependencies** | None |

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "ingest"
}
```

---

### 2.3 Agent Metrics Ingestion

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/ingest/agent/metrics` |
| **Method** | `POST` |
| **Description** | Agent-specific ingestion endpoint (alias) |
| **Auth Required** | No |
| **Dependencies** | PostgreSQL, Policy Engine |

**Request/Response:** Same as `/api/v1/ingest`

**Note:** Used by Go agent; same behavior as main ingest endpoint.

---

## 3. Actions Endpoints

### 3.1 Create Action

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/actions` |
| **Method** | `POST` |
| **Description** | Create a remediation action record |
| **Auth Required** | No |
| **Dependencies** | PostgreSQL |

**Request Payload:**
```json
{
  "target": "web-service",
  "action": "restart",
  "status": "pending",
  "details": "Triggered by high CPU policy"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target` | string | ✅ | Target resource (1-255 chars) |
| `action` | string | ✅ | Action type: `restart`, `scale-up`, `drain`, etc. |
| `status` | string | ❌ | Status: `pending`, `running`, `completed`, `failed`, `cancelled` (default: `pending`) |
| `details` | string | ❌ | Additional context |

**Response (201 Created):**
```json
{
  "ok": true,
  "action_id": 1,
  "message": "Action created successfully"
}
```

**Frontend Use Case:** Manual action trigger button, remediation dashboard

---

### 3.2 List Actions

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/actions` |
| **Method** | `GET` |
| **Description** | Retrieve recent actions with optional filters |
| **Auth Required** | No |
| **Dependencies** | PostgreSQL |

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max results (1-500) |
| `status` | string | - | Filter by status |
| `target` | string | - | Filter by target |

**Request:**
```http
GET /api/v1/actions?limit=20&status=completed
```

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
    },
    {
      "id": 2,
      "target": "api-gateway",
      "action": "scale-up",
      "status": "completed",
      "details": null,
      "started_at": "2026-01-20T12:30:00Z"
    }
  ]
}
```

**Frontend Use Case:** Actions table, activity feed, audit log

---

### 3.3 Get Action by ID

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/actions/{action_id}` |
| **Method** | `GET` |
| **Description** | Get details of a specific action |
| **Auth Required** | No |
| **Dependencies** | PostgreSQL |

**Request:**
```http
GET /api/v1/actions/1
```

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

**Error (404):**
```json
{
  "detail": "Action with id 999 not found"
}
```

**Frontend Use Case:** Action detail modal, drill-down view

---

### 3.4 Get Actions by Status

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/actions/status/{action_status}` |
| **Method** | `GET` |
| **Description** | Filter actions by status |
| **Auth Required** | No |
| **Dependencies** | PostgreSQL |

**Valid Statuses:** `pending`, `running`, `completed`, `failed`, `cancelled`

**Request:**
```http
GET /api/v1/actions/status/pending?limit=10
```

**Response (200 OK):**
```json
{
  "count": 3,
  "actions": [
    {
      "id": 5,
      "target": "db-service",
      "action": "restart",
      "status": "pending",
      "details": "Awaiting execution",
      "started_at": "2026-01-20T12:40:00Z"
    }
  ]
}
```

**Frontend Use Case:** Status filter tabs, pending actions widget

---

### 3.5 Actions Health Check

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/actions/health` |
| **Method** | `GET` |
| **Description** | Check actions service health |
| **Auth Required** | No |
| **Dependencies** | None |

**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "actions"
}
```

---

## 4. Policies Endpoints

### 4.1 Create Policy

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies` |
| **Method** | `POST` |
| **Description** | Create a new monitoring policy |
| **Auth Required** | No |
| **Dependencies** | Policy Engine (in-memory registry) |

**Request Payload:**
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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | ✅ | Unique policy name |
| `description` | string | ❌ | Human-readable description |
| `severity` | string | ❌ | `info`, `warning`, `critical` (default: `warning`) |
| `target` | string | ❌ | Target pattern (default: `all`) |
| `enabled` | boolean | ❌ | Start enabled (default: `true`) |
| `auto_remediate` | boolean | ❌ | Auto-execute action (default: `false`) |
| `condition` | object | ✅ | Condition configuration (see below) |
| `action` | string | ✅ | Action: `scale-up`, `restart`, `drain-pod`, `custom` |
| `params` | object | ❌ | Action parameters |

**Condition Types:**
```json
// Single condition
{ "type": "metric_exceeds", "metric": "cpu_percent", "threshold": 80 }
{ "type": "metric_below", "metric": "disk_free_percent", "threshold": 10 }

// Compound conditions
{
  "type": "all",
  "conditions": [
    { "type": "metric_exceeds", "metric": "cpu_percent", "threshold": 80 },
    { "type": "metric_exceeds", "metric": "memory_percent", "threshold": 90 }
  ]
}

{
  "type": "any",
  "conditions": [
    { "type": "metric_exceeds", "metric": "cpu_percent", "threshold": 95 },
    { "type": "metric_below", "metric": "disk_free_percent", "threshold": 5 }
  ]
}
```

**Response (201 Created):**
```json
{
  "name": "high-cpu-alert",
  "description": "Alert when CPU exceeds 80%",
  "severity": "warning",
  "target": "web-*",
  "enabled": true,
  "params": { "cooldown_seconds": 300 },
  "auto_remediate": false
}
```

**Frontend Use Case:** Policy creation form, wizard

---

### 4.2 List Policies

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies` |
| **Method** | `GET` |
| **Description** | List all registered policies |
| **Auth Required** | No |
| **Dependencies** | Policy Engine |

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
    },
    "low-disk-critical": {
      "name": "low-disk-critical",
      "description": "Critical alert for low disk space",
      "severity": "critical",
      "target": "all",
      "enabled": true,
      "params": {},
      "auto_remediate": true
    }
  },
  "total": 2,
  "enabled_count": 2
}
```

**Frontend Use Case:** Policies table, policy management dashboard

---

### 4.3 Get Policy

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies/{policy_name}` |
| **Method** | `GET` |
| **Description** | Get details of a specific policy |
| **Auth Required** | No |
| **Dependencies** | Policy Engine |

**Request:**
```http
GET /api/v1/policies/high-cpu-alert
```

**Response (200 OK):**
```json
{
  "name": "high-cpu-alert",
  "description": "Alert when CPU exceeds 80%",
  "severity": "warning",
  "target": "web-*",
  "enabled": true,
  "params": {},
  "auto_remediate": false
}
```

---

### 4.4 Update Policy

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies/{policy_name}` |
| **Method** | `PUT` |
| **Description** | Update an existing policy |
| **Auth Required** | No |
| **Dependencies** | Policy Engine |

**Request Payload (partial update):**
```json
{
  "description": "Updated description",
  "severity": "critical",
  "enabled": false,
  "params": { "replicas": 3 }
}
```

All fields are optional - only include fields to update.

**Response (200 OK):**
```json
{
  "name": "high-cpu-alert",
  "description": "Updated description",
  "severity": "critical",
  "target": "web-*",
  "enabled": false,
  "params": { "replicas": 3 },
  "auto_remediate": false
}
```

---

### 4.5 Delete Policy

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies/{policy_name}` |
| **Method** | `DELETE` |
| **Description** | Remove a policy |
| **Auth Required** | No |
| **Dependencies** | Policy Engine |

**Response (200 OK):**
```json
{
  "ok": true,
  "message": "Policy 'high-cpu-alert' deleted"
}
```

---

### 4.6 Enable Policy

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies/{policy_name}/enable` |
| **Method** | `PUT` |
| **Description** | Enable a disabled policy |
| **Auth Required** | No |
| **Dependencies** | Policy Engine |

**Response (200 OK):**
```json
{
  "ok": true,
  "message": "Policy 'high-cpu-alert' enabled"
}
```

**Frontend Use Case:** Toggle switch, enable button

---

### 4.7 Disable Policy

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies/{policy_name}/disable` |
| **Method** | `PUT` |
| **Description** | Disable an enabled policy |
| **Auth Required** | No |
| **Dependencies** | Policy Engine |

**Response (200 OK):**
```json
{
  "ok": true,
  "message": "Policy 'high-cpu-alert' disabled"
}
```

---

### 4.8 Reload Policies

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies/reload` |
| **Method** | `POST` |
| **Description** | Reload policies from configuration files |
| **Auth Required** | No |
| **Dependencies** | Policy Engine, Config Files |

**Response (200 OK):**
```json
{
  "ok": true,
  "message": "Policies reloaded successfully (5 policies)"
}
```

**Frontend Use Case:** Reload button, sync with config files

---

### 4.9 Get Policies by Severity

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies/severity/{severity}` |
| **Method** | `GET` |
| **Description** | Filter policies by severity level |
| **Auth Required** | No |
| **Dependencies** | Policy Engine |

**Valid Severities:** `info`, `warning`, `critical`

**Request:**
```http
GET /api/v1/policies/severity/critical
```

**Response (200 OK):**
```json
{
  "ok": true,
  "policies": {
    "low-disk-critical": {
      "name": "low-disk-critical",
      "description": "Critical alert for low disk space",
      "severity": "critical",
      "target": "all",
      "enabled": true,
      "params": {},
      "auto_remediate": true
    }
  },
  "total": 1,
  "enabled_count": 1
}
```

**Frontend Use Case:** Severity filter tabs, critical alerts widget

---

### 4.10 Get Policy Runner Status

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies/runner/status` |
| **Method** | `GET` |
| **Description** | Get background policy runner status |
| **Auth Required** | No |
| **Dependencies** | Policy Runner |

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

**Frontend Use Case:** Runner status indicator, system health dashboard

---

## 5. Policy Tester Endpoints

### 5.1 Evaluate Policies

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/policies/evaluate` |
| **Method** | `POST` |
| **Description** | Test policies against provided metrics |
| **Auth Required** | No |
| **Dependencies** | Policy Engine |

**Request Payload:**
```json
{
  "metrics": {
    "cpu_percent": 95,
    "memory_percent": 88,
    "disk_free_percent": 10
  },
  "target": "web-server-01"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `metrics` | object | ✅ | Metric name-value pairs |
| `target` | string | ❌ | Target resource filter |

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

**Frontend Use Case:** Policy testing sandbox, "what-if" simulation, debugging tool

---

## 6. Queue Monitor Endpoints (Planned)

> ⚠️ **Status:** These endpoints are planned but not yet implemented in the API.
> They exist in documentation and test files but need to be wired.

### 6.1 Queue Stats (Planned)

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/ui/queue/stats` |
| **Method** | `GET` |
| **Description** | Get remediation queue statistics |
| **Auth Required** | No |
| **Dependencies** | Redis |

**Expected Response:**
```json
{
  "ok": true,
  "queue": {
    "queue_length": 5,
    "tasks_enqueued": 1234,
    "tasks_dequeued": 1229,
    "tasks_failed": 3,
    "tasks_completed": 1226,
    "last_processed_task": {
      "task_id": "task_1705753200123",
      "action_id": 456,
      "target": "web-service",
      "timestamp": "2026-01-20T12:00:00Z"
    }
  }
}
```

**Frontend Use Case:** Queue depth gauge, worker status, processing metrics

---

## 7. Simulator Endpoints (Planned)

> ⚠️ **Status:** These endpoints are planned but not yet implemented.
> The simulator service exists but API routes need to be added.

### 7.1 Start Simulator (Planned)

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/ui/simulator/start` |
| **Method** | `POST` |
| **Description** | Start load simulator |
| **Dependencies** | Simulator Service |

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `rate` | int | 100 | Events per minute |
| `mode` | string | `steady` | Mode: `steady`, `burst`, `ramp`, `chaos` |
| `failure_rate` | float | 0.0 | Failure injection rate (0.0-1.0) |
| `timeout_rate` | float | 0.0 | Timeout injection rate |
| `malformed_rate` | float | 0.0 | Malformed payload rate |

### 7.2 Stop Simulator (Planned)

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/ui/simulator/stop` |
| **Method** | `POST` |
| **Description** | Stop load simulator |

### 7.3 Get Simulator Status (Planned)

| Property | Value |
|----------|-------|
| **Route** | `/api/v1/ui/simulator/status` |
| **Method** | `GET` |
| **Description** | Get simulator status and metrics |

---

## Endpoint Summary

### ✅ Ready for Frontend Integration (21 endpoints)

| Group | Endpoint | Method | Status |
|-------|----------|--------|--------|
| Health | `/health` | GET | ✅ Ready |
| Health | `/metrics` | GET | ✅ Ready |
| Ingest | `/api/v1/ingest` | POST | ✅ Ready |
| Ingest | `/api/v1/ingest/health` | GET | ✅ Ready |
| Ingest | `/api/v1/ingest/agent/metrics` | POST | ✅ Ready |
| Actions | `/api/v1/actions` | POST | ✅ Ready |
| Actions | `/api/v1/actions` | GET | ✅ Ready |
| Actions | `/api/v1/actions/{action_id}` | GET | ✅ Ready |
| Actions | `/api/v1/actions/status/{status}` | GET | ✅ Ready |
| Actions | `/api/v1/actions/health` | GET | ✅ Ready |
| Policies | `/api/v1/policies` | POST | ✅ Ready |
| Policies | `/api/v1/policies` | GET | ✅ Ready |
| Policies | `/api/v1/policies/{name}` | GET | ✅ Ready |
| Policies | `/api/v1/policies/{name}` | PUT | ✅ Ready |
| Policies | `/api/v1/policies/{name}` | DELETE | ✅ Ready |
| Policies | `/api/v1/policies/{name}/enable` | PUT | ✅ Ready |
| Policies | `/api/v1/policies/{name}/disable` | PUT | ✅ Ready |
| Policies | `/api/v1/policies/evaluate` | POST | ✅ Ready |
| Policies | `/api/v1/policies/reload` | POST | ✅ Ready |
| Policies | `/api/v1/policies/severity/{sev}` | GET | ✅ Ready |
| Policies | `/api/v1/policies/runner/status` | GET | ✅ Ready |

### ⚠️ Endpoints Needing Implementation (Planned)

| Group | Endpoint | Method | Status |
|-------|----------|--------|--------|
| Queue | `/api/v1/ui/queue/stats` | GET | ⚠️ Planned |
| Simulator | `/api/v1/ui/simulator/start` | POST | ⚠️ Planned |
| Simulator | `/api/v1/ui/simulator/stop` | POST | ⚠️ Planned |
| Simulator | `/api/v1/ui/simulator/status` | GET | ⚠️ Planned |

### ❌ Internal-Only (Not for Frontend)

| Endpoint | Purpose |
|----------|---------|
| `/api/v1/ingest/agent/metrics` | Go agent internal use (same as `/ingest`) |

---

## Error Handling

### Standard Error Response

```json
{
  "detail": "Error message describing the issue"
}
```

### HTTP Status Codes

| Code | Meaning | When Used |
|------|---------|-----------|
| 200 | OK | Successful GET, PUT, DELETE |
| 201 | Created | Successful POST |
| 400 | Bad Request | Validation error, invalid input |
| 404 | Not Found | Resource doesn't exist |
| 422 | Validation Error | Pydantic validation failed |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Server Error | Internal error |

### Validation Error Response (422)

```json
{
  "detail": [
    {
      "loc": ["body", "name"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## Dependencies

### Service Dependencies

| Service | Required For | Connection |
|---------|--------------|------------|
| **PostgreSQL** | Metrics, Actions | `DATABASE_URL` |
| **Redis** | Queue, Rate Limiting | `REDIS_URL` (port 6380) |
| **Policy Engine** | Policy CRUD, Evaluation | In-memory (app process) |
| **Prometheus** | Metrics endpoint | Internal metrics module |

### Connection Configuration

```bash
# Environment variables
DATABASE_URL=postgresql+asyncpg://vigil:vigil@localhost:5432/vigil
REDIS_URL=redis://localhost:6380/0
```

### Health Check Dependencies

| Endpoint | Dependencies |
|----------|--------------|
| `/health` | None (always responds) |
| `/api/v1/ingest/health` | None |
| `/api/v1/actions/health` | None |
| `/api/v1/policies/runner/status` | Policy Runner module |

---

## CORS Configuration

The API allows requests from:
- `http://localhost:3000` (React dev server)
- `http://localhost:5173` (Vite dev server)
- `http://127.0.0.1:3000`
- `http://127.0.0.1:5173`

---

## TypeScript Types

See [sdk/typescript/vigil-api-client.ts](../sdk/typescript/vigil-api-client.ts) for complete TypeScript interfaces.

Quick type reference:
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

---

## Interactive Documentation

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **OpenAPI JSON:** http://localhost:8000/openapi.json

---

*Last updated: January 20, 2026*
