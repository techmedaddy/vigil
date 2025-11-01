# Vigil — Self‑Healing Infrastructure Agent

Vigil is an opinionated, developer-focused self-healing infrastructure system. It demonstrates a small, end-to-end automation control plane where lightweight Go agents emit metrics to a Python/FastAPI collector which stores telemetry in SQLite and triggers remediation actions handled by a Go remediator. The project is built for clarity and local testing; it’s intended as a foundation for production-grade features such as GitOps-driven remediation, policy rules, and robust circuit-breaking behavior.

## Architecture

```bash
 ┌──────────────┐        ┌────────────────┐        ┌────────────────────┐
 │   Agent (Go) │  --->  │  Collector/API │  --->  │   SQLite Database  │
 │  (metrics)   │        │  (FastAPI app) │        │   (vigil.db)       │
 └──────────────┘        └────────────────┘        └────────────────────┘
          │                         │
          │                         │
          │                         ▼
          │               ┌────────────────┐
          │               │  Policy Engine │
          │               │ (Python module)│
          │               └────────────────┘
          │                         │
          │                         ▼
          │               ┌────────────────┐
          │               │ Remediator (Go)│
          │               │ auto-actions   │
          │               └────────────────┘
          │                         │
          ▼                         ▼
 ┌────────────────┐         ┌────────────────┐
 │ GitOpsD (Go)   │  --->   │ Collector/API  │
 │ (drift watcher)│         │   /actions     │
 └────────────────┘         └────────────────┘

```

## Features

- Collector (FastAPI)
  - Receives metrics on `POST /ingest`
  - Persists metrics to SQLite (`metrics` table)
  - Triggers remediation when `cpu_usage > 0.8`
  - Accepts audit posts from the remediator to `POST /actions`
- Agent (Go)
  - Periodically (every 10s) sends mocked CPU metrics to the collector
  - Lightweight, single-file implementation for fast iteration
- Remediator (Go)
  - Exposes `POST /remediate` on port `8081`
  - Simulates restart actions and reports audit logs back to collector

Planned features (short): policy rules engine, GitOps integration, circuit-breaker for remediation calls, richer telemetry, authentication and TLS.

## Storage Schema

Collector stores two primary tables in `vigil.db`:

- `metrics(id, name, value, ts)`
- `actions(id, target, action, status, details, started_at)`

Example SQL used by the collector when initializing the DB is included in `python/app/main.py`.

## Requirements

- Go 1.23+
- Python 3.12+
- pip (for Python dependencies)
- SQLite (bundled with Python stdlib)

Tested on Windows using PowerShell; Linux/macOS should behave the same but paths/commands may differ slightly.

## Quickstart — clone & prepare

Open a PowerShell terminal and run:

```powershell
git clone https://github.com/techmedaddy/vigil.git
cd vigil

# Python virtualenv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r python/requirements.txt

# Build Go binaries (creates agent.exe and remediator.exe in their package dirs)
cd go\agent\cmd\agent
go build -o agent.exe main.go
cd ..\..\..\remediator\cmd\remediator
go build -o remediator.exe main.go

# Back to repo root
cd ..\..\..\..\
```

Notes:
- On Unix-like systems use `source .venv/bin/activate` instead of the PowerShell Activate script.
- The Go builds above produce platform-native executables. You may also run with `go run ./...` in each subfolder for development.

## Run instructions (each component)

1. Collector (FastAPI)

```powershell
cd python\app
# Use uvicorn to run the FastAPI app (host 127.0.0.1:8000)
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

2. Remediator (Go)

```powershell
cd go\remediator\cmd\remediator
.\remediator.exe
# remediator listens on port 8081 for POST /remediate
```

3. Agent (Go)

```powershell
cd go\agent\cmd\agent
.\agent.exe
# agent sends a metric every 10s to http://127.0.0.1:8000/ingest
```

Run order: start the collector first, then the remediator, then one or more agents.

## Example curl tests

# 1) Send a metric manually
```powershell
curl -X POST http://127.0.0.1:8000/ingest -H "Content-Type: application/json" -d '{"name": "cpu_usage", "value": 0.12}'
```

# 2) Trigger remediation by sending a high cpu metric
```powershell
curl -X POST http://127.0.0.1:8000/ingest -H "Content-Type: application/json" -d '{"name": "cpu_usage", "value": 0.95}'
```

# 3) Query latest metrics
```powershell
curl http://127.0.0.1:8000/query
```

# 4) Call remediator directly
```powershell
curl -X POST http://127.0.0.1:8081/remediate -H "Content-Type: application/json" -d '{"service": "web", "action": "restart"}'
```

## Current status

- Collector: implemented in `python/app/main.py`. Accepts `/ingest`, persists `metrics`, triggers remediator when `cpu_usage > 0.8`. Also exposes `/query`.
- Agent: implemented at `go/agent/cmd/agent/main.go`. Sends a mocked `cpu_usage` metric every 10s.
- Remediator: implemented at `go/remediator/cmd/remediator/main.go`. Listens on `8081` and simulates remediation; posts action audit records back to the collector.
- SQLite DB `vigil.db` is initialised automatically by the collector if not present.

Everything is wired end-to-end locally: agent -> collector -> remediator -> collector.

## Troubleshooting

- If Go build fails due to multiple `main` functions in the same directory: ensure you build the specific package or move auxiliary demo mains (`test.go`, `nettest.go`) into separate subdirectories. The repository contains small helper mains for manual tests — they are not required to build the primary agent/remediator binaries.
- If `requests` or other Python packages are missing, ensure the virtualenv is activated and `pip install -r python/requirements.txt` completes successfully.
- If remediator cannot reach the collector, verify collector is running at `127.0.0.1:8000` and that no firewall is blocking loopback ports.

## Roadmap / Next steps

Short-term (next 1–2 sprints):
- Move helper mains into `cmd/` subfolders so each binary builds independently.
- Add a policy rules engine to define remediation triggers beyond simple thresholds (e.g., historical baselines, anomaly detection).
- Implement a simple circuit breaker around remediation calls to avoid repeated noisy actions.

Mid-term:
- GitOps daemon: allow remediation actions to be expressed as Git commits (and optionally applied via an operator).
- Authentication / mTLS between agents, collector, and remediator.
- Structured logging and metrics (Prometheus) for the control plane.

Long-term:
- Multi-tenant operation, RBAC, and a web UI for rule authoring and audit timelines.


