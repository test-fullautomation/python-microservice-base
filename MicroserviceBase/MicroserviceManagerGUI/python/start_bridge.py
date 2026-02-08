#!/usr/bin/env python3
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
# File: start_bridge.py
#
# Description:
#   Standalone entry point to start the FastAPI UI bridge only.
#   Use this when the Service Registry is already running elsewhere.
#   Designed to be spawned by the Electron GUI or run manually.
#
# Usage:
#   python start_bridge.py [--host BROKER_HOST] [--port BROKER_PORT]
#                          [--bridge-host BRIDGE_HOST] [--bridge-port BRIDGE_PORT]
#                          [--config CONFIG_PATH]
#
# *******************************************************************************
"""
Standalone FastAPI UI Bridge launcher.

Starts the FastAPI bridge that exposes microservices via REST API and WebSocket.
Can be spawned by the Electron GUI or run directly from the command line.
"""

import argparse
import json
import sys
import threading
from pathlib import Path

# Add the repository root to sys.path so MicroserviceBase can be imported.
# Path: python/ -> MicroserviceManagerGUI/ -> MicroserviceBase/ -> repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from MicroserviceBase.factory import create_transport, create_registry, create_ui_bridge


def _load_config(config_path):
    """Load config.json and return the dict (empty dict on failure)."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f" [!] Could not load config from {config_path}: {exc}")
        return {}


def parse_args():
    parser = argparse.ArgumentParser(description='Start the FastAPI UI Bridge')
    parser.add_argument('--config', default=None,
                        help='Path to config.json (default: config.json next to this script)')
    parser.add_argument('--host', default=None,
                        help='RabbitMQ broker host (overrides config)')
    parser.add_argument('--port', default=None,
                        help='RabbitMQ broker port (overrides config)')
    parser.add_argument('--bridge-host', default=None,
                        help='FastAPI bridge listen host (overrides config)')
    parser.add_argument('--bridge-port', type=int, default=None,
                        help='FastAPI bridge listen port (overrides config)')
    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve config path
    config_path = args.config or str(Path(__file__).resolve().parent / 'config.json')
    config = _load_config(config_path)

    # Merge: CLI args > config.json > built-in defaults
    broker_host = args.host or config.get('broker_host', 'localhost')
    broker_port = args.port or config.get('broker_port', '5672')
    bridge_host = args.bridge_host or config.get('bridge_host', 'localhost')
    bridge_port = args.bridge_port or config.get('bridge_port', 1112)
    update_exchange = config.get('update_exchange_name', 'services_update')

    cmd_args = ['--host', broker_host, '--port', str(broker_port)]

    transport = create_transport('rabbitmq', cmd_args=cmd_args,
                                 service_name='FastAPIBridge')
    registry = create_registry('rabbitmq', cmd_args=cmd_args,
                                service_name='FastAPIBridge',
                                update_exchange_name=update_exchange)

    services_info = {}

    def request_handler(request_data, exchange='services_request', routing_key=''):
        return transport.rpc_call(request_data, exchange, routing_key)

    def services_info_provider():
        return services_info

    bridge = create_ui_bridge('fastapi', host=bridge_host, port=bridge_port)

    print(f" [*] FastAPI Bridge Configuration:")
    print(f" [*]   Bridge:    http://{bridge_host}:{bridge_port}")
    print(f" [*]   Broker:    {broker_host}:{broker_port}")
    print(f" [*]   REST API:  http://{bridge_host}:{bridge_port}/api/request")
    print(f" [*]   Services:  http://{bridge_host}:{bridge_port}/api/services")
    print(f" [*]   WebSocket: ws://{bridge_host}:{bridge_port}/ws/updates")
    print(f" [*]   Swagger:   http://{bridge_host}:{bridge_port}/docs")

    try:
        def _listen_for_updates():
            registry.subscribe_to_updates(
                lambda data: _on_update(bridge, services_info, data)
            )

        update_thread = threading.Thread(target=_listen_for_updates, daemon=True)
        update_thread.start()

        print(" [*] Starting FastAPI bridge. Press CTRL+C to stop.")
        bridge.start(request_handler, services_info_provider)
        bridge.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n [*] Shutting down...")
        try:
            bridge.stop()
            transport.disconnect()
            registry.cleanup()
        except (KeyboardInterrupt, SystemExit, Exception):
            pass
        print(" [*] Bridge stopped.")


def _on_update(bridge, services_info, data):
    services_info.clear()
    services_info.update(data)
    bridge.broadcast_update(services_info)
    print(f" [>] Services updated: {list(services_info.keys())}")


if __name__ == '__main__':
    main()
