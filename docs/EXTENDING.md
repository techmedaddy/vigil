# Extending Vigil

This guide describes the extension points across Vigil's control plane so you can add new telemetry, policies, remediation actions, dashboard integrations, and custom persistence without breaking the existing self-healing loop. The instructions assume familiarity with Go, Python (FastAPI), and the repository layout under `go/` and `python/`.

## Repo Orientation and Coding Guidelines

- Place Go code inside the corresponding service folder under `go/<service>/` and keep binaries inside `cmd/<service>`; shared packages belong in `go/<service>/pkg/...`.
- Python collector code lives under `python/app/`; create new FastAPI routers in `python/app/routes/` and business logic in `python/app/services/` or `python/app/models/`.
- Name files using lower_snake_case for Python (`evaluator.py`, `metrics_router.py`) and lowerCamelCase for Go identifiers, with packages named using short lowercase nouns.
- Adhere to existing code structure: keep metric definitions in `agent` packages, policies inside `python/app/services/evaluator.py`, and remediation handlers in `go/remediator/pkg/actions`.
- Add docstrings or comments only where logic isn't obvious; follow Go's `golint` guidance and Black formatting for Python (`python -m black`).

## Adding New Metric Types

### Agent Side (Go)

- Define a collector under `go/agent/pkg/metrics/`. Create a struct implementing a `Collect(ctx context.Context) ([]Metric, error)` style function used by the scheduler.
- Register the collector in `go/agent/cmd/agent/main.go` when building the metric pipeline:

```go
// go/agent/pkg/metrics/custom.go
type HttpCheck struct {
    client *http.Client
    url    string
}

func (c *HttpCheck) Collect(ctx context.Context) ([]Metric, error) {
    req, _ := http.NewRequestWithContext(ctx, http.MethodGet, c.url, nil)
    start := time.Now()
    resp, err := c.client.Do(req)
    latency := time.Since(start).Milliseconds()
    return []Metric{{
        Name:  "http_latency_ms",
        Value: float64(latency),
        Tags:  map[string]string{"url": c.url},
        Error: err,
    }}, nil
}
```

- Wire it to configuration by extending `configs/agent.yaml` (`metrics.custom` list) and updating the loader in `go/agent/pkg/config/config.go`.

### Collector Side (FastAPI)

- Extend schema validation in `python/app/schemas/metrics.py` to accept new fields.
- Add normalization logic to `python/app/services/evaluator.py` or `python/app/services/ingest.py` to map both agent-generated and manual metrics to consistent column names.
- Update migrations if new columns are needed. Use Alembic or `python/app/db/migrations/` to add indexes for high cardinality tags.

## Creating New Policy Rules (`python/app/services/evaluator.py`)

Policies are Python classes implementing a `match(metric, history, desired_state)` interface.

```python
class ErrorRatePolicy(BasePolicy):
    name = "high_error_rate"

    async def evaluate(self, metric: MetricEvent, ctx: EvaluationContext) -> Optional[ActionRequest]:
        if metric.name != "error_rate":
            return None
        window = await ctx.history(metric.name, minutes=5)
        if statistics.mean(window) > 0.05:
            return ActionRequest(
                target=metric.tags.get("service"),
                action="scale_up",
                reason="error_rate_threshold",
            )
        return None
```

Steps:

- Create a new class under `python/app/services/policies/` when logic grows beyond a few lines and import it in `evaluator.py`.
- Register the policy in the evaluator factory list so it participates in the evaluation loop.
- Add unit tests under `python/app/tests/policies/` and include representative fixtures in `python/app/tests/fixtures/`.

## Adding Remediation Actions (Go Remediator)

1. Implement a handler in `go/remediator/pkg/actions`. Handlers satisfy an interface (e.g., `Execute(ctx context.Context, req Request) Result`).
2. Register the handler in `go/remediator/pkg/actions/registry.go` (map from action string to handler).
3. Add configuration support in `configs/remediator.yaml` under the `actions:` list and parse it in `go/remediator/pkg/config`.
4. Ensure audit logging captures success/failure via `go/remediator/pkg/audit` when the handler completes.
5. Write unit tests with `go test ./go/remediator/pkg/actions/...` and add integration coverage using docker-compose when dependent systems are involved.

## Extending GitOpsD (Go)

- **Additional directories:** Update `configs/gitopsd.yaml` `manifests.sources` and adjust `go/gitopsd/pkg/manifest/loader.go` to walk new directories.
- **Resource types:** Add new parsers in `go/gitopsd/pkg/manifest/types/`. Keep types small and provide a `Diff(desired, observed)` function for the evaluator.
- **Polling behavior:** Modify `sync.Interval` or implement adaptive polling by editing `go/gitopsd/pkg/sync/runner.go` (respect `min_interval`/`max_interval`).
- **Git providers:** Extend `go/gitopsd/pkg/git/provider.go` with new provider implementations; ensure credentials are fetched via environment variables to avoid storing secrets in config files.

## Building Custom Dashboards

- FastAPI serves static files from `python/app/static/`. Add HTML/JS dashboards there for lightweight UIs.
- For React or more complex frontends, create a separate project under `python/app/static/dashboard/` or a top-level `ui/` directory. Use the Collector API (`/query`, `/drift`, `/actions`) for data.
- When building SPAs, enable CORS in `configs/collector.yaml` (`security.allowed_origins`) and configure environment-specific API base URLs.
- Consider using WebSocket streaming (via FastAPI `WebSocketRoute`) to push metric updates if you need near real-time visuals.

## Exposing New API Endpoints (FastAPI Collector)

1. Create a router module in `python/app/routes/`, e.g., `python/app/routes/alerts.py`.
2. Define Pydantic models in `python/app/schemas/alerts.py` and business logic in `python/app/services/alerts.py`.
3. Register the router in `python/app/main.py`:

```python
from app.routes import alerts

app.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
```

4. Add tests under `python/app/tests/routes/test_alerts.py` using FastAPI's `TestClient`.
5. Document the endpoint in OpenAPI by leveraging FastAPI's docstrings and ensure authentication decorators guard sensitive routes.

## Replacing PostgreSQL

### SQLite (local dev)

1. Change `configs/collector.yaml` `database.url` to `sqlite:///./vigil.db`.
2. Update SQLAlchemy engine creation in `python/app/db/session.py` to handle SQLite-specific pragmas (thread safety, foreign key enforcement).
3. Disable migrations that require advanced PostgreSQL features (JSONB indexes). Replace with JSON columns + simple indexes.

### MySQL or Other RDBMS

1. Supply `mysql+pymysql://user:pass@host:port/db` as the URL.
2. Replace PostgreSQL-specific SQL (e.g., `gen_random_uuid()`) with portable alternatives.
3. Run the integration test suite to confirm transactional behavior and adjust Alembic migrations accordingly.

### External Observability Stores

- For time-series stores (Prometheus, Influx), add exporter jobs that subscribe to `/ingest` events via Redis and write to the store while maintaining the canonical state in PostgreSQL.

## Embedding Vigil Components

- **Collector:** Import FastAPI app (`from app.main import app`) into another ASGI server; mount under a path (`other_app.mount("/vigil", app)`). Provide dependency overrides for authentication or database sessions.
- **Agent:** Use `go/agent/pkg/metrics` as a library in another Go program; reuse `metrics.Client` to send data to an existing collector.
- **Remediator:** Wrap `go/remediator/pkg/actions` inside your orchestrator to reuse action registry logic while supplying your own transport (e.g., gRPC instead of HTTP).
- **GitOpsD:** Consume `go/gitopsd/pkg/manifest` to parse manifests in other GitOps engines or integrate drift detection inside broader automation.

## Security Considerations

- Never hardcode secrets in config files; rely on environment variables or secret managers.
- Enforce authentication on new endpoints; use FastAPI dependencies to verify API keys or JWTs.
- Validate all user-supplied config (manifest schema, remediation parameters) to avoid command injection.
- Apply least privilege to new action handlers: restrict system commands and prefer allowlists.
- When embedding or extending, ensure TLS/mTLS is consistently applied and tokens are rotated.

## Testing Extensions

- **Unit tests:** Place Go tests alongside code (`*_test.go`) and run `go test ./...`. For Python, add tests under `python/app/tests/` and run `pytest`.
- **Integration tests:** Use the provided `docker-compose.yml` to spin up Collector, Redis, Postgres, Remediator, and GitOpsD. Add new scenarios to `python/app/tests/integration/` that exercise the full ingest-evaluate-remediate flow.
- **Smoke tests:** Create a script under `simulate_failures.py` or new CLI commands to trigger metrics and verify remediation after your extension.
- **CI integration:** Update GitHub Actions or other CI workflows to include new test suites; ensure linting (`golangci-lint`, `black`, `ruff`, `mypy`) succeeds.

## Checklist When Contributing Extensions

- [ ] Update or add YAML samples in `configs/` if configuration changed.
- [ ] Document new endpoints or metrics in `README.md` or `docs/`.
- [ ] Provide migration steps if database schemas change.
- [ ] Add tracing/logging to preserve observability for new functionality.
- [ ] Ensure feature flags or configuration toggles guard experimental features.

Extending Vigil should keep the control loop simple, observable, and deterministic. Reach out via project issues or discussions when proposing larger changes so architecture principles remain aligned.
