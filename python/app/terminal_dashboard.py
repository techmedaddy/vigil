import requests
import time
import json
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from typing import List, Dict, Any

# --- API Configuration ---
BASE_URL = "http://127.0.0.1:8000"
METRICS_URL = f"{BASE_URL}/metrics/live"
DRIFT_URL = f"{BASE_URL}/drift"
ACTIONS_URL = f"{BASE_URL}/actions"

# --- Global State ---
app_data = {
    "metrics": [],
    "drift": [],
    "actions": [],
    "offline": False
}

# --- Data Fetching ---
def fetch_data():
    """Fetches all data from the FastAPI backend."""
    try:
        # Use a short timeout to keep the UI responsive
        timeout = 0.5
        metrics_resp = requests.get(METRICS_URL, timeout=timeout)
        drift_resp = requests.get(DRIFT_URL, timeout=timeout)
        actions_resp = requests.get(ACTIONS_URL, timeout=timeout)

        # Check for errors
        metrics_resp.raise_for_status()
        drift_resp.raise_for_status()
        actions_resp.raise_for_status()

        # Update global state
        app_data["metrics"] = metrics_resp.json().get("metrics", [])
        app_data["drift"] = drift_resp.json().get("actions", [])
        app_data["actions"] = actions_resp.json().get("actions", [])
        app_data["offline"] = False

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.HTTPError):
        app_data["offline"] = True
    except Exception:
        # Catch other potential errors (e.g., JSON decode)
        app_data["offline"] = True

# --- UI Rendering ---

def make_layout() -> Layout:
    """Defines the dashboard layout."""
    layout = Layout(name="root")
    layout.split(
        Layout(name="header", size=7),  # CPU graph
        Layout(name="middle", ratio=1), # Drift table
        Layout(name="footer", ratio=1)  # Actions table
    )
    return layout

def render_cpu_panel() -> Panel:
    """Renders the CPU usage sparkline graph."""
    
    # Sparkline characters from ' ' to '█'
    spark_chars = " ▂▃▄▅▆▇█"
    
    # API returns last 30, newest first. Reverse for time-series.
    values = [m.get("value", 0) for m in app_data["metrics"]][::-1]
    
    spark_line = ""
    if values:
        # Scale based on 0-100 (as simulate_failures.py sends 0-100)
        max_val = 100.0 
        for v in values:
            idx = int((v / max_val) * (len(spark_chars) - 1))
            if idx >= len(spark_chars): idx = len(spark_chars) - 1
            if idx < 0: idx = 0
            spark_line += spark_chars[idx]
    else:
        spark_line = "Fetching metrics..."

    content = Text(f"\n{spark_line}\n", justify="center")
    return Panel(content, title="[b]CPU Usage (Last 30)", border_style="blue")

def render_drift_panel() -> Panel:
    """Renders the drift events table."""
    table = Table(expand=True)
    table.add_column("ID", style="dim", width=5)
    table.add_column("Target", style="cyan", width=20)
    table.add_column("Status", width=10)
    table.add_column("Details", width=35)
    table.add_column("Timestamp", style="magenta")

    # API returns 50 most recent
    for event in app_data["drift"]:
        status = event.get('status', '')
        
        # Highlighting logic: Red if not pending (as per prompt)
        row_style = ""
        status_style = ""
        
        if status != "pending":
            row_style = "bold red"
            status_style = "bold red"
        else:
            status_style = "yellow"
        
        # Clean up details field
        details_str = event.get('details', 'N/A')
        details_text = details_str
        if isinstance(details_str, str):
            try:
                # Try to parse if it's a JSON string
                details_json = json.loads(details_str)
                if isinstance(details_json, dict):
                     details_text = details_json.get('reason', f"Policy: {details_json.get('policy')}")
            except json.JSONDecodeError:
                pass # Keep as string
        
        if len(details_text) > 35:
            details_text = details_text[:32] + "..."

        table.add_row(
            str(event.get('id', '')),
            event.get('target', ''),
            Text(status, style=status_style),
            details_text,
            event.get('started_at', ''),
            style=row_style
        )
    
    return Panel(table, title="[b]Drift Events (action='reconcile')", border_style="red")

def render_actions_panel() -> Panel:
    """Renders the action log table."""
    table = Table(expand=True)
    table.add_column("Target", style="cyan", width=20)
    table.add_column("Action", width=15)
    table.add_column("Status", width=10)
    table.add_column("Timestamp", style="magenta")

    # Show last 10 actions from the API's list of 50
    for action in app_data["actions"][:10]:
        status = action.get('status', '')
        style = ""
        if status == "success":
            style = "green"
        elif status == "blocked":
            style = "bold red"
        elif status == "pending":
            style = "yellow"
        elif status == "failed":
            style = "red"

        table.add_row(
            action.get('target', ''),
            action.get('action', ''),
            Text(status, style=style),
            action.get('started_at', '')
        )
    
    return Panel(table, title="[b]Remediator Action Log (Last 10)", border_style="green")

def generate_dashboard() -> Layout:
    """Connects all the render functions to the layout."""
    
    # Show error panel if backend is down
    if app_data["offline"]:
        return Panel(
            Text("BACKEND OFFLINE. ATTEMPTING TO RECONNECT...", style="bold red", justify="center"),
            title="[b red]CONNECTION ERROR",
            border_style="bold red",
            expand=True
        )

    # Build the main layout
    layout = make_layout()
    layout["header"].update(render_cpu_panel())
    layout["middle"].update(render_drift_panel())
    layout["footer"].update(render_actions_panel())
    return layout

# --- Main Loop ---
def main():
    """Runs the main application loop."""
    # Fetch initial data before starting Live
    fetch_data()
    
    # Use screen=True to take over the terminal
    with Live(generate_dashboard(), refresh_per_second=4, screen=True, vertical_overflow="visible") as live:
        while True:
            try:
                # Data fetch rate
                time.sleep(1) 
                fetch_data()
                
                # Update the display
                live.update(generate_dashboard())
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                # This catches errors in the dashboard code itself
                error_panel = Panel(
                    Text(f"An unexpected dashboard error occurred:\n{e}", style="bold red", justify="center"),
                    title="[b red]DASHBOARD CRITICAL ERROR",
                    border_style="bold red"
                )
                live.update(error_panel)
                time.sleep(5) # Pause to show error

if __name__ == "__main__":
    main()