# Vigil API - AI/Frontend Quick Reference

> Base URL: `http://localhost:8000` | Content-Type: `application/json`

## 1. Health & Metrics

```
GET /health                    → { status, service }
GET /metrics                   → Prometheus text format
```

## 2. Metrics Ingestion

```
POST /api/v1/ingest
Body: { name: string, value: number, tags?: object }
→ 201 { ok, metric_id, message }

GET /api/v1/ingest/health      → { status: "healthy" }
```

## 3. Actions (CRUD)

```
POST /api/v1/actions
Body: { target: string, action: string, status?: string, details?: string }
→ 201 { ok, action_id, message }

GET /api/v1/actions?limit=50&status=pending&target=web
→ { count, actions: [{ id, target, action, status, details, started_at }] }

GET /api/v1/actions/{id}
→ { id, target, action, status, details, started_at }

GET /api/v1/actions/status/{status}
→ { count, actions: [...] }

GET /api/v1/actions/health
→ { status: "healthy" }
```

Valid statuses: `pending`, `running`, `completed`, `failed`, `cancelled`

## 4. Policies (Full CRUD)

```
POST /api/v1/policies
Body: {
  name: string,           // required, unique
  description?: string,
  severity?: "info"|"warning"|"critical",
  target?: string,        // default: "all"
  enabled?: boolean,      // default: true
  auto_remediate?: boolean,
  condition: {            // required
    type: "metric_exceeds"|"metric_below"|"all"|"any",
    metric?: string,
    threshold?: number,
    conditions?: [...]    // for all/any
  },
  action: "scale-up"|"restart"|"drain-pod"|"custom",
  params?: object
}
→ 201 PolicyInfo

GET /api/v1/policies
→ { ok, policies: { [name]: PolicyInfo }, total, enabled_count }

GET /api/v1/policies/{name}
→ PolicyInfo

PUT /api/v1/policies/{name}
Body: { description?, severity?, target?, enabled?, auto_remediate?, params? }
→ PolicyInfo

DELETE /api/v1/policies/{name}
→ { ok, message }

PUT /api/v1/policies/{name}/enable
→ { ok, message }

PUT /api/v1/policies/{name}/disable
→ { ok, message }

POST /api/v1/policies/reload
→ { ok, message }

GET /api/v1/policies/severity/{severity}
→ { ok, policies, total, enabled_count }

GET /api/v1/policies/runner/status
→ { ok, runner: { enabled, running, interval_seconds, batch_size } }
```

## 5. Policy Evaluation (Testing)

```
POST /api/v1/policies/evaluate
Body: {
  metrics: { [metric_name]: value },
  target?: string
}
→ {
  ok: true,
  violations: [{ policy_name, severity, description, target, timestamp }],
  actions_triggered: [{ action, target, status, params }],
  timestamp
}
```

## Types Summary

```typescript
type Severity = "info" | "warning" | "critical";
type ActionType = "scale-up" | "restart" | "drain-pod" | "custom";
type ActionStatus = "pending" | "running" | "completed" | "failed" | "cancelled";
type ConditionType = "metric_exceeds" | "metric_below" | "all" | "any";

interface PolicyInfo {
  name: string;
  description: string;
  severity: Severity;
  target: string;
  enabled: boolean;
  params: Record<string, any>;
  auto_remediate: boolean;
}

interface ActionDetail {
  id: number;
  target: string;
  action: string;
  status: ActionStatus;
  details: string | null;
  started_at: string; // ISO 8601
}
```

## Error Format

```json
{ "detail": "Error message" }
```

Codes: 400 (bad request), 404 (not found), 422 (validation), 500 (server error)

## Dependencies

| Feature | Requires |
|---------|----------|
| Metrics/Actions | PostgreSQL |
| Queue/Rate Limit | Redis (port 6380) |
| Policies | Policy Engine (in-memory) |

## Endpoint Status

✅ **21 Ready:** All endpoints listed above  
⚠️ **4 Planned:** `/api/v1/ui/queue/stats`, `/api/v1/ui/simulator/*`  
❌ **Internal:** `/api/v1/ingest/agent/metrics` (agent-only alias)
