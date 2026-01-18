#!/usr/bin/env python3
"""
Simulate failures to test retry logic and rate limiting.

This script:
1. Sends requests that trigger retries
2. Tests rate limiting by exceeding limits
3. Simulates database connection failures
4. Monitors retry attempts and backoff behavior
"""

import asyncio
import aiohttp
import time
from datetime import datetime
from typing import List, Dict
import sys


class FailureSimulator:
    """Simulates various failure scenarios for testing retry and rate limiting."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results = []
    
    async def test_rate_limiting(self, endpoint: str, num_requests: int = 150):
        """
        Test rate limiting by sending many requests quickly.
        
        Args:
            endpoint: API endpoint to test
            num_requests: Number of requests to send
        """
        print(f"\n=== Testing Rate Limiting on {endpoint} ===")
        print(f"Sending {num_requests} requests rapidly...")
        
        success_count = 0
        rate_limited_count = 0
        error_count = 0
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            start_time = time.time()
            
            for i in range(num_requests):
                tasks.append(self._send_request(session, endpoint, i))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            elapsed = time.time() - start_time
            
            for result in results:
                if isinstance(result, Exception):
                    error_count += 1
                elif result.get("status") == 200:
                    success_count += 1
                elif result.get("status") == 429:
                    rate_limited_count += 1
                else:
                    error_count += 1
            
            print(f"\nResults ({elapsed:.2f}s):")
            print(f"  ✓ Successful: {success_count}")
            print(f"  ⚠ Rate limited (429): {rate_limited_count}")
            print(f"  ✗ Errors: {error_count}")
            print(f"  Rate: {num_requests/elapsed:.1f} req/s")
            
            if rate_limited_count > 0:
                print(f"\n✓ Rate limiting is working! {rate_limited_count} requests blocked.")
            else:
                print(f"\n⚠ Warning: No requests were rate limited. Check configuration.")
    
    async def _send_request(self, session: aiohttp.ClientSession, endpoint: str, req_num: int) -> Dict:
        """Send a single request and return result."""
        url = f"{self.base_url}{endpoint}"
        
        payload = {
            "name": f"test_metric_{req_num}",
            "value": 75.5,
            "tags": {"test": "rate_limit", "request": str(req_num)}
        }
        
        try:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return {
                    "status": resp.status,
                    "request": req_num,
                    "headers": dict(resp.headers)
                }
        except Exception as e:
            return {
                "status": "error",
                "request": req_num,
                "error": str(e)
            }
    
    async def test_retry_on_db_errors(self, endpoint: str = "/api/v1/ingest"):
        """
        Test retry logic when database has transient errors.
        
        This simulates database connection issues that should trigger retries.
        """
        print(f"\n=== Testing Retry Logic ===")
        print("Note: Actual DB errors require stopping/starting database")
        print("This test sends valid requests to verify retry infrastructure.")
        
        async with aiohttp.ClientSession() as session:
            # Send a few test requests
            for i in range(5):
                payload = {
                    "name": f"retry_test_{i}",
                    "value": 50 + i,
                    "tags": {"test": "retry", "attempt": str(i)}
                }
                
                try:
                    async with session.post(
                        f"{self.base_url}{endpoint}", 
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            print(f"  ✓ Request {i+1}: Success (metric_id: {data.get('metric_id')})")
                        else:
                            print(f"  ✗ Request {i+1}: Failed with status {resp.status}")
                
                except Exception as e:
                    print(f"  ✗ Request {i+1}: Exception - {e}")
                
                await asyncio.sleep(0.5)
    
    async def test_burst_traffic(self, endpoint: str = "/api/v1/ingest", duration: int = 10):
        """
        Send burst traffic to test both rate limiting and retry behavior.
        
        Args:
            endpoint: API endpoint
            duration: How long to send traffic (seconds)
        """
        print(f"\n=== Testing Burst Traffic ({duration}s) ===")
        
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            request_count = 0
            success_count = 0
            rate_limited_count = 0
            
            while time.time() - start_time < duration:
                payload = {
                    "name": f"burst_metric",
                    "value": 80.0 + (request_count % 20),
                    "tags": {"test": "burst", "request": str(request_count)}
                }
                
                try:
                    async with session.post(
                        f"{self.base_url}{endpoint}",
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=2)
                    ) as resp:
                        request_count += 1
                        
                        if resp.status == 200:
                            success_count += 1
                        elif resp.status == 429:
                            rate_limited_count += 1
                            retry_after = resp.headers.get("Retry-After", "unknown")
                            if request_count % 10 == 0:
                                print(f"  Rate limited (retry after {retry_after}s)")
                
                except Exception as e:
                    request_count += 1
                
                # Small delay between requests
                await asyncio.sleep(0.05)
            
            elapsed = time.time() - start_time
            print(f"\nBurst Traffic Results:")
            print(f"  Total requests: {request_count}")
            print(f"  ✓ Successful: {success_count}")
            print(f"  ⚠ Rate limited: {rate_limited_count}")
            print(f"  Rate: {request_count/elapsed:.1f} req/s")
    
    async def check_rate_limit_headers(self, endpoint: str = "/api/v1/ingest"):
        """Check that rate limit headers are present in responses."""
        print(f"\n=== Checking Rate Limit Headers ===")
        
        async with aiohttp.ClientSession() as session:
            payload = {
                "name": "header_test",
                "value": 42.0,
                "tags": {"test": "headers"}
            }
            
            try:
                async with session.post(f"{self.base_url}{endpoint}", json=payload) as resp:
                    headers = dict(resp.headers)
                    
                    print(f"Status: {resp.status}")
                    print("\nRate Limit Headers:")
                    
                    limit = headers.get("X-RateLimit-Limit", "Not present")
                    remaining = headers.get("X-RateLimit-Remaining", "Not present")
                    reset = headers.get("X-RateLimit-Reset", "Not present")
                    
                    print(f"  X-RateLimit-Limit: {limit}")
                    print(f"  X-RateLimit-Remaining: {remaining}")
                    print(f"  X-RateLimit-Reset: {reset}")
                    
                    if limit != "Not present":
                        print(f"\n✓ Rate limit headers are present")
                    else:
                        print(f"\n⚠ Rate limit headers missing (rate limiting may be disabled)")
            
            except Exception as e:
                print(f"✗ Error checking headers: {e}")


async def main():
    """Run failure simulation tests."""
    print("=" * 70)
    print("Phase 3 Failure Simulation & Testing")
    print("Retry Logic & Rate Limiting")
    print("=" * 70)
    
    # Check if server is running
    simulator = FailureSimulator()
    
    print("\nChecking if Vigil API is running...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{simulator.base_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    print("✓ API is running")
                else:
                    print(f"⚠ API returned status {resp.status}")
    except Exception as e:
        print(f"✗ Cannot connect to API: {e}")
        print(f"\nPlease start the Vigil API first:")
        print(f"  cd python")
        print(f"  uvicorn app.main:app --reload")
        sys.exit(1)
    
    # Run tests
    await simulator.check_rate_limit_headers()
    await simulator.test_retry_on_db_errors()
    await simulator.test_rate_limiting("/api/v1/ingest", num_requests=250)
    await simulator.test_burst_traffic(duration=10)
    
    print("\n" + "=" * 70)
    print("Simulation Complete")
    print("=" * 70)
    print("\nCheck application logs to see:")
    print("  - Retry attempts with exponential backoff")
    print("  - Rate limit warnings and blocks")
    print("  - Structured logging of events")


if __name__ == "__main__":
    asyncio.run(main())
