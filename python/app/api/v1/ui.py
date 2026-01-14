"""
UI Router - Dashboard and Static Asset Serving

This module provides FastAPI routes for serving the Vigil dashboard UI
and associated static assets (CSS, JavaScript, etc.).

It includes:
- Dashboard HTML rendering
- Health check endpoint
- Static file serving integration
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from python.app.core.logger import get_logger
from python.app.core.db import Alert, Action, get_session

# Get router logger
logger = get_logger(__name__)

# Create router with /ui prefix
router = APIRouter(
    prefix="/ui",
    tags=["UI"],
    responses={
        404: {"description": "Asset or page not found"},
        500: {"description": "Internal server error"},
    },
)

# Define static directory path
STATIC_DIR = Path(__file__).parent.parent.parent / "static"
DASHBOARD_HTML_PATH = STATIC_DIR / "dashboard.html"


def ensure_static_dir():
    """Ensure static directory exists and create if needed."""
    try:
        STATIC_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Static directory verified",
            static_dir=str(STATIC_DIR),
            exists=True
        )
    except Exception as e:
        logger.error(
            "Failed to create static directory",
            static_dir=str(STATIC_DIR),
            error=str(e),
            exc_info=True
        )


def create_default_dashboard() -> str:
    """
    Create a default dashboard HTML if none exists.
    
    Returns:
        str: Default HTML content for dashboard
    """
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vigil Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        
        header {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 8px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1);
        }
        
        h1 {
            color: #667eea;
            font-size: 32px;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #666;
            font-size: 16px;
        }
        
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .card {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 15px 50px rgba(0, 0, 0, 0.15);
        }
        
        .card h2 {
            color: #667eea;
            font-size: 18px;
            margin-bottom: 15px;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        
        .card p {
            color: #666;
            line-height: 1.6;
            margin-bottom: 15px;
        }
        
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #eee;
        }
        
        .metric:last-child {
            border-bottom: none;
        }
        
        .metric-label {
            color: #666;
            font-weight: 500;
        }
        
        .metric-value {
            color: #667eea;
            font-weight: bold;
            font-size: 18px;
        }
        
        .status {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }
        
        .status.healthy {
            background: #d4edda;
            color: #155724;
        }
        
        .status.warning {
            background: #fff3cd;
            color: #856404;
        }
        
        .status.error {
            background: #f8d7da;
            color: #721c24;
        }
        
        .endpoint-list {
            list-style: none;
            padding: 0;
        }
        
        .endpoint-list li {
            padding: 10px 0;
            border-bottom: 1px solid #eee;
            color: #666;
        }
        
        .endpoint-list li:last-child {
            border-bottom: none;
        }
        
        .endpoint-method {
            display: inline-block;
            width: 60px;
            padding: 3px 8px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 12px;
            margin-right: 10px;
            color: white;
        }
        
        .method-get {
            background: #007bff;
        }
        
        .method-post {
            background: #28a745;
        }
        
        .method-delete {
            background: #dc3545;
        }
        
        .footer {
            text-align: center;
            color: rgba(255, 255, 255, 0.7);
            padding: 20px;
            margin-top: 30px;
        }
        
        .api-docs-link {
            display: inline-block;
            margin-top: 15px;
            padding: 10px 20px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-weight: bold;
            transition: background 0.2s;
        }
        
        .api-docs-link:hover {
            background: #764ba2;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚨 Vigil Monitoring System</h1>
            <p class="subtitle">Real-time infrastructure monitoring and automated remediation</p>
        </header>
        
        <div class="dashboard-grid">
            <div class="card">
                <h2>📊 System Status</h2>
                <div class="metric">
                    <span class="metric-label">Service Status</span>
                    <span class="status healthy">Healthy</span>
                </div>
                <div class="metric">
                    <span class="metric-label">API Version</span>
                    <span class="metric-value">1.0.0</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Database</span>
                    <span class="status healthy">Connected</span>
                </div>
            </div>
            
            <div class="card">
                <h2>🔌 Quick Links</h2>
                <ul class="endpoint-list">
                    <li><span class="endpoint-method method-post">POST</span>/ingest - Submit metrics</li>
                    <li><span class="endpoint-method method-get">GET</span>/actions - List remediation actions</li>
                    <li><span class="endpoint-method method-post">POST</span>/actions - Create action</li>
                    <li><span class="endpoint-method method-get">GET</span>/queries - Query historical data</li>
                </ul>
                <a href="/docs" class="api-docs-link">📖 API Documentation</a>
            </div>
            
            <div class="card">
                <h2>📈 Metrics Summary</h2>
                <div class="metric">
                    <span class="metric-label">Total Metrics</span>
                    <span class="metric-value">--</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Active Alerts</span>
                    <span class="metric-value">--</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Remediation Actions</span>
                    <span class="metric-value">--</span>
                </div>
            </div>
            
            <div class="card">
                <h2>⚙️ Configuration</h2>
                <div class="metric">
                    <span class="metric-label">Environment</span>
                    <span class="metric-value">Production</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Evaluator</span>
                    <span class="status healthy">Enabled</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Logging</span>
                    <span class="metric-value">JSON</span>
                </div>
            </div>
            
            <div class="card">
                <h2>🔧 Components</h2>
                <ul class="endpoint-list">
                    <li>✅ Metrics Ingestion</li>
                    <li>✅ Policy Evaluation</li>
                    <li>✅ Action Management</li>
                    <li>✅ Data Queries</li>
                </ul>
            </div>
            
            <div class="card">
                <h2>📚 Resources</h2>
                <ul class="endpoint-list">
                    <li><a href="/docs" style="color: #667eea;">Interactive API Docs (Swagger)</a></li>
                    <li><a href="/redoc" style="color: #667eea;">API Reference (ReDoc)</a></li>
                    <li><a href="/openapi.json" style="color: #667eea;">OpenAPI Schema</a></li>
                    <li><a href="/actions/health" style="color: #667eea;">Health Check</a></li>
                </ul>
            </div>
        </div>
        
        <div class="footer">
            <p>Vigil © 2026 | Monitoring made simple</p>
        </div>
    </div>
    
    <script>
        // Placeholder for dynamic updates
        console.log('Vigil Dashboard loaded');
    </script>
</body>
</html>
"""


@router.get(
    "/dashboard",
    response_class=HTMLResponse,
    summary="Dashboard",
    description="Serve the main Vigil dashboard page"
)
async def serve_dashboard() -> str:
    """
    Serve the Vigil dashboard HTML page.
    
    Returns the dashboard HTML with styling and quick links to API endpoints.
    Falls back to a default dashboard if custom HTML is not found.
    
    Returns:
        str: HTML content of the dashboard page
        
    Raises:
        HTTPException: 500 if unable to read or generate dashboard
    """
    try:
        if DASHBOARD_HTML_PATH.exists() and DASHBOARD_HTML_PATH.stat().st_size > 0:
            logger.debug(
                "Serving custom dashboard",
                path=str(DASHBOARD_HTML_PATH)
            )
            with open(DASHBOARD_HTML_PATH, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            logger.debug(
                "Dashboard HTML not found or empty, serving default",
                path=str(DASHBOARD_HTML_PATH)
            )
            return create_default_dashboard()
    except Exception as e:
        logger.error(
            "Failed to serve dashboard",
            path=str(DASHBOARD_HTML_PATH),
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to serve dashboard"
        )


@router.get(
    "/health",
    summary="Health Check",
    description="Check if the UI service is operational"
)
async def health_check() -> Dict[str, str]:
    """
    Health check endpoint for the UI service.
    
    Returns:
        Dict with status indicator
    """
    logger.debug("UI health check requested")
    return {"status": "ok"}


async def get_active_policies() -> Dict[str, Dict]:
    """
    Fetch active policies from the policy registry.
    
    Returns:
        Dict mapping policy name to policy details (condition, action, severity, target)
    """
    try:
        from python.app.core.policy import get_policy_registry
        
        registry = get_policy_registry()
        policies_list = registry.get_enabled()
        
        active_policies = {}
        for policy in policies_list:
            active_policies[policy.name] = {
                "name": policy.name,
                "condition": str(policy.condition) if policy.condition else "N/A",
                "action": policy.action.name if hasattr(policy.action, 'name') else str(policy.action),
                "severity": policy.severity.name if hasattr(policy.severity, 'name') else str(policy.severity),
                "target": policy.target,
                "auto_remediate": policy.auto_remediate,
            }
        
        return active_policies
    except ImportError:
        logger.warning("Policy registry not available")
        return {}
    except Exception as e:
        logger.error(
            "Failed to fetch active policies",
            error=str(e),
            exc_info=True
        )
        return {}


async def get_recent_violations(hours: int = 24) -> List[Dict]:
    """
    Fetch recent policy violations (alerts) from the database.
    
    Args:
        hours: Number of hours to look back (default: 24)
    
    Returns:
        List of violation records with timestamp, severity, name, and details
    """
    try:
        async with get_session() as session:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            stmt = select(Alert).where(
                Alert.triggered_at >= cutoff_time
            ).order_by(
                desc(Alert.triggered_at)
            ).limit(100)
            
            result = await session.execute(stmt)
            alerts = result.scalars().all()
            
            violations = []
            for alert in alerts:
                violations.append({
                    "id": alert.id,
                    "policy_name": alert.name,
                    "severity": alert.severity,
                    "condition": alert.condition,
                    "timestamp": alert.triggered_at.isoformat() if alert.triggered_at else None,
                    "resolved": alert.resolved_at is not None,
                    "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
                    "details": alert.details,
                })
            
            return violations
    except Exception as e:
        logger.error(
            "Failed to fetch recent violations",
            error=str(e),
            exc_info=True
        )
        return []


async def get_remediation_logs(hours: int = 24, limit: int = 50) -> List[Dict]:
    """
    Fetch remediation action logs from the database.
    
    Args:
        hours: Number of hours to look back (default: 24)
        limit: Maximum number of records to return (default: 50)
    
    Returns:
        List of action logs with target, action, status, timestamp, and details
    """
    try:
        async with get_session() as session:
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            stmt = select(Action).where(
                Action.started_at >= cutoff_time
            ).order_by(
                desc(Action.started_at)
            ).limit(limit)
            
            result = await session.execute(stmt)
            actions = result.scalars().all()
            
            logs = []
            for action in actions:
                logs.append({
                    "id": action.id,
                    "target": action.target,
                    "action": action.action,
                    "status": action.status,
                    "timestamp": action.started_at.isoformat() if action.started_at else None,
                    "detail": action.details,
                })
            
            return logs
    except Exception as e:
        logger.error(
            "Failed to fetch remediation logs",
            error=str(e),
            exc_info=True
        )
        return []


@router.get(
    "/policies",
    summary="Get Policy Status",
    description="Get comprehensive policy information, violations, and remediation logs for dashboard display"
)
async def get_policy_status(request: Request) -> Dict:
    """
    Get comprehensive policy information for dashboard display.
    
    Returns:
        Dict containing:
        - active_policies: Currently enabled policies with details
        - recent_violations: Policy violations from last 24 hours
        - remediation_logs: Remediation actions from last 24 hours
        - runner_status: Policy runner state and configuration
        - timestamp: Response generation timestamp
    """
    request_start = datetime.utcnow()
    
    try:
        from python.app.core.policy import get_policy_registry
        from python.app.core.policy_runner import get_policy_runner_status
        
        # Audit logging - log policy status request
        logger.info(
            "Policy status request received",
            client_ip=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", "unknown"),
            method=request.method,
            path=request.url.path,
        )
        
        # Fetch active policies
        active_policies = await get_active_policies()
        
        # Fetch recent violations from Alert table
        recent_violations = await get_recent_violations(hours=24)
        
        # Fetch remediation logs from Action table
        remediation_logs = await get_remediation_logs(hours=24)
        
        # Get policy registry stats
        registry = get_policy_registry()
        enabled_count = len([p for p in registry.get_enabled()])
        total_count = len(registry.list_policies())
        runner_status = get_policy_runner_status()
        
        response_time = (datetime.utcnow() - request_start).total_seconds()
        
        response_data = {
            "ok": True,
            "timestamp": datetime.utcnow().isoformat(),
            "response_time_seconds": round(response_time, 3),
            "summary": {
                "total_policies": total_count,
                "enabled_policies": enabled_count,
                "recent_violations": len(recent_violations),
                "remediation_actions": len(remediation_logs),
            },
            "active_policies": active_policies,
            "recent_violations": recent_violations,
            "remediation_logs": remediation_logs,
            "runner_status": runner_status,
        }
        
        # Audit log - successful response
        logger.info(
            "Policy status returned successfully",
            client_ip=request.client.host if request.client else "unknown",
            total_policies=total_count,
            enabled_policies=enabled_count,
            recent_violations=len(recent_violations),
            remediation_actions=len(remediation_logs),
            response_time_seconds=response_time,
        )
        
        return response_data
        
    except ImportError as e:
        logger.warning(
            "Policy engine not available",
            error=str(e),
        )
        return {
            "ok": True,
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "total_policies": 0,
                "enabled_policies": 0,
                "recent_violations": 0,
                "remediation_actions": 0,
            },
            "active_policies": {},
            "recent_violations": [],
            "remediation_logs": [],
            "runner_status": {
                "enabled": False,
                "running": False,
                "message": "Policy engine not available"
            }
        }
    except Exception as e:
        logger.error(
            "Failed to get policy status",
            error=str(e),
            client_ip=request.client.host if request.client else "unknown",
            exc_info=True
        )
        return {
            "ok": False,
            "timestamp": datetime.utcnow().isoformat(),
            "error": "Failed to retrieve policy status",
            "error_detail": str(e) if str(e) else "Unknown error",
            "summary": {
                "total_policies": 0,
                "enabled_policies": 0,
                "recent_violations": 0,
                "remediation_actions": 0,
            }
        }


def mount_static_files(app) -> None:
    """
    Mount static files directory to the FastAPI application.
    
    This function should be called from main.py after creating the FastAPI app
    and including the UI router.
    
    Args:
        app: FastAPI application instance
        
    Example:
        from fastapi import FastAPI
        from python.app.api.v1.ui import mount_static_files
        
        app = FastAPI()
        mount_static_files(app)
    """
    try:
        ensure_static_dir()
        
        # Mount static files
        app.mount(
            "/static",
            StaticFiles(directory=str(STATIC_DIR)),
            name="static"
        )
        
        logger.info(
            "Static files mounted",
            static_dir=str(STATIC_DIR),
            mount_path="/static"
        )
    except Exception as e:
        logger.error(
            "Failed to mount static files",
            static_dir=str(STATIC_DIR),
            error=str(e),
            exc_info=True
        )
