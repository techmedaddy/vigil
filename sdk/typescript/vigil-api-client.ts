/**
 * Vigil API Client for Frontend
 * 
 * Auto-generated TypeScript client for Vigil Monitoring System API
 * Base URL: http://localhost:8000
 * 
 * Usage:
 *   import { VigilAPI } from './vigil-api-client';
 *   const api = new VigilAPI('http://localhost:8000');
 *   const health = await api.health.check();
 */

// ============================================
// TYPES
// ============================================

export interface HealthResponse {
  status: string;
  service: string;
}

export interface MetricRequest {
  name: string;
  value: number;
  tags?: Record<string, string>;
}

export interface MetricResponse {
  ok: boolean;
  metric_id: number;
  message: string;
}

export interface ActionRequest {
  target: string;
  action: string;
  status?: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  details?: string;
}

export interface ActionResponse {
  ok: boolean;
  action_id: number;
  message: string;
}

export interface ActionDetail {
  id: number;
  target: string;
  action: string;
  status: string;
  details: string | null;
  started_at: string;
}

export interface ActionListResponse {
  count: number;
  actions: ActionDetail[];
}

export interface PolicyCondition {
  type: 'metric_exceeds' | 'metric_below' | 'all' | 'any';
  metric?: string;
  threshold?: number;
  conditions?: PolicyCondition[];
}

export interface PolicyRequest {
  name: string;
  description: string;
  severity: 'info' | 'warning' | 'critical';
  target: string;
  enabled: boolean;
  auto_remediate: boolean;
  condition: PolicyCondition;
  action: 'scale-up' | 'restart' | 'drain-pod' | 'custom';
  params?: Record<string, any>;
}

export interface PolicyInfo {
  name: string;
  description: string;
  severity: string;
  target: string;
  enabled: boolean;
  auto_remediate: boolean;
  params: Record<string, any>;
}

export interface PolicyListResponse {
  ok: boolean;
  policies: Record<string, PolicyInfo>;
  total: number;
  enabled_count: number;
}

export interface PolicyUpdateRequest {
  description?: string;
  severity?: 'info' | 'warning' | 'critical';
  target?: string;
  enabled?: boolean;
  auto_remediate?: boolean;
  params?: Record<string, any>;
}

export interface EvaluateRequest {
  metrics: Record<string, number>;
  target?: string;
}

export interface PolicyViolation {
  policy_name: string;
  severity: string;
  target: string;
  action: string;
  triggered_at: string;
}

export interface ActionTriggered {
  action_id: number;
  policy_name: string;
  target: string;
  action: string;
  status: string;
}

export interface EvaluateResponse {
  ok: boolean;
  violations: PolicyViolation[];
  actions_triggered: ActionTriggered[];
  timestamp: string;
}

export interface MessageResponse {
  ok: boolean;
  message: string;
}

export interface RunnerStatus {
  enabled: boolean;
  running: boolean;
  interval_seconds?: number;
  batch_size?: number;
  message?: string;
}

export interface RunnerStatusResponse {
  ok: boolean;
  runner: RunnerStatus;
}

// ============================================
// API CLIENT
// ============================================

export class VigilAPI {
  private baseUrl: string;
  private headers: HeadersInit;

  constructor(baseUrl: string = 'http://localhost:8000') {
    this.baseUrl = baseUrl.replace(/\/$/, ''); // Remove trailing slash
    this.headers = {
      'Content-Type': 'application/json',
    };
  }

  private async request<T>(
    method: string,
    path: string,
    body?: any
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    
    const options: RequestInit = {
      method,
      headers: this.headers,
    };

    if (body) {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
  }

  // ============================================
  // HEALTH & SYSTEM
  // ============================================

  health = {
    /**
     * Check if Vigil API is healthy
     * GET /health
     */
    check: (): Promise<HealthResponse> => 
      this.request('GET', '/health'),

    /**
     * Get Prometheus metrics (returns text)
     * GET /metrics
     */
    metrics: async (): Promise<string> => {
      const response = await fetch(`${this.baseUrl}/metrics`);
      return response.text();
    },
  };

  // ============================================
  // METRICS INGESTION
  // ============================================

  ingest = {
    /**
     * Ingest a metric
     * POST /api/v1/ingest
     */
    metric: (data: MetricRequest): Promise<MetricResponse> =>
      this.request('POST', '/api/v1/ingest', data),

    /**
     * Ingest metric from agent
     * POST /api/v1/ingest/agent/metrics
     */
    agentMetric: (data: MetricRequest): Promise<MetricResponse> =>
      this.request('POST', '/api/v1/ingest/agent/metrics', data),

    /**
     * Check ingest service health
     * GET /api/v1/ingest/health
     */
    health: (): Promise<HealthResponse> =>
      this.request('GET', '/api/v1/ingest/health'),
  };

  // ============================================
  // ACTIONS MANAGEMENT
  // ============================================

  actions = {
    /**
     * Create a new action
     * POST /api/v1/actions
     */
    create: (data: ActionRequest): Promise<ActionResponse> =>
      this.request('POST', '/api/v1/actions', data),

    /**
     * List actions with optional filters
     * GET /api/v1/actions
     */
    list: (params?: { 
      limit?: number; 
      status?: string; 
      target?: string;
    }): Promise<ActionListResponse> => {
      const query = new URLSearchParams();
      if (params?.limit) query.set('limit', params.limit.toString());
      if (params?.status) query.set('status', params.status);
      if (params?.target) query.set('target', params.target);
      const queryStr = query.toString();
      return this.request('GET', `/api/v1/actions${queryStr ? '?' + queryStr : ''}`);
    },

    /**
     * Get action by ID
     * GET /api/v1/actions/{id}
     */
    get: (id: number): Promise<ActionDetail> =>
      this.request('GET', `/api/v1/actions/${id}`),

    /**
     * Get actions by status
     * GET /api/v1/actions/status/{status}
     */
    byStatus: (
      status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled',
      limit?: number
    ): Promise<ActionListResponse> => {
      const query = limit ? `?limit=${limit}` : '';
      return this.request('GET', `/api/v1/actions/status/${status}${query}`);
    },

    /**
     * Check actions service health
     * GET /api/v1/actions/health
     */
    health: (): Promise<HealthResponse> =>
      this.request('GET', '/api/v1/actions/health'),
  };

  // ============================================
  // POLICIES MANAGEMENT
  // ============================================

  policies = {
    /**
     * Create a new policy
     * POST /api/v1/policies
     */
    create: (data: PolicyRequest): Promise<PolicyInfo> =>
      this.request('POST', '/api/v1/policies', data),

    /**
     * List all policies
     * GET /api/v1/policies
     */
    list: (): Promise<PolicyListResponse> =>
      this.request('GET', '/api/v1/policies'),

    /**
     * Get policy by name
     * GET /api/v1/policies/{name}
     */
    get: (name: string): Promise<PolicyInfo> =>
      this.request('GET', `/api/v1/policies/${encodeURIComponent(name)}`),

    /**
     * Update a policy
     * PUT /api/v1/policies/{name}
     */
    update: (name: string, data: PolicyUpdateRequest): Promise<PolicyInfo> =>
      this.request('PUT', `/api/v1/policies/${encodeURIComponent(name)}`, data),

    /**
     * Delete a policy
     * DELETE /api/v1/policies/{name}
     */
    delete: (name: string): Promise<MessageResponse> =>
      this.request('DELETE', `/api/v1/policies/${encodeURIComponent(name)}`),

    /**
     * Evaluate policies against metrics
     * POST /api/v1/policies/evaluate
     */
    evaluate: (data: EvaluateRequest): Promise<EvaluateResponse> =>
      this.request('POST', '/api/v1/policies/evaluate', data),

    /**
     * Enable a policy
     * PUT /api/v1/policies/{name}/enable
     */
    enable: (name: string): Promise<MessageResponse> =>
      this.request('PUT', `/api/v1/policies/${encodeURIComponent(name)}/enable`),

    /**
     * Disable a policy
     * PUT /api/v1/policies/{name}/disable
     */
    disable: (name: string): Promise<MessageResponse> =>
      this.request('PUT', `/api/v1/policies/${encodeURIComponent(name)}/disable`),

    /**
     * Reload policies from config files
     * POST /api/v1/policies/reload
     */
    reload: (): Promise<MessageResponse> =>
      this.request('POST', '/api/v1/policies/reload'),

    /**
     * Get policies by severity
     * GET /api/v1/policies/severity/{severity}
     */
    bySeverity: (
      severity: 'info' | 'warning' | 'critical'
    ): Promise<PolicyListResponse> =>
      this.request('GET', `/api/v1/policies/severity/${severity}`),

    /**
     * Get policy runner status
     * GET /api/v1/policies/runner/status
     */
    runnerStatus: (): Promise<RunnerStatusResponse> =>
      this.request('GET', '/api/v1/policies/runner/status'),
  };
}

// ============================================
// CONVENIENCE EXPORTS
// ============================================

// Default instance
export const vigilApi = new VigilAPI();

// Usage examples:
/*
import { VigilAPI, vigilApi } from './vigil-api-client';

// Using default instance
const health = await vigilApi.health.check();

// Using custom instance
const api = new VigilAPI('http://api.example.com:8000');

// Health check
const healthStatus = await api.health.check();
console.log(healthStatus.status); // "healthy"

// Ingest metric
const result = await api.ingest.metric({
  name: 'cpu_usage',
  value: 85.5,
  tags: { host: 'web-01' }
});
console.log(result.metric_id);

// List actions
const actions = await api.actions.list({ limit: 10, status: 'pending' });
console.log(actions.count);

// Create policy
const policy = await api.policies.create({
  name: 'high-cpu',
  description: 'Alert on high CPU',
  severity: 'warning',
  target: 'web-*',
  enabled: true,
  auto_remediate: true,
  condition: { type: 'metric_exceeds', metric: 'cpu_percent', threshold: 90 },
  action: 'scale-up',
  params: { replicas: 2 }
});

// Evaluate policies
const evaluation = await api.policies.evaluate({
  metrics: { cpu_percent: 95, memory_percent: 80 },
  target: 'web-server-01'
});
console.log(evaluation.violations);

// Enable/disable policy
await api.policies.disable('high-cpu');
await api.policies.enable('high-cpu');

// Get policies by severity
const criticalPolicies = await api.policies.bySeverity('critical');
*/
