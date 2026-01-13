#!/usr/bin/env python3
"""
Vigil Verification Script

Tests all major endpoints to verify system functionality:
- POST /api/v1/ingest: Ingest metrics
- GET /api/v1/query: Query stored metrics
- POST /api/v1/actions: Create remediation actions
- GET /ui/health: Health check
- GET /ui/dashboard: Dashboard serving

Prints success/failure for each step and exits with non-zero code if any test fails.
Includes equivalent curl commands for manual testing.
"""

import asyncio
import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any

import httpx

# Configuration
API_BASE_URL = "http://localhost:8000"
API_V1_PREFIX = f"{API_BASE_URL}/api/v1"
TIMEOUT = 10.0

# Test results tracking
test_results = []


def print_header(title: str):
    """Print a formatted section header."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def print_test(test_name: str, success: bool, message: str = "", details: str = ""):
    """Print test result with status."""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} | {test_name}")
    if message:
        print(f"       Message: {message}")
    if details:
        print(f"       Details: {details}")
    test_results.append((test_name, success))


def print_curl_command(description: str, method: str, endpoint: str, data: Optional[Dict] = None):
    """Print equivalent curl command for manual testing."""
    url = f"{API_BASE_URL}{endpoint}"
    
    print(f"\n   Manual Test with curl:")
    print(f"   {description}")
    
    if method == "GET":
        print(f"   $ curl -X GET '{url}'")
    elif method == "POST":
        if data:
            json_str = json.dumps(data)
            print(f"   $ curl -X POST '{url}' \\")
            print(f"     -H 'Content-Type: application/json' \\")
            print(f"     -d '{json_str}'")
        else:
            print(f"   $ curl -X POST '{url}'")
    elif method == "DELETE":
        print(f"   $ curl -X DELETE '{url}'")


async def test_ingest_metric(client: httpx.AsyncClient) -> bool:
    """Test metric ingestion endpoint."""
    test_name = "Ingest Metric"
    print(f"\n[TEST 1] {test_name}")
    print("-" * 70)
    
    endpoint = "/api/v1/ingest"
    payload = {
        "name": "cpu_burst",
        "value": 92.5,
        "tags": {
            "host": "web-server-01",
            "region": "us-east-1",
            "service": "api"
        }
    }
    
    print(f"Endpoint: POST {endpoint}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = await client.post(
            f"{API_V1_PREFIX}{endpoint}",
            json=payload,
            timeout=TIMEOUT
        )
        
        if response.status_code == 201:
            data = response.json()
            print(f"\nStatus Code: {response.status_code} (Created)")
            print(f"Response: {json.dumps(data, indent=2)}")
            
            # Verify response structure
            if data.get("ok") and "metric_id" in data:
                metric_id = data["metric_id"]
                print(f"\n✓ Metric ingested successfully (ID: {metric_id})")
                print_curl_command("Test metric ingestion", "POST", endpoint, payload)
                print_test(test_name, True, f"Metric ID: {metric_id}")
                return True
            else:
                print_test(test_name, False, "Invalid response structure", str(data))
                return False
        else:
            print(f"\nStatus Code: {response.status_code}")
            print(f"Response: {response.text}")
            print_test(test_name, False, f"HTTP {response.status_code}", response.text)
            return False
            
    except httpx.ConnectError:
        print_test(test_name, False, "Connection error", f"Cannot connect to {API_BASE_URL}")
        return False
    except Exception as e:
        print_test(test_name, False, str(e))
        return False


async def test_query_metrics(client: httpx.AsyncClient) -> bool:
    """Test metrics query endpoint."""
    test_name = "Query Metrics"
    print(f"\n[TEST 2] {test_name}")
    print("-" * 70)
    
    endpoint = "/api/v1/query"
    params = {"metric_name": "cpu_burst"}
    
    print(f"Endpoint: GET {endpoint}")
    print(f"Params: {json.dumps(params, indent=2)}")
    
    try:
        response = await client.get(
            f"{API_V1_PREFIX}{endpoint}",
            params=params,
            timeout=TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"\nStatus Code: {response.status_code} (OK)")
            print(f"Response: {json.dumps(data, indent=2)}")
            
            # Verify response structure
            if isinstance(data, dict) and "metrics" in data:
                metrics_count = len(data.get("metrics", []))
                print(f"\n✓ Found {metrics_count} metric(s)")
                print_curl_command("Test query metrics", "GET", f"{endpoint}?metric_name=cpu_burst")
                print_test(test_name, True, f"Metrics found: {metrics_count}")
                return True
            else:
                print_test(test_name, False, "Invalid response structure", str(data))
                return False
        elif response.status_code == 404:
            print(f"\nStatus Code: {response.status_code} (Not Found)")
            print("Note: Query endpoint may not be implemented yet")
            print_curl_command("Test query metrics", "GET", f"{endpoint}?metric_name=cpu_burst")
            print_test(test_name, False, "Endpoint not implemented")
            return False
        else:
            print(f"\nStatus Code: {response.status_code}")
            print(f"Response: {response.text}")
            print_test(test_name, False, f"HTTP {response.status_code}", response.text)
            return False
            
    except httpx.ConnectError:
        print_test(test_name, False, "Connection error", f"Cannot connect to {API_BASE_URL}")
        return False
    except Exception as e:
        print_test(test_name, False, str(e))
        return False


async def test_create_action(client: httpx.AsyncClient) -> bool:
    """Test action creation endpoint."""
    test_name = "Create Remediation Action"
    print(f"\n[TEST 3] {test_name}")
    print("-" * 70)
    
    endpoint = "/api/v1/actions"
    payload = {
        "target": "web-server-01",
        "action": "restart_service",
        "status": "pending",
        "details": "High CPU detected. Restarting web service."
    }
    
    print(f"Endpoint: POST {endpoint}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = await client.post(
            f"{API_V1_PREFIX}{endpoint}",
            json=payload,
            timeout=TIMEOUT
        )
        
        if response.status_code == 201:
            data = response.json()
            print(f"\nStatus Code: {response.status_code} (Created)")
            print(f"Response: {json.dumps(data, indent=2)}")
            
            # Verify response structure
            if data.get("ok") and "action_id" in data:
                action_id = data["action_id"]
                print(f"\n✓ Action created successfully (ID: {action_id})")
                print_curl_command("Test action creation", "POST", endpoint, payload)
                print_test(test_name, True, f"Action ID: {action_id}")
                return True
            else:
                print_test(test_name, False, "Invalid response structure", str(data))
                return False
        else:
            print(f"\nStatus Code: {response.status_code}")
            print(f"Response: {response.text}")
            print_test(test_name, False, f"HTTP {response.status_code}", response.text)
            return False
            
    except httpx.ConnectError:
        print_test(test_name, False, "Connection error", f"Cannot connect to {API_BASE_URL}")
        return False
    except Exception as e:
        print_test(test_name, False, str(e))
        return False


async def test_ui_health(client: httpx.AsyncClient) -> bool:
    """Test UI health check endpoint."""
    test_name = "UI Health Check"
    print(f"\n[TEST 4] {test_name}")
    print("-" * 70)
    
    endpoint = "/ui/health"
    
    print(f"Endpoint: GET {endpoint}")
    
    try:
        response = await client.get(
            f"{API_BASE_URL}{endpoint}",
            timeout=TIMEOUT
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"\nStatus Code: {response.status_code} (OK)")
            print(f"Response: {json.dumps(data, indent=2)}")
            
            # Verify response structure
            if "status" in data:
                status = data["status"]
                print(f"\n✓ Service health status: {status}")
                print_curl_command("Test health check", "GET", endpoint)
                print_test(test_name, True, f"Status: {status}")
                return True
            else:
                print_test(test_name, False, "Invalid response structure", str(data))
                return False
        else:
            print(f"\nStatus Code: {response.status_code}")
            print(f"Response: {response.text}")
            print_test(test_name, False, f"HTTP {response.status_code}", response.text)
            return False
            
    except httpx.ConnectError:
        print_test(test_name, False, "Connection error", f"Cannot connect to {API_BASE_URL}")
        return False
    except Exception as e:
        print_test(test_name, False, str(e))
        return False


async def test_ui_dashboard(client: httpx.AsyncClient) -> bool:
    """Test dashboard HTML serving."""
    test_name = "Dashboard HTML Serving"
    print(f"\n[TEST 5] {test_name}")
    print("-" * 70)
    
    endpoint = "/ui/dashboard"
    
    print(f"Endpoint: GET {endpoint}")
    
    try:
        response = await client.get(
            f"{API_BASE_URL}{endpoint}",
            timeout=TIMEOUT
        )
        
        if response.status_code == 200:
            content = response.text
            print(f"\nStatus Code: {response.status_code} (OK)")
            print(f"Content-Type: {response.headers.get('content-type', 'unknown')}")
            print(f"Content Length: {len(content)} bytes")
            
            # Verify HTML content
            if "<!DOCTYPE html" in content or "<html" in content.lower():
                # Extract title for verification
                import re
                title_match = re.search(r"<title>([^<]+)</title>", content, re.IGNORECASE)
                title = title_match.group(1) if title_match else "Unknown"
                
                print(f"\n✓ HTML content received")
                print(f"  Page Title: {title}")
                print(f"  Content Preview: {content[:200]}...")
                print_curl_command("Test dashboard", "GET", endpoint)
                print_test(test_name, True, f"HTML page ({len(content)} bytes)")
                return True
            else:
                print_test(test_name, False, "Invalid HTML content", "Expected HTML, got: " + content[:100])
                return False
        else:
            print(f"\nStatus Code: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            print_test(test_name, False, f"HTTP {response.status_code}", response.text)
            return False
            
    except httpx.ConnectError:
        print_test(test_name, False, "Connection error", f"Cannot connect to {API_BASE_URL}")
        return False
    except Exception as e:
        print_test(test_name, False, str(e))
        return False


async def run_all_tests():
    """Run all verification tests."""
    print_header("VIGIL SYSTEM VERIFICATION")
    print(f"Testing API at: {API_BASE_URL}")
    print(f"Started at: {datetime.now().isoformat()}")
    
    # Create async client
    async with httpx.AsyncClient() as client:
        # Test 1: Ingest metric
        result1 = await test_ingest_metric(client)
        
        # Test 2: Query metrics
        result2 = await test_query_metrics(client)
        
        # Test 3: Create action
        result3 = await test_create_action(client)
        
        # Test 4: UI Health check
        result4 = await test_ui_health(client)
        
        # Test 5: Dashboard
        result5 = await test_ui_dashboard(client)
    
    # Print summary
    print_header("VERIFICATION SUMMARY")
    print(f"{'Test':<40} {'Result':<10}")
    print("-" * 70)
    
    for test_name, success in test_results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:<40} {status}")
    
    # Calculate statistics
    total_tests = len(test_results)
    passed_tests = sum(1 for _, success in test_results if success)
    failed_tests = total_tests - passed_tests
    pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    
    print("-" * 70)
    print(f"Total: {total_tests} | Passed: {passed_tests} | Failed: {failed_tests}")
    print(f"Pass Rate: {pass_rate:.1f}%")
    print(f"Completed at: {datetime.now().isoformat()}")
    
    # Exit with appropriate code
    if failed_tests == 0:
        print("\n✅ ALL TESTS PASSED")
        return 0
    else:
        print(f"\n❌ {failed_tests} TEST(S) FAILED")
        return 1


def main():
    """Main entry point."""
    try:
        exit_code = asyncio.run(run_all_tests())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
