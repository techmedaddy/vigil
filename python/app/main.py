from fastapi import FastAPI, Request, BackgroundTasks
import sqlite3
import os
import requests
import json

DB_PATH = os.getenv("DB_PATH", "vigil.db")
REMediator_URL = os.getenv("REMediator_URL", "http://127.0.0.1:8081/remediate")

app = FastAPI(title="Vigil Collector")


def init_db():
    if not os.path.exists(DB_PATH):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    ts DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


init_db()


def call_remediator(payload: dict):
    try:
        requests.post(REMediator_URL, json=payload, timeout=5)
    except Exception as e:
        # keep this simple; in real code use structured logging
        print("Remediator call failed:", e)


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
        print("DB write failed:", e)
        return {"error": "db error"}, 500

    # alert condition
    if name == "cpu_usage":
        try:
            v = float(value)
            if v > 0.8:
                print(f"HIGH_CPU: {v:.2f} → scheduling remediation")
                background_tasks.add_task(call_remediator, {"service": "backend", "reason": "high_cpu", "value": v})
        except Exception:
            pass

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
        print("DB read failed:", e)
        return {"error": "db error"}, 500
