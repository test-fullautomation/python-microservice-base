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
# File: 08_fleet_demo.py
#
# Description:
#   All-in-one demo that starts the mock FleetWebAPI and a standalone FastAPI
#   server serving the MicroserviceManager GUI, then opens the browser.
#
#   This lets you explore the Service Network tab without RabbitMQ or any
#   real services — the mock fleet provides dynamic hub data.
#
# Prerequisites:
#   pip install fastapi uvicorn httpx
#
# Usage:
#   python 08_fleet_demo.py
#
# What it does:
#   1. Starts mock FleetWebAPI on port 2510  (simulated fleet)
#   2. Starts a minimal FastAPI server on port 1112 serving:
#      - The MicroserviceManager GUI at /gui/
#      - Fleet proxy endpoints at /api/fleet/*
#   3. Auto-configures the fleet URL
#   4. Opens the browser to http://localhost:1112/gui/
#
# Demo walkthrough:
#   1. The GUI opens in your browser
#   2. Click the "Service Network" tab in the navbar
#   3. The fleet dashboard shows 4 simulated hubs with live status
#   4. Click a hub card or sidebar item to see process details
#   5. Use Start All / Stop All / Reset buttons to control hubs
#   6. Watch hub states change dynamically every ~5 seconds
#   7. Switch back to "Services" tab — it remains intact
#
# *******************************************************************************
"""
Fleet Demo — All-in-one launcher.

Starts both the mock FleetWebAPI and a GUI server so you can demo the
Service Network tab in a single command with zero infrastructure.
"""

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Add MicroserviceBase to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))


def start_mock_fleet(port=2510):
    """Start the mock FleetWebAPI in a background thread."""
    import uvicorn

    # Import the mock fleet app from sibling example
    examples_dir = Path(__file__).parent
    sys.path.insert(0, str(examples_dir))

    # We import after adding to path
    from importlib import import_module
    mock_module = import_module("07_mock_fleet_api")

    # Initialize timestamps
    import random
    now = time.time()
    for hub in mock_module.MOCK_HUBS.values():
        hub["last_seen"] = now - random.uniform(0, 30)

    # Start simulation
    sim = threading.Thread(target=mock_module._simulation_loop, daemon=True)
    sim.start()

    # Run fleet API server
    config = uvicorn.Config(
        mock_module.app, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    server.run()


def start_gui_server(port=1112, fleet_port=2510):
    """Start a minimal FastAPI server that serves the GUI + fleet proxy."""
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel
    from typing import List, Optional

    app = FastAPI(title="Fleet Demo Server")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    fleet_api_url = f"http://127.0.0.1:{fleet_port}"

    class ProcessActionBody(BaseModel):
        process_list: List[str]
        panel_id: str = "fleet"
        force: bool = False

    class FleetCommandBody(BaseModel):
        hub_id: str
        action: str
        params: Optional[dict] = {}

    # ---- Fleet proxy (same contract as fastapi_bridge.py) ----

    def _fleet_proxy(method, path, json_body=None):
        import httpx
        from fastapi.responses import JSONResponse

        url = fleet_api_url + path
        try:
            with httpx.Client(timeout=10.0) as client:
                if method == "GET":
                    resp = client.get(url)
                else:
                    resp = client.post(url, json=json_body)
            return JSONResponse(status_code=resp.status_code, content=resp.json())
        except Exception as exc:
            return JSONResponse(
                status_code=502,
                content={"error": f"Fleet API unreachable: {exc}"},
            )

    @app.get("/api/fleet/config")
    def get_fleet_config():
        return {"fleet_api_url": fleet_api_url}

    @app.post("/api/fleet/config")
    def set_fleet_config():
        return {"fleet_api_url": fleet_api_url}

    @app.get("/api/fleet/status")
    def fleet_status():
        return _fleet_proxy("GET", "/api/fleet/status")

    @app.get("/api/fleet/hubs")
    def fleet_hubs():
        return _fleet_proxy("GET", "/api/fleet/hubs")

    @app.get("/api/fleet/hubs/{hub_id}")
    def fleet_hub_detail(hub_id: str):
        return _fleet_proxy("GET", f"/api/fleet/hubs/{hub_id}")

    @app.post("/api/fleet/hubs/{hub_id}/start")
    def fleet_hub_start(hub_id: str, body: ProcessActionBody):
        return _fleet_proxy("POST", f"/api/fleet/hubs/{hub_id}/start",
                            body.model_dump())

    @app.post("/api/fleet/hubs/{hub_id}/stop")
    def fleet_hub_stop(hub_id: str, body: ProcessActionBody):
        return _fleet_proxy("POST", f"/api/fleet/hubs/{hub_id}/stop",
                            body.model_dump())

    @app.post("/api/fleet/hubs/{hub_id}/reset")
    def fleet_hub_reset(hub_id: str):
        return _fleet_proxy("POST", f"/api/fleet/hubs/{hub_id}/reset")

    @app.post("/api/fleet/command")
    def fleet_command(body: FleetCommandBody):
        return _fleet_proxy("POST", "/api/fleet/command", body.model_dump())

    # Stub for /api/request (services tab won't work in this demo, but
    # prevents JS console errors)
    @app.post("/api/request")
    def stub_request():
        return {"request": "", "result": "exception",
                "result_data": "No broker connected in demo mode"}

    @app.get("/api/services")
    def stub_services():
        return {}

    # Mount GUI static files
    gui_path = os.path.join(
        os.path.dirname(__file__), '..', 'MicroserviceBase',
        'MicroserviceManagerGUI', 'web'
    )
    gui_path = os.path.abspath(gui_path)
    if os.path.isdir(gui_path):
        app.mount("/gui", StaticFiles(directory=gui_path, html=True), name="gui")
    else:
        print(f" [!] GUI directory not found: {gui_path}")
        return

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    server.run()


def main():
    fleet_port = 2510
    gui_port = 1112

    print("=" * 60)
    print("  Fleet Demo — Service Network Tab")
    print("=" * 60)
    print()
    print(f"  Mock FleetWebAPI:  http://localhost:{fleet_port}")
    print(f"  GUI Server:        http://localhost:{gui_port}")
    print(f"  Open in browser:   http://localhost:{gui_port}/gui/")
    print()
    print("  Demo steps:")
    print("  1. Click 'Service Network' tab in the navbar")
    print("  2. Dashboard shows 4 hubs with live status")
    print("  3. Click a hub to see process details")
    print("  4. Use Start/Stop/Reset to control hubs")
    print("  5. Watch states change every ~5 seconds")
    print()
    print("  Press CTRL+C to stop.")
    print("=" * 60)
    print()

    # Start mock fleet in background
    fleet_thread = threading.Thread(
        target=start_mock_fleet,
        args=(fleet_port,),
        daemon=True,
    )
    fleet_thread.start()

    # Wait a moment for fleet to be ready
    time.sleep(1)

    # Open browser after a short delay
    def _open_browser():
        time.sleep(2)
        url = f"http://localhost:{gui_port}/gui/"
        print(f" [*] Opening browser: {url}")
        webbrowser.open(url)

    browser_thread = threading.Thread(target=_open_browser, daemon=True)
    browser_thread.start()

    # Start GUI server (blocks)
    try:
        start_gui_server(gui_port, fleet_port)
    except KeyboardInterrupt:
        print("\n [*] Shutting down...")


if __name__ == "__main__":
    main()
