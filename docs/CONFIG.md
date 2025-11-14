# Vigil Configuration Guide

This document provides comprehensive configuration guidance for all Vigil components. Vigil uses YAML configuration files located in the `configs/` directory, with support for environment variable overrides and deployment-specific customization.

## Configuration File Locations

All configuration files are located in the `configs/` directory:

```
configs/
├── agent.yaml        # Agent configuration
├── collector.yaml    # Collector API configuration  
├── gitopsd.yaml      # GitOps daemon configuration
└── remediator.yaml   # Remediator configuration
```

Each service reads its respective configuration file on startup. Configuration files are optional - services will use sensible defaults when config files are missing or incomplete.

## Collector Configuration (`configs/collector.yaml`)

The Collector API configuration controls ingestion, storage, evaluation, and integration settings.

### Schema and Examples

```yaml
# Collector API configuration
server:
  host: "127.0.0.1"
  port: 8000
  workers: 4
  log_level: "INFO"
  
database:
  url: "postgresql://vigil:password@localhost:5432/vigil"
  pool_size: 10
  max_overflow: 20
  pool_timeout: 30
  
redis:
  url: "redis://localhost:6379/0"
  password: ""
  pool_size: 10
  socket_timeout: 5
  
evaluation:
  enabled: true
  interval: 30  # seconds
  batch_size: 100
  workers: 2
  
policies:
  # CPU usage threshold policy
  - name: "high_cpu_usage"
    condition: "cpu_usage > 0.8"
    duration: "5m"
    severity: "warning"
    action: "restart_service"
    cooldown: "10m"
    
  # Memory leak detection
  - name: "memory_leak_detection"
    condition: "memory_usage_trend > 0.1 for 30m"
    severity: "critical"
    action: "restart_service"
    cooldown: "15m"
    
  # Service health check failure
  - name: "health_check_failure"
    condition: "health_check_status != 'healthy' for 3 attempts"
    severity: "critical"
    action: "restart_service"
    cooldown: "5m"

remediation:
  enabled: true
  remediator_url: "http://127.0.0.1:8081"
  timeout: 30  # seconds
  retry_attempts: 3
  retry_delay: 5  # seconds

security:
  api_key_header: "X-API-Key"
  require_auth: false
  allowed_origins:
    - "http://localhost:3000"
    - "https://dashboard.example.com"
    
logging:
  level: "INFO"
  format: "json"
  file: "/var/log/vigil/collector.log"
  max_size: "100MB"
  max_files: 5
```

### Environment Variable Overrides

| Variable | Default | Description |
|----------|---------|-------------|
| `VIGIL_COLLECTOR_HOST` | 127.0.0.1 | Server bind address |
| `VIGIL_COLLECTOR_PORT` | 8000 | Server port |
| `VIGIL_DATABASE_URL` | - | PostgreSQL connection string |
| `VIGIL_REDIS_URL` | redis://localhost:6379/0 | Redis connection string |
| `VIGIL_LOG_LEVEL` | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `VIGIL_API_KEY` | - | API key for authentication |
| `VIGIL_REMEDIATOR_URL` | http://127.0.0.1:8081 | Remediator service URL |

## Agent Configuration (`configs/agent.yaml`)

Agent configuration controls metric collection, reporting intervals, and collector connectivity.

### Schema and Examples

```yaml
# Agent configuration
collector:
  url: "http://127.0.0.1:8000/ingest"
  timeout: 10  # seconds
  retry_attempts: 3
  retry_delay: 5   # seconds
  batch_size: 50
  
agent:
  id: "agent-001"  # Unique agent identifier
  hostname: ""     # Auto-detected if empty
  interval: 10     # Collection interval in seconds
  tags:
    environment: "production"
    datacenter: "us-west-1"
    team: "platform"

metrics:
  # System metrics collection
  system:
    enabled: true
    cpu:
      enabled: true
      interval: 10
    memory:
      enabled: true  
      interval: 10
    disk:
      enabled: true
      interval: 30
      paths:
        - "/"
        - "/var"
    network:
      enabled: true
      interval: 10
      interfaces:
        - "eth0"
        - "wlan0"
        
  # Custom application metrics
  custom:
    # Web service health check
    - name: "web_service_health"
      type: "http_check"
      interval: 30
      config:
        url: "http://localhost:8080/health"
        expected_status: 200
        timeout: 5
        
    # Database connection check  
    - name: "db_connection_health"
      type: "tcp_check"
      interval: 60
      config:
        host: "localhost"
        port: 5432
        timeout: 3
        
    # Custom script execution
    - name: "custom_business_metric"
      type: "script"
      interval: 300  # 5 minutes
      config:
        command: "/opt/scripts/business_metric.sh"
        timeout: 30

security:
  api_key: ""  # API key for collector authentication
  tls:
    enabled: false
    cert_file: ""
    key_file: ""
    ca_file: ""
    
logging:
  level: "INFO"
  format: "text"
  file: "/var/log/vigil/agent.log"
```

### Environment Variable Overrides

| Variable | Default | Description |
|----------|---------|-------------|
| `VIGIL_COLLECTOR_URL` | http://127.0.0.1:8000/ingest | Collector ingestion endpoint |
| `VIGIL_AGENT_ID` | auto-generated | Unique agent identifier |
| `VIGIL_AGENT_INTERVAL` | 10 | Metric collection interval (seconds) |
| `VIGIL_API_KEY` | - | API key for collector authentication |
| `VIGIL_LOG_LEVEL` | INFO | Logging level |

## GitOpsD Configuration (`configs/gitopsd.yaml`)

GitOpsD configuration controls manifest synchronization, Git integration, and desired state management.

### Schema and Examples

```yaml
# GitOps daemon configuration
git:
  repository_url: "https://github.com/your-org/vigil-manifests.git"
  branch: "main"
  auth:
    type: "token"  # token, ssh_key, or none
    token: ""      # GitHub token or password
    ssh_key_path: "/home/vigil/.ssh/id_rsa"
    username: ""
    
sync:
  interval: 60        # seconds - how often to check for changes
  timeout: 30         # seconds - git operation timeout
  local_path: "/tmp/vigil-manifests"
  
manifests:
  # Local manifest directory (alternative to Git)
  local_path: "./manifests"
  
  # Manifest file patterns
  patterns:
    - "**/*.yaml"
    - "**/*.yml"
    - "**/*.json"
    
  # Directories to exclude
  exclude_patterns:
    - ".git/**"
    - "*.tmp"
    - "draft/**"
    
validation:
  enabled: true
  strict_mode: false  # Fail on unknown fields
  schema_validation: true
  
collector:
  url: "http://127.0.0.1:8000"
  timeout: 10
  api_key: ""
  
redis:
  url: "redis://localhost:6379/0"
  password: ""
  
drift_detection:
  enabled: true
  interval: 120  # seconds - how often to run drift analysis
  threshold: 0.1 # Drift significance threshold (0.0-1.0)
  
server:
  host: "127.0.0.1"
  port: 8082
  
logging:
  level: "INFO"
  format: "json"
  file: "/var/log/vigil/gitopsd.log"
```

### Environment Variable Overrides

| Variable | Default | Description |
|----------|---------|-------------|
| `VIGIL_GIT_REPOSITORY_URL` | - | Git repository URL for manifests |
| `VIGIL_GIT_BRANCH` | main | Git branch to track |
| `VIGIL_GIT_TOKEN` | - | Git authentication token |
| `VIGIL_SYNC_INTERVAL` | 60 | Git sync interval (seconds) |
| `VIGIL_MANIFESTS_PATH` | ./manifests | Local manifests directory |
| `VIGIL_COLLECTOR_URL` | http://127.0.0.1:8000 | Collector API URL |
| `VIGIL_REDIS_URL` | redis://localhost:6379/0 | Redis connection string |

## Remediator Configuration (`configs/remediator.yaml`)

Remediator configuration controls action execution, safety mechanisms, and external integrations.

### Schema and Examples

```yaml
# Remediator configuration
server:
  host: "127.0.0.1"
  port: 8081
  
collector:
  url: "http://127.0.0.1:8000"
  timeout: 30
  api_key: ""
  
redis:
  url: "redis://localhost:6379/0"
  password: ""
  
safety:
  dry_run: false
  require_approval: false
  max_concurrent_actions: 5
  action_timeout: 300  # seconds
  cooldown_period: 600 # seconds between actions on same target
  
circuit_breaker:
  enabled: true
  failure_threshold: 5
  success_threshold: 3
  timeout: 60  # seconds
  
actions:
  # Docker container restart
  - name: "restart_service"
    type: "docker"
    config:
      command: "docker restart {target}"
      timeout: 60
      requires_sudo: false
      
  # Systemd service restart  
  - name: "restart_systemd_service"
    type: "systemd"
    config:
      command: "systemctl restart {target}"
      timeout: 30
      requires_sudo: true
      
  # Kubernetes pod restart
  - name: "restart_k8s_pod"
    type: "kubernetes"
    config:
      command: "kubectl delete pod {target} -n {namespace}"
      timeout: 120
      requires_auth: true
      
  # Custom script execution
  - name: "custom_remediation"
    type: "script"
    config:
      command: "/opt/scripts/remediate.sh {target} {action}"
      timeout: 180
      working_directory: "/opt/scripts"
      environment:
        PATH: "/usr/local/bin:/usr/bin:/bin"
        
  # HTTP webhook call
  - name: "webhook_notification"
    type: "webhook"
    config:
      url: "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK"
      method: "POST"
      timeout: 10
      headers:
        Content-Type: "application/json"
      body_template: |
        {
          "text": "Vigil performed remediation action: {action} on {target}",
          "channel": "#alerts"
        }

integrations:
  # AWS integration for cloud resource management
  aws:
    enabled: false
    region: "us-west-2"
    access_key_id: ""
    secret_access_key: ""
    
  # Docker integration
  docker:
    enabled: true
    socket_path: "/var/run/docker.sock"
    
  # Kubernetes integration
  kubernetes:
    enabled: false
    config_path: "/home/vigil/.kube/config"
    namespace: "default"
    
logging:
  level: "INFO"
  format: "json"
  file: "/var/log/vigil/remediator.log"
  audit_file: "/var/log/vigil/audit.log"
```

### Environment Variable Overrides

| Variable | Default | Description |
|----------|---------|-------------|
| `VIGIL_REMEDIATOR_HOST` | 127.0.0.1 | Server bind address |
| `VIGIL_REMEDIATOR_PORT` | 8081 | Server port |
| `VIGIL_COLLECTOR_URL` | http://127.0.0.1:8000 | Collector API URL |
| `VIGIL_DRY_RUN` | false | Enable dry-run mode |
| `VIGIL_MAX_CONCURRENT_ACTIONS` | 5 | Maximum concurrent remediation actions |
| `VIGIL_REDIS_URL` | redis://localhost:6379/0 | Redis connection string |

## Docker Compose Environment Override Examples

### Development Configuration

```yaml
version: '3.8'

services:
  collector:
    environment:
      VIGIL_LOG_LEVEL: DEBUG
      VIGIL_DATABASE_URL: postgresql://vigil:dev_password@postgres:5432/vigil_dev
      VIGIL_REDIS_URL: redis://redis:6379/0
      
  agent:
    environment:
      VIGIL_COLLECTOR_URL: http://collector:8000/ingest
      VIGIL_AGENT_INTERVAL: 5  # More frequent collection for development
      VIGIL_LOG_LEVEL: DEBUG
      
  gitopsd:
    environment:
      VIGIL_SYNC_INTERVAL: 30  # More frequent sync for development
      VIGIL_MANIFESTS_PATH: /manifests
      VIGIL_LOG_LEVEL: DEBUG
      
  remediator:
    environment:
      VIGIL_DRY_RUN: true  # Safe mode for development
      VIGIL_LOG_LEVEL: DEBUG
```

### Production Configuration

```yaml
version: '3.8'

services:
  collector:
    environment:
      VIGIL_LOG_LEVEL: INFO
      VIGIL_DATABASE_URL: postgresql://vigil:${POSTGRES_PASSWORD}@postgres:5432/vigil
      VIGIL_REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      VIGIL_API_KEY: ${COLLECTOR_API_KEY}
      
  agent:
    environment:
      VIGIL_COLLECTOR_URL: https://collector.internal.example.com/ingest
      VIGIL_API_KEY: ${AGENT_API_KEY}
      VIGIL_AGENT_INTERVAL: 30
      
  gitopsd:
    environment:
      VIGIL_GIT_REPOSITORY_URL: https://github.com/your-org/prod-manifests.git
      VIGIL_GIT_TOKEN: ${GITHUB_TOKEN}
      VIGIL_SYNC_INTERVAL: 300
      
  remediator:
    environment:
      VIGIL_DRY_RUN: false
      VIGIL_MAX_CONCURRENT_ACTIONS: 10
      VIGIL_API_KEY: ${REMEDIATOR_API_KEY}
```

## Configuration Recommendations

### Development vs Production Settings

| Component | Development | Production |
|-----------|-------------|------------|
| **Log Level** | DEBUG | INFO/WARNING |
| **Collection Interval** | 5-10s | 30-60s |
| **Git Sync Interval** | 30s | 300s |
| **Dry Run Mode** | true | false |
| **Authentication** | disabled | enabled |
| **TLS/HTTPS** | optional | required |
| **Database** | SQLite/small PostgreSQL | PostgreSQL with replicas |
| **Redis** | single instance | Redis Sentinel/Cluster |

### Performance Tuning

**High-Throughput Environments:**
```yaml
# Collector configuration for high throughput
server:
  workers: 8
  
database:
  pool_size: 20
  max_overflow: 40
  
evaluation:
  batch_size: 500
  workers: 4
  
redis:
  pool_size: 20
```

**Resource-Constrained Environments:**
```yaml
# Collector configuration for limited resources
server:
  workers: 2
  
database:
  pool_size: 5
  max_overflow: 10
  
evaluation:
  batch_size: 50
  workers: 1
```

## Adding New Metrics

### 1. Agent-Side Custom Metrics

Add new metrics to `agent.yaml`:

```yaml
metrics:
  custom:
    # Database query performance
    - name: "db_query_time"
      type: "sql_query"
      interval: 60
      config:
        connection_string: "postgresql://user:pass@localhost:5432/app"
        query: "SELECT AVG(duration) FROM query_logs WHERE created_at > NOW() - INTERVAL '1 minute'"
        
    # File system usage
    - name: "log_file_size"
      type: "file_stat"
      interval: 300
      config:
        path: "/var/log/application.log"
        stat: "size"
```

### 2. Custom Metric Collectors

Create custom metric collector plugins:

```go
// Custom metric collector interface
type MetricCollector interface {
    Name() string
    Collect() ([]Metric, error)
    Configure(config map[string]interface{}) error
}

// Example: Business logic metric
type BusinessMetricCollector struct {
    apiEndpoint string
    apiKey      string
}

func (c *BusinessMetricCollector) Collect() ([]Metric, error) {
    // Implementation for collecting business metrics
    // Return metrics in standard format
}
```

## Adding New Policies

### 1. Threshold-Based Policies

Add to `collector.yaml`:

```yaml
policies:
  # Disk usage alert
  - name: "high_disk_usage"
    condition: "disk_usage_percent > 85"
    duration: "10m"
    severity: "warning"
    action: "cleanup_logs"
    
  # Network latency detection  
  - name: "high_network_latency"
    condition: "network_latency_ms > 500 for 5m"
    severity: "critical"
    action: "restart_network_service"
```

### 2. Complex Policy Rules

```yaml
policies:
  # Multi-condition policy
  - name: "application_degradation"
    condition: |
      (cpu_usage > 0.8 AND memory_usage > 0.9) OR
      (error_rate > 0.05 AND response_time > 1000)
    duration: "3m"
    severity: "critical"
    action: "scale_up_service"
    
  # Time-based policy
  - name: "business_hours_monitoring"
    condition: "response_time > 200"
    schedule: "Mon-Fri 09:00-17:00"
    timezone: "America/New_York"
    action: "alert_team"
```

## Adding New Manifest Paths

### 1. GitOpsD Configuration

Update `gitopsd.yaml` to include additional manifest sources:

```yaml
manifests:
  sources:
    # Primary manifest repository
    - type: "git"
      url: "https://github.com/your-org/prod-manifests.git"
      branch: "main"
      path: "services/"
      
    # Secondary manifest repository  
    - type: "git"
      url: "https://github.com/your-org/infrastructure-manifests.git"
      branch: "main"
      path: "/"
      
    # Local manifest directory
    - type: "local"
      path: "/etc/vigil/manifests"
      
  patterns:
    - "**/*.yaml"
    - "**/*.yml"
    - "**/manifest.json"
```

### 2. Manifest Directory Structure

```
manifests/
├── services/
│   ├── web/
│   │   ├── production.yaml
│   │   └── staging.yaml
│   └── api/
│       ├── production.yaml
│       └── staging.yaml
├── infrastructure/
│   ├── databases/
│   │   └── postgres.yaml
│   └── caches/
│       └── redis.yaml
└── policies/
    ├── scaling.yaml
    └── alerting.yaml
```

## GitOpsD Polling Interval Configuration

### Basic Interval Settings

```yaml
# gitopsd.yaml
sync:
  interval: 300  # Check Git repository every 5 minutes
  
drift_detection:
  interval: 120  # Run drift analysis every 2 minutes
```

### Advanced Polling Configuration

```yaml
sync:
  # Adaptive polling based on activity
  interval: 300
  adaptive_polling:
    enabled: true
    min_interval: 60    # Minimum 1 minute
    max_interval: 1800  # Maximum 30 minutes
    activity_threshold: 5  # Scale up polling if >5 changes/hour
    
  # Webhook-triggered sync
  webhooks:
    enabled: true
    secret: "webhook_secret_key"
    endpoints:
      - "/webhook/github"
      - "/webhook/gitlab"
```

### Environment-Specific Intervals

```yaml
# Development
sync:
  interval: 30  # Fast iteration

# Staging  
sync:
  interval: 120  # Moderate testing

# Production
sync:
  interval: 600  # Conservative, stable
```

## Remediator Action Handler Selection

### Action Selection Logic

The Remediator selects action handlers using a priority-based matching system:

```yaml
# remediator.yaml
actions:
  # Exact action name match (highest priority)
  - name: "restart_web_service"
    type: "docker"
    priority: 100
    conditions:
      target: "web-*"
    config:
      command: "docker restart {target}"
      
  # Pattern-based matching
  - name: "restart_service"
    type: "systemd"  
    priority: 50
    conditions:
      action: "restart_*"
      target_type: "service"
    config:
      command: "systemctl restart {target}"
      
  # Fallback handler (lowest priority)
  - name: "default_action"
    type: "script"
    priority: 1
    config:
      command: "/opt/scripts/generic_handler.sh {action} {target}"
```

### Conditional Action Handlers

```yaml
actions:
  # Kubernetes environment
  - name: "restart_service"
    type: "kubernetes"
    conditions:
      environment: "kubernetes"
      namespace: "production"
    config:
      command: "kubectl rollout restart deployment/{target} -n {namespace}"
      
  # Docker Swarm environment
  - name: "restart_service" 
    type: "docker_swarm"
    conditions:
      environment: "swarm"
    config:
      command: "docker service update --force {target}"
      
  # Traditional VM environment
  - name: "restart_service"
    type: "systemd"
    conditions:
      environment: "vm"
    config:
      command: "systemctl restart {target}"
```

### Dynamic Action Parameters

```yaml
actions:
  - name: "scale_service"
    type: "script"
    config:
      command: "/opt/scripts/scale.sh"
      parameters:
        # Static parameters
        max_replicas: 10
        min_replicas: 2
        
        # Dynamic parameters from request
        target: "{target}"
        desired_replicas: "{metadata.replicas}"
        reason: "{reason}"
        
        # Environment-based parameters
        namespace: "{env.NAMESPACE|default:production}"
```

## Configuration Validation

### Schema Validation

Vigil validates configuration files on startup:

```bash
# Validate all configuration files
vigil-config validate --config-dir ./configs/

# Validate specific config file
vigil-config validate --file ./configs/collector.yaml

# Validate with custom schema
vigil-config validate --schema ./schemas/collector.json --file ./configs/collector.yaml
```

### Configuration Testing

```bash
# Test collector configuration
vigil-collector --config ./configs/collector.yaml --dry-run

# Test agent configuration with mock collector
vigil-agent --config ./configs/agent.yaml --mock-collector

# Test GitOpsD manifest parsing
vigil-gitopsd --config ./configs/gitopsd.yaml --validate-manifests
```

## Troubleshooting Configuration Issues

### Common Configuration Problems

1. **Database Connection Issues**
   ```yaml
   # Check database URL format
   database:
     url: "postgresql://user:password@host:port/database"
     # Not: "postgres://..." (old format)
   ```

2. **Redis Connection Problems**
   ```yaml
   # Include password in URL or separate field
   redis:
     url: "redis://:password@host:port/db"
     # Or:
     # url: "redis://host:port/db"
     # password: "your_password"
   ```

3. **File Path Issues**
   ```yaml
   # Use absolute paths in production
   manifests:
     local_path: "/opt/vigil/manifests"  # Good
     # local_path: "./manifests"        # Problematic in containers
   ```

### Configuration Debugging

Enable debug logging to troubleshoot configuration issues:

```yaml
logging:
  level: "DEBUG"
  
# Or via environment variable
VIGIL_LOG_LEVEL=DEBUG
```

Use configuration validation tools:

```bash
# Check YAML syntax
yamllint configs/

# Validate against schema
vigil-config validate --all

# Test connectivity
vigil-config test-connections --config-dir configs/
```

This configuration guide provides comprehensive coverage of all Vigil components and their configuration options. Use it as a reference for deploying and customizing Vigil in different environments.
