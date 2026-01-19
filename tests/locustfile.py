"""
Locust load testing script for Vigil API.

Usage:
    # Run with web UI
    locust -f tests/locustfile.py --host=http://localhost:8000
    
    # Headless mode
    locust -f tests/locustfile.py --host=http://localhost:8000 --users 100 --spawn-rate 10 --run-time 5m --headless
    
    # Specific scenario
    locust -f tests/locustfile.py --host=http://localhost:8000 --tags steady
"""

import random
import time
from locust import HttpUser, task, between, tag, events


class VigilUser(HttpUser):
    """
    Simulated user for Vigil API load testing.
    
    Simulates realistic usage patterns including:
    - Metric ingestion
    - Policy queries
    - Action triggering
    - Queue monitoring
    """
    
    wait_time = between(0.1, 2.0)  # Wait 0.1-2 seconds between tasks
    
    def on_start(self):
        """Initialize user session"""
        self.service_names = ["web", "api", "worker", "db", "cache"]
        self.metric_types = [
            ("cpu_usage", 0, 100),
            ("memory_usage", 0, 100),
            ("disk_usage", 0, 100),
            ("request_latency", 0, 5000),
            ("error_rate", 0, 100),
        ]
    
    @task(10)
    @tag("steady", "ingest")
    def ingest_normal_metric(self):
        """Ingest a normal metric (70% value range)"""
        metric_name, min_val, max_val = random.choice(self.metric_types)
        value = random.uniform(min_val, max_val * 0.70)
        
        payload = {
            "name": metric_name,
            "value": round(value, 2),
            "timestamp": time.time(),
            "labels": {
                "service": random.choice(self.service_names),
                "environment": "load_test",
            }
        }
        
        with self.client.post(
            "/api/v1/ingest",
            json=payload,
            catch_response=True,
            name="/api/v1/ingest [normal]"
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 429:
                response.failure("Rate limited")
            else:
                response.failure(f"Status {response.status_code}")
    
    @task(3)
    @tag("steady", "ingest", "warning")
    def ingest_warning_metric(self):
        """Ingest a warning-level metric (70-85% value range)"""
        metric_name, min_val, max_val = random.choice(self.metric_types)
        value = random.uniform(max_val * 0.70, max_val * 0.85)
        
        payload = {
            "name": metric_name,
            "value": round(value, 2),
            "timestamp": time.time(),
            "labels": {
                "service": random.choice(self.service_names),
                "environment": "load_test",
            }
        }
        
        self.client.post(
            "/api/v1/ingest",
            json=payload,
            name="/api/v1/ingest [warning]"
        )
    
    @task(1)
    @tag("steady", "ingest", "critical")
    def ingest_critical_metric(self):
        """Ingest a critical metric (85-100% value range)"""
        metric_name, min_val, max_val = random.choice(self.metric_types)
        value = random.uniform(max_val * 0.85, max_val)
        
        payload = {
            "name": metric_name,
            "value": round(value, 2),
            "timestamp": time.time(),
            "labels": {
                "service": random.choice(self.service_names),
                "environment": "load_test",
            }
        }
        
        self.client.post(
            "/api/v1/ingest",
            json=payload,
            name="/api/v1/ingest [critical]"
        )
    
    @task(2)
    @tag("steady", "query")
    def get_policies(self):
        """Query policies"""
        self.client.get(
            "/api/v1/policies",
            name="/api/v1/policies"
        )
    
    @task(2)
    @tag("steady", "query")
    def get_actions(self):
        """Query recent actions"""
        self.client.get(
            "/api/v1/actions?limit=20",
            name="/api/v1/actions"
        )
    
    @task(1)
    @tag("steady", "monitoring")
    def get_queue_stats(self):
        """Monitor queue statistics"""
        self.client.get(
            "/api/v1/ui/queue/stats",
            name="/api/v1/ui/queue/stats"
        )
    
    @task(1)
    @tag("steady", "monitoring")
    def get_metrics(self):
        """Get Prometheus metrics"""
        self.client.get(
            "/metrics",
            name="/metrics"
        )


class BurstUser(HttpUser):
    """
    User generating burst traffic patterns.
    
    Sends rapid bursts of requests followed by idle periods.
    """
    
    wait_time = between(5, 15)  # Long wait between bursts
    
    def on_start(self):
        """Initialize user session"""
        self.metric_types = [
            ("cpu_usage", 0, 100),
            ("memory_usage", 0, 100),
        ]
    
    @task
    @tag("burst")
    def burst_ingest(self):
        """Send a burst of ingest requests"""
        burst_size = random.randint(10, 50)
        
        for _ in range(burst_size):
            metric_name, min_val, max_val = random.choice(self.metric_types)
            value = random.uniform(max_val * 0.80, max_val)
            
            payload = {
                "name": metric_name,
                "value": round(value, 2),
                "timestamp": time.time(),
                "labels": {
                    "service": "burst_test",
                    "environment": "load_test",
                }
            }
            
            self.client.post(
                "/api/v1/ingest",
                json=payload,
                name="/api/v1/ingest [burst]"
            )
            
            # Small delay between burst requests
            time.sleep(0.01)


class FailureInjector(HttpUser):
    """
    User that intentionally sends malformed requests.
    
    Tests error handling and resilience.
    """
    
    wait_time = between(2, 5)
    
    @task(5)
    @tag("failure")
    def send_malformed_payload(self):
        """Send malformed payloads"""
        malformed = random.choice([
            {},
            {"name": "test"},
            {"value": 123},
            {"name": "", "value": "invalid"},
            {"name": "test", "value": None},
        ])
        
        self.client.post(
            "/api/v1/ingest",
            json=malformed,
            name="/api/v1/ingest [malformed]"
        )
    
    @task(1)
    @tag("failure")
    def send_invalid_action(self):
        """Send invalid action request"""
        self.client.post(
            "/api/v1/actions",
            json={"invalid": "data"},
            name="/api/v1/actions [invalid]"
        )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Log when test starts"""
    print("=" * 60)
    print("Vigil Load Test Started")
    print(f"Host: {environment.host}")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Log when test stops"""
    print("=" * 60)
    print("Vigil Load Test Completed")
    print("=" * 60)
