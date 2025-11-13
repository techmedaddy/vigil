from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3
import os
import requests
import json
import yaml
from dotenv import load_dotenv

# --- Import Evaluator ---
# Assuming evaluator.py is in the 'app' directory or a discoverable path
try:
    from app.evaluator import evaluate_policies
except ImportError:
    print("Warning: Could not import 'app.evaluator'. Policy evaluation will be skipped.")
    # Define a dummy function to prevent crashes if import fails
    def evaluate_policies(name: str, value: float) -> list:
        return []

# --- Configuration Loading ---
load_dotenv()  # Load .env file, environment variables take precedence

CONFIG_FILE_PATH = os.getenv("CONFIG_PATH", "configs/collector.yaml")

# Default configuration
config = {
    "db_path": "python/app/vigil.db",
    "remediator_url": "http://127.0.0.1:8081/remediate",
}

if os.path.exists(CONFIG_FILE_PATH):
    try:
        with open(CONFIG_FILE_PATH, 'r') as f:
            yaml_config = yaml.safe_load(f)
            if yaml_config:
                config.update(yaml_config)
    except Exception as e:
        print(f"Warning: Could not load YAML config {CONFIG_FILE_PATH}: {e}")
else:
    print(f"Info: Config file not found at {CONFIG_FILE_PATH}, using defaults.")

# Environment variables override YAML and defaults
DB_PATH = os.getenv("DB_PATH", config.get("db_path"))
REMEDIATOR_URL = os.getenv("REMEDIATOR_URL", config.get("remediator_url"))
# --- End Configuration ---


app = FastAPI(title="Vigil Collector")

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# --- Static Files ---
# Define the path to the static directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
    print(f"Created static directory: {static_dir}")

app.mount("/static", StaticFiles(directory=static_dir), name="static")
dashboard_html_path = os.path.join(static_dir, "dashboard.html")

# --- Database Setup ---

def init_db():
    """Initializes the database and creates tables if they don't exist."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        print(f"Created database directory: {db_dir}")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT,
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def get_db():
    """Returns a database connection."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

init_db()

# --- Background Tasks ---

def call_remediator(payload: dict):
    """Background task to call the remediator service."""
    try:
        requests.post(REMEDIATOR_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"Remediator call failed: {e}")


# --- Dashboard & New API Endpoints ---

@app.get("/dashboard", response_class=FileResponse)
async def get_dashboard():
    """Serves the main dashboard HTML file."""
    if not os.path.exists(dashboard_html_path):
        raise HTTPException(status_code=404, detail="dashboard.html not found. Please create it in the 'static' directory.")
    return FileResponse(dashboard_html_path)


@app.get("/metrics/live")
async def get_live_metrics():
    """Returns the 30 most recent cpu_usage metrics for the dashboard."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT name, value, ts FROM metrics WHERE name = 'cpu_usage' ORDER BY ts DESC LIMIT 30"
            ).fetchall()
            result = [dict(r) for r in rows]
            return {"metrics": result}
    except Exception as e:
        print(f"Live metrics DB read failed: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@app.get("/drift")
async def get_drift_actions():
    """Returns the 50 most recent drift-related ('reconcile') actions."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, target, action, status, details, started_at FROM actions WHERE action = 'reconcile' ORDER BY started_at DESC LIMIT 50"
            ).fetchall()
            result = [dict(r) for r in rows]
            return {"actions": result}
    except Exception as e:
        print(f"Drift actions DB read failed: {e}")
        raise HTTPException(status_code=500, detail="Database error")


# --- Existing Endpoints ---

@app.post("/ingest")
async def ingest(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
    except Exception:
        return {"error": "invalid JSON"}, 400

    name = data.get("name")
    value = data.get("value")
    if name is None or value is None:
        return {"error": "missing 'name' or 'value'"}, 400

    try:
        val_float = float(value)
        with get_db() as conn:
            conn.execute("INSERT INTO metrics (name, value) VALUES (?, ?)", (name, val_float))
            conn.commit()
    except (ValueError, TypeError):
        return {"error": f"invalid value type for: {value}"}, 400
    except Exception as e:
        print(f"DB write failed: {e}")
        return {"error": "db error"}, 500

    # --- Policy Evaluation ---
    try:
        triggered_actions = evaluate_policies(name, val_float)
        
        for action in triggered_actions:
            print(f"Policy triggered: {action['policy']} ({name} threshold) → {action['action']} on {action['target']}")
            payload = {
                "service": action["target"],
                "action": action["action"],
                "policy": action["policy"],
                "value": val_float
            }
            background_tasks.add_task(call_remediator, payload)
            
    except Exception as e:
        print(f"Policy evaluation failed: {e}")
    # --- End Policy Evaluation ---

    return {"ok": True}


@app.get("/query")
def query(limit: int = 10):
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT name, value, ts FROM metrics ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
            result = [dict(r) for r in rows]
            return {"metrics": result}
    except Exception as e:
        print(f"DB read failed: {e}")
        return {"error": "db error"}, 500


# --- Action Endpoints ---

class ActionRequest(BaseModel):
    """Pydantic model for validating a new action request."""
    target: str
    action: str
    status: str
    details: Optional[str | dict | list] = None


@app.post("/actions", status_code=201)
async def create_action(action: ActionRequest):
    """Logs a new action to the database."""
    try:
        details_str = json.dumps(action.details) if isinstance(action.details, (dict, list)) else action.details

        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO actions (target, action, status, details) VALUES (?, ?, ?, ?)",
                (action.target, action.action, action.status, details_str)
            )
            conn.commit()
            return {"ok": True, "id": cursor.lastrowid}
    except Exception as e:
        print(f"Action DB write failed: {e}")
        raise HTTPException(status_code=500, detail="Database error")


@app.get("/actions")
async def get_actions():
    """Returns the 50 most recent actions."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, target, action, status, details, started_at FROM actions ORDER BY id DESC LIMIT 50"
            ).fetchall()
            result = [dict(r) for r in rows]
            return {"actions": result}
    except Exception as e:
        print(f"Action DB read failed: {e}")
        raise HTTPException(status_code=500, detail="Database error")