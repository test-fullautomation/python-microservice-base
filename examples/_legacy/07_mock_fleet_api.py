#  Copyright 2020-2025 Robert Bosch GmbH
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# *******************************************************************************
#
# File: 07_mock_fleet_api.py
#
# Description:
#   Mock FleetWebAPI server that simulates a fleet of ProcessHub instances.
#   Provides realistic, dynamic data for demonstrating the Service Network tab
#   in the MicroserviceManager GUI without requiring the actual ProcessHub fleet
#   infrastructure.
#
# Prerequisites:
#   pip install fastapi uvicorn
#
# Usage:
#   python 07_mock_fleet_api.py [--port 2510]
#
# Then in the GUI, set Fleet API URL to http://localhost:2510
#
# Features:
#   - 4 simulated hubs with varying statuses
#   - Processes appear/disappear over time (simulating real activity)
#   - Start/stop/reset commands are accepted and affect hub state
#   - Hub health degrades and recovers dynamically
#
# *******************************************************************************
"""
Mock FleetWebAPI Server.

Simulates a fleet orchestrator with multiple hubs for GUI development and
demonstration purposes.  Each hub has a set of processes that can be started
and stopped via the API, and hub health status changes over time.

Endpoints (matching the real FleetWebAPI contract):
    GET  /api/fleet/status          - Full fleet snapshot
    GET  /api/fleet/hubs            - Hub list
    GET  /api/fleet/hubs/{hub_id}   - Single hub detail
    POST /api/fleet/hubs/{hub_id}/start  - Start processes
    POST /api/fleet/hubs/{hub_id}/stop   - Stop processes
    POST /api/fleet/hubs/{hub_id}/reset  - Reset hub
    POST /api/fleet/command         - Raw fleet command
    GET  /                          - Simple status page
"""

import argparse
import random
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Optional

# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

def _mock_process_configs(process_names):
    """Generate mock process configs for given process names."""
    configs = {}
    for name in process_names:
        configs[name] = {
            "process_name": name,
            "script": "python",
            "args": ["-m", name, "--host", "localhost", "--port", "5672"],
            "wait_time": 2.0,
            "description": f"Mock {name} microservice",
            "env": {"PYTHONPATH": "/opt/services", "LOG_LEVEL": "INFO"},
        }
    return configs


MOCK_HUBS = {
    "hub-alpha-001": {
        "hub_id": "hub-alpha-001",
        "hub_name": "AlphaHub",
        "host": "192.168.1.10",
        "status": "online",
        "all_processes": [
            "DataCollector", "SignalProcessor", "LogAggregator",
            "MetricsExporter", "HealthMonitor"
        ],
        "running_processes": [
            "DataCollector", "SignalProcessor", "LogAggregator",
            "MetricsExporter", "HealthMonitor"
        ],
        "connections": ["rabbitmq:5672", "redis:6379", "postgres:5432"],
        "last_seen": 0.0,
        "version": "2.1.0",
    },
    "hub-beta-002": {
        "hub_id": "hub-beta-002",
        "hub_name": "BetaHub",
        "host": "192.168.1.20",
        "status": "online",
        "all_processes": [
            "TestRunner", "ReportGenerator", "NotificationService"
        ],
        "running_processes": [
            "TestRunner", "ReportGenerator", "NotificationService"
        ],
        "connections": ["rabbitmq:5672", "smtp:587"],
        "last_seen": 0.0,
        "version": "2.1.0",
    },
    "hub-gamma-003": {
        "hub_id": "hub-gamma-003",
        "hub_name": "GammaHub",
        "host": "192.168.1.30",
        "status": "degraded",
        "all_processes": [
            "ImageProcessor", "ThumbnailGen", "StorageSync",
            "CacheWarmer", "APIGateway", "AuthService",
            "RateLimiter"
        ],
        "running_processes": [
            "ImageProcessor", "StorageSync", "APIGateway", "AuthService"
        ],
        "connections": ["rabbitmq:5672", "minio:9000"],
        "last_seen": 0.0,
        "version": "2.0.3",
    },
    "hub-delta-004": {
        "hub_id": "hub-delta-004",
        "hub_name": "DeltaHub",
        "host": "192.168.1.40",
        "status": "offline",
        "all_processes": [
            "BackupAgent", "SnapshotService"
        ],
        "running_processes": [],
        "connections": [],
        "last_seen": 0.0,
        "version": "1.9.5",
    },
}

# Generate process configs for each mock hub
for _hub in MOCK_HUBS.values():
    _hub["process_configs"] = _mock_process_configs(_hub["all_processes"])

_lock = threading.Lock()
_command_log = []


def _hub_snapshot(hub):
    """Create an API-compatible snapshot dict for a hub."""
    return {
        "hub_id": hub["hub_id"],
        "hub_name": hub["hub_name"],
        "host": hub["host"],
        "status": hub["status"],
        "process_count": len(hub["running_processes"]),
        "connection_count": len(hub["connections"]),
        "processes": list(hub["running_processes"]),
        "connections": list(hub["connections"]),
        "configured_processes": list(hub["all_processes"]),
        "process_configs": hub.get("process_configs", {}),
        "last_seen": hub["last_seen"],
        "version": hub["version"],
    }


def _fleet_snapshot():
    """Create a full fleet status snapshot."""
    hubs = []
    online = 0
    total_procs = 0
    for hub in MOCK_HUBS.values():
        snap = _hub_snapshot(hub)
        hubs.append(snap)
        if hub["status"] in ("online", "degraded"):
            online += 1
        total_procs += snap["process_count"]
    return {
        "total_hubs": len(hubs),
        "online_hubs": online,
        "total_processes": total_procs,
        "timestamp": time.time(),
        "hubs": hubs,
    }


# ---------------------------------------------------------------------------
# Background simulation thread
# ---------------------------------------------------------------------------

def _simulation_loop():
    """
    Periodically mutate hub state to make the demo feel alive.
    - Updates last_seen timestamps
    - Occasionally toggles processes on/off
    - Occasionally changes hub status
    """
    while True:
        time.sleep(5)
        with _lock:
            for hub in MOCK_HUBS.values():
                if hub["status"] == "offline":
                    # Offline hubs may come back online sometimes
                    if random.random() < 0.05:
                        hub["status"] = "online"
                        hub["running_processes"] = list(hub["all_processes"])
                        hub["connections"] = ["rabbitmq:5672"]
                        hub["last_seen"] = time.time()
                        print(f" [~] {hub['hub_name']} came back online")
                    continue

                hub["last_seen"] = time.time()

                # Small chance a process stops or starts
                if random.random() < 0.1 and len(hub["running_processes"]) > 1:
                    proc = random.choice(hub["running_processes"])
                    hub["running_processes"].remove(proc)
                    print(f" [~] {hub['hub_name']}: {proc} stopped (simulated)")
                elif random.random() < 0.1:
                    stopped = [p for p in hub["all_processes"]
                               if p not in hub["running_processes"]]
                    if stopped:
                        proc = random.choice(stopped)
                        hub["running_processes"].append(proc)
                        print(f" [~] {hub['hub_name']}: {proc} started (simulated)")

                # Recalculate status
                ratio = (len(hub["running_processes"]) /
                         max(len(hub["all_processes"]), 1))
                if ratio >= 0.8:
                    hub["status"] = "online"
                elif ratio > 0:
                    hub["status"] = "degraded"
                else:
                    hub["status"] = "offline"

                # Very rare: hub goes offline entirely
                if random.random() < 0.02:
                    hub["status"] = "offline"
                    hub["running_processes"] = []
                    hub["connections"] = []
                    print(f" [~] {hub['hub_name']} went offline (simulated)")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Mock FleetWebAPI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProcessActionRequest(BaseModel):
    process_list: List[str]
    panel_id: str = "fleet"
    force: bool = False


class CommandRequest(BaseModel):
    hub_id: str
    action: str
    params: dict = {}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    with _lock:
        snap = _fleet_snapshot()
    rows = ""
    for h in snap["hubs"]:
        color = {"online": "#2ecc71", "degraded": "#f1c40f",
                 "offline": "#e74c3c"}.get(h["status"], "#ccc")
        rows += (
            f'<tr>'
            f'<td>{h["hub_name"]}</td>'
            f'<td><code>{h["hub_id"]}</code></td>'
            f'<td>{h["host"]}</td>'
            f'<td><span style="color:{color};font-weight:bold">'
            f'{h["status"].upper()}</span></td>'
            f'<td>{h["process_count"]}</td>'
            f'<td>{", ".join(h["processes"][:3])}{"..." if len(h["processes"]) > 3 else ""}</td>'
            f'</tr>'
        )
    return f"""
    <html><head><title>Mock FleetWebAPI</title>
    <style>
        body {{ font-family: sans-serif; padding: 2rem; background: #f8f9fa; }}
        h1 {{ color: #2c3e50; }}
        table {{ border-collapse: collapse; width: 100%; background: #fff;
                 border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
        th, td {{ padding: 0.6rem 1rem; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #2c3e50; color: #fff; font-size: 0.85rem; }}
        .stats {{ display: flex; gap: 1rem; margin-bottom: 1.5rem; }}
        .stat {{ background: #fff; padding: 1rem 1.5rem; border-radius: 8px;
                 box-shadow: 0 1px 3px rgba(0,0,0,.08); text-align: center; }}
        .stat-val {{ font-size: 2rem; font-weight: 700; color: #2c3e50; }}
        .stat-lbl {{ font-size: 0.8rem; color: #95a5a6; text-transform: uppercase; }}
        code {{ font-size: 0.8rem; }}
        .api-links {{ margin-top: 1.5rem; }}
        .api-links a {{ display: inline-block; margin-right: 1rem; color: #3498db; }}
    </style>
    <meta http-equiv="refresh" content="5">
    </head><body>
    <h1>Mock FleetWebAPI</h1>
    <div class="stats">
        <div class="stat"><div class="stat-val">{snap['total_hubs']}</div><div class="stat-lbl">Total Hubs</div></div>
        <div class="stat"><div class="stat-val">{snap['online_hubs']}</div><div class="stat-lbl">Online</div></div>
        <div class="stat"><div class="stat-val">{snap['total_processes']}</div><div class="stat-lbl">Processes</div></div>
    </div>
    <table>
        <tr><th>Name</th><th>Hub ID</th><th>Host</th><th>Status</th><th>Processes</th><th>Running</th></tr>
        {rows}
    </table>
    <div class="api-links">
        <strong>API:</strong>
        <a href="/api/fleet/status">/api/fleet/status</a>
        <a href="/api/fleet/hubs">/api/fleet/hubs</a>
        <a href="/docs">/docs (Swagger)</a>
    </div>
    <p style="color:#95a5a6;font-size:0.8rem;margin-top:1rem">
        Auto-refreshes every 5 seconds. Hub states change dynamically.
    </p>
    </body></html>
    """


@app.get("/api/fleet/status")
def fleet_status():
    with _lock:
        return _fleet_snapshot()


@app.get("/api/fleet/hubs")
def fleet_hubs():
    with _lock:
        hubs = [_hub_snapshot(h) for h in MOCK_HUBS.values()]
        return {"total": len(hubs), "hubs": hubs}


@app.get("/api/fleet/hubs/{hub_id}")
def fleet_hub_detail(hub_id: str):
    with _lock:
        hub = MOCK_HUBS.get(hub_id)
        if not hub:
            raise HTTPException(status_code=404,
                                detail=f"Hub not found: {hub_id}")
        return _hub_snapshot(hub)


@app.post("/api/fleet/hubs/{hub_id}/start")
def fleet_hub_start(hub_id: str, body: ProcessActionRequest):
    with _lock:
        hub = MOCK_HUBS.get(hub_id)
        if not hub:
            raise HTTPException(status_code=400, detail="Hub not found")
        if hub["status"] == "offline":
            # Bring hub online when start is requested
            hub["status"] = "online"
            hub["connections"] = ["rabbitmq:5672"]
            hub["last_seen"] = time.time()
        for proc in body.process_list:
            if proc in hub["all_processes"] and proc not in hub["running_processes"]:
                hub["running_processes"].append(proc)
                print(f" [>] Started {proc} on {hub['hub_name']}")
        # Recalculate status
        ratio = len(hub["running_processes"]) / max(len(hub["all_processes"]), 1)
        hub["status"] = "online" if ratio >= 0.8 else "degraded"
        hub["last_seen"] = time.time()
        cmd_id = str(uuid.uuid4())[:8]
        _command_log.append({"id": cmd_id, "hub": hub_id, "action": "start"})
        return {"command_id": cmd_id, "hub_id": hub_id, "action": "start_process"}


@app.post("/api/fleet/hubs/{hub_id}/stop")
def fleet_hub_stop(hub_id: str, body: ProcessActionRequest):
    with _lock:
        hub = MOCK_HUBS.get(hub_id)
        if not hub:
            raise HTTPException(status_code=400, detail="Hub not found")
        for proc in body.process_list:
            if proc in hub["running_processes"]:
                hub["running_processes"].remove(proc)
                print(f" [>] Stopped {proc} on {hub['hub_name']}")
        # Recalculate status
        if len(hub["running_processes"]) == 0:
            hub["status"] = "offline"
            hub["connections"] = []
        else:
            ratio = len(hub["running_processes"]) / max(len(hub["all_processes"]), 1)
            hub["status"] = "online" if ratio >= 0.8 else "degraded"
        hub["last_seen"] = time.time()
        cmd_id = str(uuid.uuid4())[:8]
        _command_log.append({"id": cmd_id, "hub": hub_id, "action": "stop"})
        return {"command_id": cmd_id, "hub_id": hub_id, "action": "stop_process"}


@app.post("/api/fleet/hubs/{hub_id}/reset")
def fleet_hub_reset(hub_id: str):
    with _lock:
        hub = MOCK_HUBS.get(hub_id)
        if not hub:
            raise HTTPException(status_code=400, detail="Hub not found")
        hub["running_processes"] = list(hub["all_processes"])
        hub["connections"] = ["rabbitmq:5672"]
        hub["status"] = "online"
        hub["last_seen"] = time.time()
        print(f" [>] Reset {hub['hub_name']} — all processes restored")
        cmd_id = str(uuid.uuid4())[:8]
        _command_log.append({"id": cmd_id, "hub": hub_id, "action": "reset"})
        return {"command_id": cmd_id, "hub_id": hub_id, "action": "reset"}


@app.post("/api/fleet/command")
def fleet_command(body: CommandRequest):
    with _lock:
        hub = MOCK_HUBS.get(body.hub_id)
        if not hub:
            raise HTTPException(status_code=400, detail="Hub not found")
        cmd_id = str(uuid.uuid4())[:8]
        _command_log.append({
            "id": cmd_id, "hub": body.hub_id,
            "action": body.action, "params": body.params
        })
        print(f" [>] Command '{body.action}' -> {hub['hub_name']}: {body.params}")
        return {"command_id": cmd_id, "hub_id": body.hub_id, "action": body.action}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Mock FleetWebAPI server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=2510, help="Bind port")
    args = parser.parse_args()

    # Initialize timestamps
    now = time.time()
    for hub in MOCK_HUBS.values():
        hub["last_seen"] = now - random.uniform(0, 30)

    # Start background simulation
    sim_thread = threading.Thread(target=_simulation_loop, daemon=True)
    sim_thread.start()

    print(f" [*] Mock FleetWebAPI starting on http://{args.host}:{args.port}")
    print(f" [*] Dashboard:  http://{args.host}:{args.port}/")
    print(f" [*] Fleet API:  http://{args.host}:{args.port}/api/fleet/status")
    print(f" [*] Swagger:    http://{args.host}:{args.port}/docs")
    print(f" [*] Hubs: {', '.join(h['hub_name'] for h in MOCK_HUBS.values())}")
    print(f" [*] Hub states change dynamically every ~5 seconds")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
