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
# File: run_hub_agent.py
#
# Description:
#   Starts a ProcessHub server with Calculator and ServiceCleware processes,
#   then attaches a HubAgent that announces to the FleetOrchestrator.
#
#   The orchestrator (and the MicroserviceManager GUI's Service Network tab)
#   can then start/stop these processes remotely.
#
# Prerequisites:
#   1. RabbitMQ running (default: localhost:5672)
#   2. run_orchestrator.py running (fleet orchestrator)
#   3. ProcessHub package on PYTHONPATH
#   4. MicroserviceBase package on PYTHONPATH
#   5. MicroserviceClewareSwitch package on PYTHONPATH (for Cleware process)
#
# Usage:
#   python run_hub_agent.py --hub-id my-bench --hub-name "My Test Bench"
#
# *******************************************************************************
"""
Hub Agent with Calculator and Cleware processes.

Starts a ProcessHub server that manages two microservice processes:
  - Calculator:      01_basic_service.py (arithmetic service)
  - ServiceCleware:  python -m MicroserviceClewareSwitch (USB switch service)

A HubAgent sidecar connects to the FleetOrchestrator so these processes
can be monitored and controlled from the Service Network tab.
"""

import argparse
import json
import logging
import os
import platform
import pika
import sys
import time
from pathlib import Path

# Add packages to path for development
REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT.parent / "test" / "python-process-hub"))
sys.path.insert(0, str(REPO_ROOT.parent / "develop_ms_cleware"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_process_config(rabbitmq_host, rabbitmq_port):
    """
    Build the process configuration for Calculator and Cleware.

    Each entry tells ProcessHub how to start the process.
    The subprocess inherits os.environ but NOT sys.path modifications,
    so we must pass PYTHONPATH explicitly via the 'env' dict.
    """
    python_exe = sys.executable
    examples_dir = str(Path(__file__).parent.parent)

    # Build PYTHONPATH for subprocesses — they need to find
    # MicroserviceBase, MicroserviceClewareSwitch, etc.
    extra_paths = [
        str(REPO_ROOT),
        str(REPO_ROOT.parent / "develop_ms_cleware"),
    ]
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    if existing_pythonpath:
        extra_paths.append(existing_pythonpath)
    subprocess_env = {
        "PYTHONPATH": os.pathsep.join(extra_paths),
    }

    config = {
        "Calculator": {
            "process_name": "Calculator",
            "script": python_exe,
            "args": [
                str(Path(examples_dir) / "01_basic_service.py"),
                "--host", rabbitmq_host,
                "--port", str(rabbitmq_port),
            ],
            "env": subprocess_env,
            "wait_time": 2.0,
            "description": "Basic arithmetic calculator microservice",
        },
        "ServiceCleware": {
            "process_name": "ServiceCleware",
            "script": python_exe,
            "args": [
                "-m", "MicroserviceClewareSwitch",
                "--host", rabbitmq_host,
                "--port", str(rabbitmq_port),
            ],
            "env": subprocess_env,
            "wait_time": 2.0,
            "description": "Cleware USB switch microservice",
        },
    }

    return config


def main():
    parser = argparse.ArgumentParser(
        description="Hub Agent with Calculator and Cleware processes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_hub_agent.py --hub-id bench-1 --hub-name "HIL Bench 1"
  python run_hub_agent.py --hub-id dev-pc --rabbitmq-host 10.0.0.5
        """,
    )
    parser.add_argument(
        "--hub-id", default="hub-" + platform.node().lower().replace(".", "-"),
        help="Unique hub identifier (default: hub-<hostname>)",
    )
    parser.add_argument(
        "--hub-name", default="",
        help="Human-readable hub name (default: same as hub-id)",
    )
    parser.add_argument("--rabbitmq-host", default="localhost", help="RabbitMQ host")
    parser.add_argument("--rabbitmq-port", type=int, default=5672, help="RabbitMQ port")
    parser.add_argument(
        "--heartbeat-interval", type=float, default=5.0,
        help="Heartbeat interval in seconds",
    )
    parser.add_argument(
        "--status-interval", type=float, default=10.0,
        help="Status report interval in seconds",
    )
    args = parser.parse_args()

    hub_name = args.hub_name or args.hub_id

    from ProcessHub.transport import EventBusTransport, EventBusConfig
    from ProcessHub.runtime.server import ProcessHubServer
    from ProcessHub.process.executor import SimpleExecutor
    from ProcessHub.ui.null_view import NullView
    from ProcessHub.fleet import HubAgent

    # -- Local transport: for ProcessHub server internals --
    local_config = EventBusConfig(
        host=args.rabbitmq_host,
        port=args.rabbitmq_port,
        exchange_name="process_hub_local",
        routing_key_prefix="processhub",
        serializer="PickleSerializer",
        auto_reconnect=True,
    )
    local_transport = EventBusTransport(config=local_config)

    # -- Fleet transport: for HubAgent <-> Orchestrator communication --
    fleet_config = EventBusConfig(
        host=args.rabbitmq_host,
        port=args.rabbitmq_port,
        exchange_name="process_hub_fleet",
        routing_key_prefix="fleet",
        serializer="PickleSerializer",
        auto_reconnect=True,
    )
    fleet_transport = EventBusTransport(config=fleet_config)
    fleet_transport.start()

    # -- Process configuration --
    process_config = build_process_config(args.rabbitmq_host, args.rabbitmq_port)

    # -- Stop callback: notify MicroserviceBase service registry --
    # On Windows, CTRL_BREAK_EVENT is unreliable for piped subprocesses,
    # so the child process may be killed without running its cleanup code.
    # This callback publishes the "service off" event on its behalf.
    def on_process_stopped(process_name):
        try:
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=args.rabbitmq_host, port=args.rabbitmq_port
                )
            )
            ch = conn.channel()
            ch.exchange_declare(
                exchange='service_information', exchange_type='topic'
            )
            body = json.dumps({
                'info': {'name': process_name},
                'state': 'off',
            })
            ch.basic_publish(
                exchange='service_information',
                routing_key='service.information',
                body=body,
                properties=pika.BasicProperties(delivery_mode=2),
            )
            conn.close()
            logger.info(
                "Published 'off' for %s to service registry", process_name
            )
        except Exception as e:
            logger.warning(
                "Failed to notify registry for %s: %s", process_name, e
            )

    # -- ProcessHub server --
    executor = SimpleExecutor(
        stop_timeout=5.0, stop_callback=on_process_stopped
    )
    server = ProcessHubServer(
        transport=local_transport,
        executor=executor,
        view=NullView(),
        process_config=process_config,
    )
    server.start()

    # -- Hub Agent (sidecar) --
    agent = HubAgent(
        server=server,
        transport=fleet_transport,
        hub_id=args.hub_id,
        hub_name=hub_name,
        heartbeat_interval=args.heartbeat_interval,
        status_interval=args.status_interval,
    )
    agent.start()

    print()
    print("=" * 60)
    print(f"  Hub Agent: {hub_name}")
    print("=" * 60)
    print()
    print(f"  Hub ID:          {args.hub_id}")
    print(f"  Hub Name:        {hub_name}")
    print(f"  Host:            {platform.node()}")
    print(f"  RabbitMQ:        {args.rabbitmq_host}:{args.rabbitmq_port}")
    print(f"  Heartbeat:       every {args.heartbeat_interval}s")
    print(f"  Status report:   every {args.status_interval}s")
    print()
    print("  Managed processes:")
    for name, cfg in process_config.items():
        print(f"    - {name}: {cfg['description']}")
    print()
    print("  Agent announced to fleet orchestrator.")
    print("  Processes can be started/stopped from the GUI or REST API.")
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()

    try:
        while True:
            messages = server.core.tick()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass

    print("\nShutting down...")
    agent.stop()
    server.stop()
    fleet_transport.stop()
    print(f"Hub agent '{args.hub_id}' stopped.")


if __name__ == "__main__":
    main()
