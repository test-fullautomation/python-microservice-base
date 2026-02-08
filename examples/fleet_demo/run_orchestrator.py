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
# File: run_orchestrator.py
#
# Description:
#   Starts the FleetOrchestrator + FleetWebAPI.
#   This is the central coordinator that hub agents connect to.
#
# Prerequisites:
#   1. RabbitMQ running (default: localhost:5672)
#   2. pip install fastapi uvicorn
#   3. ProcessHub package on PYTHONPATH
#
# Usage:
#   python run_orchestrator.py
#   python run_orchestrator.py --rabbitmq-host 10.0.0.5 --web-port 2510
#
# *******************************************************************************
"""
Fleet Orchestrator.

Starts the FleetOrchestrator that receives hub agent heartbeats and
routes commands, plus the FleetWebAPI on port 2510 for the GUI's
Service Network tab.

Open http://localhost:2510 for the built-in fleet dashboard,
or connect from the MicroserviceManager GUI.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add ProcessHub to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "test" / "python-process-hub"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Fleet Orchestrator")
    parser.add_argument("--rabbitmq-host", default="localhost")
    parser.add_argument("--rabbitmq-port", type=int, default=5672)
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=2510)
    parser.add_argument("--health-timeout", type=float, default=30.0)
    args = parser.parse_args()

    from ProcessHub.transport import EventBusTransport, EventBusConfig
    from ProcessHub.fleet import FleetOrchestrator
    from ProcessHub.fleet.web_api import FleetWebAPI

    # Fleet transport — all hub agents and orchestrator share this exchange
    config = EventBusConfig(
        host=args.rabbitmq_host,
        port=args.rabbitmq_port,
        exchange_name="process_hub_fleet",
        routing_key_prefix="fleet",
        serializer="PickleSerializer",
        auto_reconnect=True,
    )
    fleet_transport = EventBusTransport(config=config)
    fleet_transport.start()

    orchestrator = FleetOrchestrator(
        transport=fleet_transport,
        health_timeout=args.health_timeout,
        tick_interval=5.0,
    )
    orchestrator.start()

    web_api = FleetWebAPI(
        orchestrator=orchestrator,
        host=args.web_host,
        port=args.web_port,
    )
    web_api.start()

    print()
    print("=" * 60)
    print("  Fleet Orchestrator")
    print("=" * 60)
    print()
    print(f"  RabbitMQ:        {args.rabbitmq_host}:{args.rabbitmq_port}")
    print(f"  Fleet Dashboard: http://{args.web_host}:{args.web_port}")
    print(f"  REST API:        http://{args.web_host}:{args.web_port}/api/fleet/status")
    print(f"  Health timeout:  {args.health_timeout}s")
    print()
    print("  Waiting for hub agents to connect...")
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()

    try:
        while True:
            orchestrator.tick()
            snapshot = orchestrator.get_fleet_snapshot()
            if snapshot.total_hubs > 0:
                logger.info(
                    "Fleet: %d hubs (%d online), %d processes",
                    snapshot.total_hubs,
                    snapshot.online_hubs,
                    snapshot.total_processes,
                )
            time.sleep(5)
    except KeyboardInterrupt:
        pass

    print("\nShutting down...")
    web_api.stop()
    orchestrator.stop()
    fleet_transport.stop()
    print("Orchestrator stopped.")


if __name__ == "__main__":
    main()
