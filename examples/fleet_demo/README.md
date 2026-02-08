# Fleet Demo — Calculator & Cleware via Service Network

Real fleet example with two microservice processes managed through the
MicroserviceManager GUI's **Service Network** tab.

## Architecture

```
Terminal 1                    Terminal 2                    GUI
┌──────────────────┐    ┌──────────────────────────┐    ┌──────────────────┐
│  Orchestrator    │    │  Hub Agent               │    │ Microservice     │
│  + FleetWebAPI   │◄──►│  + ProcessHub Server     │    │ Manager GUI      │
│  (port 2510)     │    │    ├─ Calculator          │    │ Service Network  │
│                  │    │    └─ ServiceCleware      │    │ tab              │
└────────┬─────────┘    └──────────┬───────────────┘    └────────┬─────────┘
         │                         │                             │
         └─────────RabbitMQ (5672)─┘                             │
                        │                                        │
                        └── Fleet API (http://localhost:2510) ───┘
```

## Prerequisites

1. **RabbitMQ** running on localhost:5672
   ```
   docker run -d -p 5672:5672 -p 15672:15672 rabbitmq:management
   ```

2. **Python packages** on PYTHONPATH:
   - `MicroserviceBase` (this repo)
   - `ProcessHub` (python-process-hub)
   - `MicroserviceClewareSwitch` (for Cleware process)
   - `EventBusClient` (python-rabbitmq-messagebus)

3. **pip dependencies**:
   ```
   pip install fastapi uvicorn
   ```

## Quick Start

### Terminal 1 — Start Orchestrator

```bash
cd examples/fleet_demo
python run_orchestrator.py
```

This starts:
- FleetOrchestrator listening for hub agents via RabbitMQ
- FleetWebAPI on http://localhost:2510 (REST API + dashboard)

### Terminal 2 — Start Hub Agent

```bash
cd examples/fleet_demo
python run_hub_agent.py --hub-id bench-1 --hub-name "HIL Bench 1"
```

This starts:
- ProcessHub server with Calculator and ServiceCleware process definitions
- HubAgent that announces to the orchestrator

The processes are **not started automatically** — they are registered as
available and can be started from the GUI or API.

### GUI — Connect to Fleet

1. Open MicroserviceManager (Electron or browser at http://localhost:1112/gui/)
2. Click the **Service Network** tab
3. Enter Fleet API URL: `http://localhost:2510`
4. The dashboard shows "HIL Bench 1" with its processes
5. Click the hub → see Calculator and ServiceCleware
6. Click **Start All** to launch both processes
7. Processes register with RabbitMQ and appear in the **Services** tab too

## Multiple Hubs

Run additional hub agents on different machines or terminals:

```bash
# Terminal 3
python run_hub_agent.py --hub-id bench-2 --hub-name "HIL Bench 2"

# Terminal 4 (remote machine)
python run_hub_agent.py --hub-id lab-pc --hub-name "Lab PC" --rabbitmq-host 10.0.0.5
```

## REST API

```bash
# Fleet status
curl http://localhost:2510/api/fleet/status

# List hubs
curl http://localhost:2510/api/fleet/hubs

# Start Calculator on bench-1
curl -X POST http://localhost:2510/api/fleet/hubs/bench-1/start \
     -H "Content-Type: application/json" \
     -d '{"process_list": ["Calculator"]}'

# Stop all processes on bench-1
curl -X POST http://localhost:2510/api/fleet/hubs/bench-1/stop \
     -H "Content-Type: application/json" \
     -d '{"process_list": ["Calculator", "ServiceCleware"]}'

# Reset hub
curl -X POST http://localhost:2510/api/fleet/hubs/bench-1/reset
```

## Files

| File | Purpose |
|------|---------|
| `run_orchestrator.py` | FleetOrchestrator + FleetWebAPI (central coordinator) |
| `run_hub_agent.py` | ProcessHub server + HubAgent (runs on each machine) |
| `process_config.json` | Reference process configuration (JSON format) |
