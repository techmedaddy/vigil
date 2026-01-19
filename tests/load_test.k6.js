/**
 * K6 Load Testing Script for Vigil API
 * 
 * Usage:
 *   # Run steady load test
 *   k6 run tests/load_test.k6.js
 * 
 *   # Run with custom settings
 *   k6 run --vus 50 --duration 5m tests/load_test.k6.js
 * 
 *   # Run burst scenario
 *   k6 run --env SCENARIO=burst tests/load_test.k6.js
 * 
 *   # Run with failure injection
 *   k6 run --env SCENARIO=failure tests/load_test.k6.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Counter, Trend } from 'k6/metrics';

// Custom metrics
const ingestErrors = new Rate('ingest_errors');
const rateLimitHits = new Counter('rate_limit_hits');
const queueDepth = new Trend('queue_depth');
const workerThroughput = new Trend('worker_throughput');

// Configuration
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const SCENARIO = __ENV.SCENARIO || 'steady';

// Test scenarios
export const options = {
  scenarios: {
    steady: {
      executor: 'constant-vus',
      vus: 50,
      duration: '5m',
      tags: { scenario: 'steady' },
    },
    burst: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 100 },
        { duration: '1m', target: 100 },
        { duration: '30s', target: 0 },
        { duration: '30s', target: 200 },
        { duration: '1m', target: 200 },
        { duration: '30s', target: 0 },
      ],
      tags: { scenario: 'burst' },
    },
    ramp: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '2m', target: 50 },
        { duration: '3m', target: 100 },
        { duration: '2m', target: 150 },
        { duration: '1m', target: 0 },
      ],
      tags: { scenario: 'ramp' },
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    http_req_failed: ['rate<0.1'],
    ingest_errors: ['rate<0.05'],
  },
};

// Metric types
const METRIC_TYPES = [
  { name: 'cpu_usage', min: 0, max: 100 },
  { name: 'memory_usage', min: 0, max: 100 },
  { name: 'disk_usage', min: 0, max: 100 },
  { name: 'request_latency', min: 0, max: 5000 },
  { name: 'error_rate', min: 0, max: 100 },
];

const SERVICES = ['web', 'api', 'worker', 'db', 'cache'];

/**
 * Generate random metric payload
 */
function generateMetric(severity = 'normal') {
  const metricType = METRIC_TYPES[Math.floor(Math.random() * METRIC_TYPES.length)];
  const service = SERVICES[Math.floor(Math.random() * SERVICES.length)];
  
  let value;
  if (severity === 'critical') {
    value = metricType.min + (metricType.max - metricType.min) * (0.85 + Math.random() * 0.15);
  } else if (severity === 'warning') {
    value = metricType.min + (metricType.max - metricType.min) * (0.70 + Math.random() * 0.15);
  } else {
    value = metricType.min + (metricType.max - metricType.min) * Math.random() * 0.70;
  }
  
  return {
    name: metricType.name,
    value: Math.round(value * 100) / 100,
    timestamp: Date.now() / 1000,
    labels: {
      service: service,
      environment: 'k6_test',
    },
  };
}

/**
 * Main test function
 */
export default function () {
  // Determine severity distribution
  const rand = Math.random();
  let severity;
  if (rand < 0.70) {
    severity = 'normal';
  } else if (rand < 0.90) {
    severity = 'warning';
  } else {
    severity = 'critical';
  }
  
  // Ingest metric
  const ingestPayload = JSON.stringify(generateMetric(severity));
  const ingestRes = http.post(
    `${BASE_URL}/api/v1/ingest`,
    ingestPayload,
    {
      headers: { 'Content-Type': 'application/json' },
      tags: { name: 'ingest', severity: severity },
    }
  );
  
  // Check response
  const ingestOk = check(ingestRes, {
    'ingest status is 200': (r) => r.status === 200,
    'ingest has response body': (r) => r.body.length > 0,
  });
  
  if (!ingestOk) {
    ingestErrors.add(1);
    if (ingestRes.status === 429) {
      rateLimitHits.add(1);
    }
  }
  
  // Periodically check queue stats
  if (Math.random() < 0.1) {
    const queueRes = http.get(
      `${BASE_URL}/api/v1/ui/queue/stats`,
      { tags: { name: 'queue_stats' } }
    );
    
    if (queueRes.status === 200) {
      try {
        const stats = JSON.parse(queueRes.body);
        if (stats.queue && stats.queue.queue_length !== undefined) {
          queueDepth.add(stats.queue.queue_length);
        }
      } catch (e) {
        // Ignore parse errors
      }
    }
  }
  
  // Query actions periodically
  if (Math.random() < 0.2) {
    http.get(
      `${BASE_URL}/api/v1/actions?limit=10`,
      { tags: { name: 'actions' } }
    );
  }
  
  // Query policies periodically
  if (Math.random() < 0.15) {
    http.get(
      `${BASE_URL}/api/v1/policies`,
      { tags: { name: 'policies' } }
    );
  }
  
  // Small delay between iterations
  sleep(Math.random() * 0.5 + 0.1);
}

/**
 * Setup function - runs once before test
 */
export function setup() {
  console.log('Starting Vigil load test...');
  console.log(`Base URL: ${BASE_URL}`);
  console.log(`Scenario: ${SCENARIO}`);
  
  // Health check
  const healthRes = http.get(`${BASE_URL}/health`);
  if (healthRes.status !== 200) {
    console.warn('Warning: API health check failed');
  }
  
  return { startTime: Date.now() };
}

/**
 * Teardown function - runs once after test
 */
export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Test completed in ${duration.toFixed(2)} seconds`);
}
