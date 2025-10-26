from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Optional
import sqlite3
import os
import requests
import json
import yaml
from dotenv import load_dotenv

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


def init_db():
    """Initializes the database and creates tables if they don't exist."""
    # Ensure the directory for the DB exists
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        print(f"Created database directory: {db_dir}")

    with sqlite3.connect(DB_PATH) as conn:
        # Existing metrics table
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
        # New actions table
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


# Initialize DB on startup
init_db()


def call_remediator(payload: dict):
    """Background task to call the remediator service."""
    try:
        requests.post(REMEDIATOR_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"Remediator call failed: {e}")


# --- Existing Endpoints (Unchanged) ---

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
        with get_db() as conn:
            conn.execute("INSERT INTO metrics (name, value) VALUES (?, ?)", (name, float(value)))
            conn.commit()
    except Exception as e:
        print(f"DB write failed: {e}")
        return {"error": "db error"}, 500

    # Alert condition
    if name == "cpu_usage":
        try:
            v = float(value)
            if v > 0.8:
                print(f"HIGH_CPU: {v:.2f} → scheduling remediation")
                background_tasks.add_task(call_remediator, {"service": "backend", "reason": "high_cpu", "value": v})
        except Exception:
            pass  # Fail silently if value conversion fails

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


# --- New Action Endpoints ---

class ActionRequest(BaseModel):
    """Pydantic model for validating a new action request."""
    target: str
    action: str
    status: str
    details: Optional[str] = None


@app.post("/actions", status_code=201)
async def create_action(action: ActionRequest):
    """Logs a new action to the database."""
    try:
        with get_db() as conn:
            cursor = conn.execute(
                "INSERT INTO actions (target, action, status, details) VALUES (?, ?, ?, ?)",
                (action.target, action.action, action.status, action.details)
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

