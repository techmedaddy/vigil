
# Vigil

**Backend-Only Monitoring & Self-Healing System**

Vigil is a lightweight self-healing and drift-detection system inspired by GitOps and Kubernetes operators. It provides a pure backend API service connecting Go-based agents and remediation workers with a FastAPI control plane for metrics ingestion, policy evaluation, drift detection, and automated remediation.

> **Note:** Vigil is now a **backend-only** service. All UI/frontend code has been removed. For dashboard and visualization needs, integrate with external frontend solutions (e.g., Google AI Studio, Grafana, custom React/Vue apps, or any HTTP client).

## Status Note

> Vigil started as a personal learning experiment for self-healing infrastructure and is now evolving into a more capable, modular project. It is still actively being worked on.

This repository favors clarity over production-hardening and receives frequent changes while the core architecture evolves.

## Features

- **Pure Backend API:** RESTful endpoints for metrics ingestion, policy management, actions, and queue stats
- **End-to-end self-healing loop:** agent metrics → policy evaluation → remediation actions → audit trail
- **GitOps-style drift detection:** GitOpsD daemon watches manifests and raises actions when desired state diverges
- **Policy Engine:** Configurable threshold-based and custom logic policies with auto-remediation
- **YAML-first configuration:** Environment variable overrides for every service
- **Docker Compose stack:** Local development with PostgreSQL/Redis
- **Kubernetes ready:** K8s manifests for cluster deployment
- **Failure simulation:** Tooling to exercise remediation paths without touching real workloads
- **Frontend agnostic:** Integrate with any UI framework or monitoring dashboard via REST API

## System Overview

### Collector/API (FastAPI, Python)

- **Backend-only REST API** running the ingest endpoint, policy evaluation loop, storage adapters, and action management (`python/app`)
- Persists telemetry to SQLite for local runs or PostgreSQL/Redis when started via Docker Compose
- Emits remediation requests over HTTP and records action history under `/api/v1/actions`
- **No built-in UI** - all endpoints return JSON for external frontend integration

### Agent (Go)

- Configured via `configs/agent.yaml` to emit metrics (CPU, HTTP checks, or custom collectors) every interval to the collector.
- Lives under `go/agent` with a small scheduler and pluggable metric sources.

### GitOps Drift Detector (Go)

- Watches the `manifests/` directory (and any Git working tree you mount) for desired state definitions.
- Detects drift by comparing manifests with live cluster signals and files action requests through the collector.

### Remediator (Go)

- Implements action handlers (`go/remediator/pkg/actions`) that restart services, patch manifests, or call external APIs
- Posts audit results back to the collector, ensuring the control loop can correlate cause and effect

### Configs Folder (YAML behavior)

- `configs/*.yaml` capture every service’s defaults (ports, polling intervals, downstream URLs). These files are mounted into containers and can be overridden via environment variables.

### Manifests Folder (desired state)

- `manifests/` holds example services, alerts, and policies. GitOpsD treats it as the canonical desired state for drift detection demos.

### Tools & Simulation Scripts

- `simulate_failures.py` injects synthetic anomalies so you can observe end-to-end remediation.
- Additional helper docs live under `tools/`.

### Docker Compose Workflow

- `docker-compose.yml` bootstraps PostgreSQL, Redis, the FastAPI collector, GitOpsD, the Go agent, and the remediator in one command for a realistic multi-service demo.

### Kubernetes Manifests (optional)

- `k8s/` contains deployment specs for running the collector, agent, GitOpsD, and remediator inside a cluster. They are reference-grade and meant for experimentation, not production.

## Architecture Diagram

```text
+-----------------------------+
|        Dashboard UI         |
| (python/app/static/*.html)  |
+-------------+---------------+
┌───────────┐   metrics   ┌──────────────────┐   state   ┌─────────────┐
│ Go Agent  │ ───────────▶│  Collector/API   │ ────────▶│ PostgreSQL* │
│ (metrics) │             │  FastAPI + eval  │          │   /SQLite   │
└───────────┘             └─────────┬────────┘          └─────────────┘
                                     │
                                     │ remediation requests
                                     v
                            ┌──────────────────┐
                            │   Remediator     │
                            │  (Go handlers)   │
                            └─────────┬────────┘
                                     │ audits
                                     v
                            ┌──────────────────┐
                            │   /actions API   │
                            └──────────────────┘

┌───────────┐   manifests   ┌──────────────────┐
│ GitOpsD   │──────────────▶│ Collector /actions│
│ (drift)   │◀──────────────┤ Redis* (events)   │
└───────────┘               └──────────────────┘

*SQLite is used for local development, PostgreSQL + Redis are provisioned by docker-compose.

External Frontend Integration:
  - Connect to REST API endpoints via HTTP
  - Build custom dashboards with React, Vue, Angular
  - Use monitoring tools like Grafana, Google AI Studio
  - CLI tools can consume JSON responses directly
```text
vigil/
├─ docker-compose.yml         # Full local stack (Postgres, Redis, API, agents)
├─ README.md                  # This guide
├─ docs/                      # Detailed architecture, config, and extending guides
├─ go/
│  ├─ agent/                  # Metric collectors and CLI entrypoint
│  ├─ gitopsd/                # Drift detector daemon and helpers
│  └─ remediator/             # Action registry and remediation server
├─ python/
│  └─ app/                    # FastAPI collector, services, schemas, dashboard
├─ configs/                   # YAML conbackend API, services, schemas
├─ manifests/                 # Desired state, alerts, services for GitOpsD
├─ k8s/                       # Optional Kubernetes deployment manifests
├─ tools/                     # Helper documentation and utilities
└─ simulate_failures.py       # Fault-injection script for local testing
```

## How It Works

1. Agents emit metrics (CPU, latency, synthetic probes) on a configurable interval and POST them to the collector.
2. **Agents emit metrics** (CPU, latency, synthetic probes) on a configurable interval and POST them to the collector at `/api/v1/ingest`
2. **Collector stores and evaluates** each metric, enriches context from Redis/PostgreSQL, and evaluates registered policy rules
3. **Policies trigger actions** - decide whether to enqueue remediation requests (restart service, scale replica) or simply record telemetry
4. **Remediator executes** - workers pick up requests, execute Go handlers, and post audit results back to `/api/v1/actions`
5. **GitOpsD detects drift** - continuously compares `manifests/` with real state and files actions whenever divergence is detected
6. **External frontends consume** - REST API endpoints expose current metrics, action history, and drift summaries as JSON for external dashboards and tools
## Tech Stack

| Layer                | Technology |
|----------------------|------------|
| Collector/API        | Python 3.12, FastAPI, Uvicorn, SQLAlchemy |
| Agents & Remediator  | Go 1.23+, standard library HTTP, pluggable packages |
| Drift Detection      | Go GitOpsD service with filesystem/Git walkers |
| Storage              | SQLite (local), PostgreSQL + Redis (compose) |
| Packaging            | Docker Compose, Kubernetes manifests |
| Frontend             | **None (bring your own)** - REST API only |

## Getting Started

### Prerequisites

- Go 1.23 or newer
- Python 3.12 or newer with `pip`
- Docker Desktop (for Compose workflow)
- kubectl + a cluster (optional, for `k8s/` manifests)

### Clone the repository

```powershell
git clone https://github.com/techmedaddy/vigil.git
cd vigil
```

### Option A — Run everything with Docker Compose

```powershell
docker compose up --build
```

The command launches PostgreSQL, Redis, the FastAPI API, GitOpsD, the Go agent, and the remediator. Logs stream in the terminal, and the collector becomes available at `http://localhost:8000`.

### Option B — Run services manually

```powershell
# In one terminal (collector)
cd python/app
pip install -r ../requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# In a second terminal (remediator)
cd go/remediator/cmd/remediator
go run .

# In a third terminal (agent)
cd go/agent/cmd/agent
go run .

# Optional GitOpsD
cd go/gitopsd/cmd/gitopsd
go run .
```

### Environment Variables

| Variable            | Default (YAML)                            | Purpose |
|--------------------|-------------------------------------------|---------|
| `DATABASE_URL`     | `sqlite:///python/app/vigil.db` or Compose Postgres URI | Controls the collector’s persistence backend. |
| `REDIS_URL`        | `redis://127.0.0.1:6379/0` (Compose overrides) | Used for pub/sub style evaluation contexts. |
| `COLLECTOR_PORT`   | `8000`                                    | Port exposed by FastAPI. |
| `REMEDIATOR_URL`   | `http://127.0.0.1:8081/remediate`         | Where the collector posts remediation actions. |
| `AGENT_INTERVAL`   | `10` seconds                              | Metric publishing cadence per `configs/agent.yaml`. |
| `GITOPSD_INTERVAL` | `15` seconds                              | Drift polling cadence per `configs/gitopsd.yaml`. |
| `CONFIG_PATH`      | `configs/*.yaml`                          | Path mounted into API/agents; override to switch profiles. |

Any value defined in `configs/*.yaml` can be overridden by exporting the corresponding environment variable before starting a service or Compose stack.

## Configuration

- Centralized configuration details, schema references, and override patterns live in [`docs/CONFIG.md`](docs/CONFIG.md).
- Sample YAML files in `configs/` demonstrate sane defaults for local testing. Copy them and adjust intervals, endpoint URLs, and feature flags as needed.

## API Overview

**Backend REST API Endpoints:**

```http
# Metrics Ingestion
POST /api/v1/ingest
Content-Type: application/json
{
  "name": "cpu_usage",
  "value": 0.82,
  "tags": {"service": "web"},
  "timestamp": "2026-01-19T12:00:00Z"
}

# Actions Management
POST /api/v1/actions
GET /api/v1/actions
GET /api/v1/actions/{action_id}

# Policy Management
GET /api/v1/policies
POST /api/v1/policies
PUT /api/v1/policies/{name}
DELETE /api/v1/policies/{name}
POST /api/v1/policies/evaluate
POST /api/v1/policies/reload

# Queue Stats
GET /api/v1/queue/stats

# Health Check
GET /health

# Prometheus Metrics
GET /metrics
```

**OpenAPI Documentation:**
- Interactive API docs available at `http://localhost:8000/docs`
- ReDoc format at `http://localhost:8000/redoc`

**Frontend Integration Examples:**
```javascript
// Fetch recent metrics
const response = await fetch('http://localhost:8000/api/v1/ingest');
const data = await response.json();

// Create a policy
await fetch('http://localhost:8000/api/v1/policies', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    name: 'high-cpu',
    condition: { type: 'metric_exceeds', metric: 'cpu_percent', threshold: 90 },
    action: 'scale-up'
  })
});
```

## Simulating Failures

- Run `simulate_failures.py` from the project root to push high CPU metrics, inject artificial drift events, and watch remediation kicks in.

```powershell
python simulate_failures.py --burst 5 --drift manifests/services/web.service.yaml
```

- Use the script in tandem with the dashboard or `/query` endpoint to verify the full loop.

## Extending Vigil

- A dedicated guide in [`docs/EXTENDING.md`](docs/EXTENDING.md) covers adding metric collectors, authoring policies, creating remediation handlers, building dashboards, and embedding Vigil components into other systems.
- Follow the repo conventions: Go services live under `go/<service>`, FastAPI modules under `python/app`, and configuration defaults under `configs/`.

## Roadmap

- **Backend API enhancements:** Historical windows, anomaly detection, pluggable scoring adapters
- **GitOpsD expansion:** Support Helm, Kustomize, and signed commits
- **Security:** Authentication, TLS, RBAC for multi-team scenarios
- **Monitoring integration:** Native Prometheus exporters, OpenTelemetry support
- **Deployment tools:** Helm charts and Terraform modules for production

**Note:** Dashboard/UI features have been removed. Frontend integration is expected via external tools (Grafana, custom React/Vue apps, Google AI Studio, etc.)


