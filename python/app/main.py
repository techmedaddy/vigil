from fastapi import FastAPI, Request
import sqlite3, os

DB_PATH = "vigil.db"
app = FastAPI(title="Vigil Collector")

# ensure database exists
def init_db():
    if not os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
        CREATE TABLE metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            value REAL,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
        conn.close()

init_db()

@app.post("/ingest")
async def ingest(request: Request):
    data = await request.json()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO metrics (name, value) VALUES (?, ?)", (data["name"], data["value"]))
    conn.commit()
    conn.close()
    print("Metric stored:", data)
    return {"ok": True}

@app.get("/query")
def query():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT name, value, ts FROM metrics ORDER BY ts DESC LIMIT 10").fetchall()
    conn.close()
    return {"metrics": rows}
