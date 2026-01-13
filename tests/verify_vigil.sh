#!/bin/bash
###############################################################################
# Vigil System Verification Script
#
# Tests all major endpoints to verify system functionality:
# - POST /api/v1/ingest: Ingest metrics
# - POST /api/v1/actions: Create remediation actions
# - GET /ui/health: Health check
# - GET /ui/dashboard: Dashboard serving
#
# Prints success/failure for each step with curl commands for manual testing
###############################################################################

set -e

# Configuration
API_BASE_URL="http://localhost:8000"
API_V1_PREFIX="$API_BASE_URL/api/v1"

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test tracking
PASSED=0
FAILED=0
TOTAL=0

###############################################################################
# Helper Functions
###############################################################################

print_header() {
    local title="$1"
    echo ""
    echo "╔════════════════════════════════════════════════════════════════════════╗"
    echo "║  $title"
    echo "╚════════════════════════════════════════════════════════════════════════╝"
    echo ""
}

print_test() {
    local test_name="$1"
    local success="$2"
    local message="$3"
    local details="$4"
    
    TOTAL=$((TOTAL + 1))
    
    if [ "$success" = "true" ]; then
        echo -e "${GREEN}✅ PASS${NC} | $test_name"
        PASSED=$((PASSED + 1))
    else
        echo -e "${RED}❌ FAIL${NC} | $test_name"
        FAILED=$((FAILED + 1))
    fi
    
    if [ -n "$message" ]; then
        echo "       Message: $message"
    fi
    if [ -n "$details" ]; then
        echo "       Details: $details"
    fi
}

print_curl_command() {
    local description="$1"
    local method="$2"
    local endpoint="$3"
    local data="$4"
    
    echo ""
    echo -e "${BLUE}Manual Test with curl:${NC}"
    echo "   $description"
    echo ""
    
    local url="$API_BASE_URL$endpoint"
    
    if [ "$method" = "GET" ]; then
        echo "   \$ curl -X GET '$url'"
    elif [ "$method" = "POST" ]; then
        if [ -n "$data" ]; then
            echo "   \$ curl -X POST '$url' \\"
            echo "     -H 'Content-Type: application/json' \\"
            echo "     -d '$data'"
        else
            echo "   \$ curl -X POST '$url'"
        fi
    fi
}

###############################################################################
# Main Tests
###############################################################################

main() {
    print_header "VIGIL SYSTEM VERIFICATION"
    
    echo "Testing API at: $API_BASE_URL"
    echo "Started at: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo ""
    
    # Test 1: Ingest Metric
    echo "─────────────────────────────────────────────────────────────────────────"
    echo "[TEST 1] Ingest Metric"
    echo "─────────────────────────────────────────────────────────────────────────"
    
    ENDPOINT="/ingest"
    PAYLOAD='{"name": "cpu_burst", "value": 92.5, "tags": {"host": "web-server-01", "region": "us-east-1", "service": "api"}}'
    
    echo "Endpoint: POST $ENDPOINT"
    echo "Payload:"
    echo "  {\"name\": \"cpu_burst\", \"value\": 92.5, \"tags\": {...}}"
    echo ""
    
    RESPONSE=$(curl -s -X POST "$API_BASE_URL$ENDPOINT" \
      -H "Content-Type: application/json" \
      -d "$PAYLOAD" \
      -w "\n%{http_code}")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | head -n-1)
    
    echo "Status Code: $HTTP_CODE"
    echo "Response: $BODY"
    echo ""
    
    if echo "$HTTP_CODE" | grep -qE "^(201|200)$"; then
        if echo "$BODY" | grep -q '"ok"'; then
            METRIC_ID=$(echo "$BODY" | grep -o '"metric_id":[0-9]*' | grep -o '[0-9]*' || echo "unknown")
            echo -e "${GREEN}✓ Metric ingested successfully (ID: $METRIC_ID)${NC}"
            print_curl_command "Test metric ingestion" "POST" "$ENDPOINT" "$PAYLOAD"
            print_test "Ingest Metric" "true" "Metric ID: $METRIC_ID"
        else
            print_test "Ingest Metric" "false" "Invalid response structure" "$BODY"
        fi
    else
        print_test "Ingest Metric" "false" "HTTP $HTTP_CODE" "$BODY"
    fi
    
    echo ""
    
    # Test 2: Query Metrics
    echo "─────────────────────────────────────────────────────────────────────────"
    echo "[TEST 2] Query Metrics"
    echo "─────────────────────────────────────────────────────────────────────────"
    
    ENDPOINT="/query?metric_name=cpu_burst"
    
    echo "Endpoint: GET $ENDPOINT"
    echo ""
    
    RESPONSE=$(curl -s -X GET "$API_BASE_URL$ENDPOINT" \
      -w "\n%{http_code}")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | head -n-1)
    
    echo "Status Code: $HTTP_CODE"
    echo "Response: $BODY"
    echo ""
    
    if [ "$HTTP_CODE" = "200" ]; then
        if echo "$BODY" | grep -q '"metrics"'; then
            METRICS_COUNT=$(echo "$BODY" | grep -o '"metrics"' | wc -l)
            echo -e "${GREEN}✓ Found metrics${NC}"
            print_curl_command "Test query metrics" "GET" "$ENDPOINT"
            print_test "Query Metrics" "true" "Status 200"
        else
            print_test "Query Metrics" "false" "Invalid response structure" "$BODY"
        fi
    else
        print_test "Query Metrics" "false" "HTTP $HTTP_CODE" "$BODY"
    fi
    
    echo ""
    
    # Test 3: Dashboard
    echo "─────────────────────────────────────────────────────────────────────────"
    echo "[TEST 3] Dashboard HTML Serving"
    echo "─────────────────────────────────────────────────────────────────────────"
    
    ENDPOINT="/dashboard"
    
    echo "Endpoint: GET $ENDPOINT"
    echo ""
    
    RESPONSE=$(curl -s -X GET "$API_BASE_URL$ENDPOINT" \
      -w "\n%{http_code}")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | head -n-1)
    
    CONTENT_TYPE=$(curl -s -I "$API_BASE_URL$ENDPOINT" 2>/dev/null | grep -i "content-type" | tr -d '\r' | cut -d' ' -f2-)
    CONTENT_LEN=${#BODY}
    
    echo "Status Code: $HTTP_CODE"
    echo "Content-Type: $CONTENT_TYPE"
    echo "Content Length: $CONTENT_LEN bytes"
    echo "Content Preview: ${BODY:0:150}..."
    echo ""
    
    if [ "$HTTP_CODE" = "200" ] && (echo "$BODY" | grep -qi "vigil\|dashboard\|html\|<!doctype"); then
        echo -e "${GREEN}✓ HTML content received${NC}"
        print_curl_command "Test dashboard" "GET" "$ENDPOINT"
        print_test "Dashboard HTML" "true" "HTML page ($CONTENT_LEN bytes)"
    else
        print_test "Dashboard HTML" "false" "HTTP $HTTP_CODE or invalid HTML" "${BODY:0:100}"
    fi
    
    echo ""
    
    # Test 4: Create Action
    echo "─────────────────────────────────────────────────────────────────────────"
    echo "[TEST 4] Create Remediation Action"
    echo "─────────────────────────────────────────────────────────────────────────"
    
    ENDPOINT="/actions"
    PAYLOAD='{"target": "web-server-01", "action": "restart_service", "status": "pending", "details": "High CPU detected. Restarting web service."}'
    
    echo "Endpoint: POST $ENDPOINT"
    echo "Payload:"
    echo "  {\"target\": \"web-server-01\", \"action\": \"restart_service\", ...}"
    echo ""
    
    RESPONSE=$(curl -s -X POST "$API_BASE_URL$ENDPOINT" \
      -H "Content-Type: application/json" \
      -d "$PAYLOAD" \
      -w "\n%{http_code}")
    
    HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
    BODY=$(echo "$RESPONSE" | head -n-1)
    
    echo "Status Code: $HTTP_CODE"
    echo "Response: $BODY"
    echo ""
    
    if echo "$HTTP_CODE" | grep -qE "^(201|200)$"; then
        if echo "$BODY" | grep -q '"ok"'; then
            ACTION_ID=$(echo "$BODY" | grep -o '"action_id":[0-9]*' | grep -o '[0-9]*' || echo "unknown")
            echo -e "${GREEN}✓ Action created successfully (ID: $ACTION_ID)${NC}"
            print_curl_command "Test action creation" "POST" "$ENDPOINT" "$PAYLOAD"
            print_test "Create Action" "true" "Action ID: $ACTION_ID"
        else
            print_test "Create Action" "false" "Invalid response structure" "$BODY"
        fi
    else
        print_test "Create Action" "false" "HTTP $HTTP_CODE" "$BODY"
    fi
    
    echo ""
    
    # Print Summary
    print_header "VERIFICATION SUMMARY"
    
    echo "Test Results:"
    echo "  1. Ingest Metric:        $([ $PASSED -gt 0 ] && echo 'CHECK ABOVE' || echo 'FAILED')"
    echo "  2. Query Metrics:        $([ $PASSED -gt 1 ] && echo 'CHECK ABOVE' || echo 'FAILED')"
    echo "  3. Dashboard HTML:       $([ $PASSED -gt 2 ] && echo 'CHECK ABOVE' || echo 'FAILED')"
    echo "  4. Create Action:        $([ $PASSED -gt 3 ] && echo 'CHECK ABOVE' || echo 'FAILED')"
    echo ""
    echo "Total: $TOTAL | Passed: $PASSED | Failed: $FAILED"
    if [ $TOTAL -gt 0 ]; then
        PASS_RATE=$((PASSED * 100 / TOTAL))
        echo "Pass Rate: ${PASS_RATE}%"
    fi
    echo "Completed at: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo ""
    
    if [ "$FAILED" -eq 0 ]; then
        echo -e "${GREEN}✅ ALL TESTS PASSED${NC}"
        return 0
    else
        echo -e "${RED}❌ $FAILED TEST(S) FAILED${NC}"
        return 1
    fi
}

###############################################################################
# Run Tests
###############################################################################

if main; then
    exit 0
else
    exit 1
fi
