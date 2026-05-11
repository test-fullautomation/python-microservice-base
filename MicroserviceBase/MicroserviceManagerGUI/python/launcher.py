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
# File: launcher.py
#
# Description:
#   Entry point that starts the FastAPI UI Bridge.
#   Designed to be spawned by the Electron GUI or run manually from the
#   command line.
#
#   The Service Registry is NOT started here — it is managed as a separate
#   process by the Local Hub (ProcessHub) so the user can see, start, and
#   stop it from the hub dashboard.
#
# Usage:
#   python launcher.py [--broker-host HOST] [--broker-port PORT]
#                      [--bridge-host HOST] [--bridge-port PORT]
#                      [--config CONFIG_PATH]
#
# *******************************************************************************
"""
FastAPI Bridge launcher.

Starts the FastAPI Bridge (REST/WS gateway) that connects the
MicroserviceManagerGUI to microservices.

Post-migration to gRPC + Consul + Nomad, the bridge no longer requires
a RabbitMQ broker to start.  If the broker is reachable, the legacy
``/api/request`` endpoint and the WebSocket service-update stream are
enabled; if not, the bridge starts in gRPC/Consul/Nomad-only mode and
those legacy paths return a clear "no broker configured" response.
"""

import argparse
import json
import os
import sys
import threading
from pathlib import Path

# Try pip-installed package first; fall back to repo-relative path for development.
try:
    from MicroserviceBase.factory import create_transport, create_registry, create_ui_bridge
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
    from MicroserviceBase.factory import create_transport, create_registry, create_ui_bridge


def _try_connect_rabbitmq(broker_host, broker_port, update_exchange):
    """Attempt to connect to RabbitMQ for the legacy ``/api/request`` and
    update-broadcast paths.

    Returns ``(transport, registry)`` on success or ``(None, None)`` if
    the broker is unreachable.  Failure is non-fatal — the bridge can
    still serve the gRPC + Consul + Nomad endpoints.
    """
    cmd_args = ['--host', broker_host, '--port', str(broker_port)]
    try:
        transport = create_transport(
            'rabbitmq', cmd_args=cmd_args, service_name='FastAPIBridge'
        )
        registry = create_registry(
            'rabbitmq', cmd_args=cmd_args, service_name='FastAPIBridge',
            update_exchange_name=update_exchange,
        )
        print(f" [*] RabbitMQ broker reachable at {broker_host}:{broker_port}"
              f" — legacy /api/request + WS updates enabled.")
        return transport, registry
    except Exception as exc:
        print(f" [!] RabbitMQ broker unreachable at {broker_host}:{broker_port}:"
              f" {exc}")
        print(" [!] Continuing without RabbitMQ — only gRPC, Consul, and Nomad")
        print(" [!] endpoints are active.  Legacy /api/request will return a")
        print(' [!] "no request handler configured" response if called.')
        return None, None


def _load_config(config_path):
    """
Load config.json and return the dict (empty dict on failure).

**Arguments:**

* ``config_path``

  / *Condition*: required / *Type*: str /

  Path to the config.json file.
    """
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f" [!] Could not load config from {config_path}: {exc}")
        return {}


def parse_args():
    parser = argparse.ArgumentParser(description='Start the FastAPI Bridge')
    parser.add_argument('--config', default=None,
                        help='Path to config.json (default: config.json next to this script)')
    parser.add_argument('--broker-host', default=None,
                        help='RabbitMQ broker host (overrides config)')
    parser.add_argument('--broker-port', default=None,
                        help='RabbitMQ broker port (overrides config)')
    parser.add_argument('--bridge-host', default=None,
                        help='FastAPI bridge listen host (overrides config)')
    parser.add_argument('--bridge-port', type=int, default=None,
                        help='FastAPI bridge listen port (overrides config)')
    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve config path
    script_dir = Path(__file__).resolve().parent
    config_path = args.config or str(script_dir / 'config.json')
    config = _load_config(config_path)

    # Expose hub_processes.json path to FastAPIBridge's LocalHubManager.
    # In packaged mode, config_path points to %APPDATA%/.../python/config.json,
    # so hub_processes.json lives in the same directory.
    config_dir = str(Path(config_path).resolve().parent)
    os.environ['DASGUI_HUB_CONFIG'] = str(
        Path(config_dir) / 'hub_processes.json'
    )

    # Merge: CLI args > config.json > built-in defaults
    broker_host = args.broker_host or config.get('broker_host', 'localhost')
    broker_port = args.broker_port or config.get('broker_port', '5672')
    bridge_host = args.bridge_host or config.get('bridge_host', 'localhost')
    bridge_port = args.bridge_port or config.get('bridge_port', 1112)
    update_exchange = config.get('update_exchange_name', 'services_update')

    bridge_transport, bridge_registry = _try_connect_rabbitmq(
        broker_host, broker_port, update_exchange
    )

    services_info = {}

    if bridge_transport is not None:
        def request_handler(request_data, exchange='services_request', routing_key=''):
            return bridge_transport.rpc_call(request_data, exchange, routing_key)
    else:
        # Pass None — the bridge's /api/request endpoint already returns
        # a clean "No request handler configured" response in this case.
        request_handler = None

    def services_info_provider():
        return services_info

    bridge = create_ui_bridge('fastapi', host=bridge_host, port=bridge_port)

    def _on_update(data):
        services_info.clear()
        services_info.update(data)
        bridge.broadcast_update(services_info)
        print(f" [>] Services updated: {list(services_info.keys())}")

    # Update-listener thread is broker-dependent — skip when no RabbitMQ.
    if bridge_registry is not None:
        threading.Thread(
            target=bridge_registry.subscribe_to_updates,
            args=(_on_update,),
            daemon=True,
        ).start()

    broker_status = (
        f"{broker_host}:{broker_port} (connected)"
        if bridge_transport is not None
        else "(not configured — running in gRPC/Consul/Nomad-only mode)"
    )
    print(f" [*] FastAPI Bridge Configuration:")
    print(f" [*]   Bridge:    http://{bridge_host}:{bridge_port}")
    print(f" [*]   Broker:    {broker_status}")
    if bridge_transport is not None:
        print(f" [*]   REST API:  http://{bridge_host}:{bridge_port}/api/request")
        print(f" [*]   WebSocket: ws://{bridge_host}:{bridge_port}/ws/updates")
    print(f" [*]   Services:  http://{bridge_host}:{bridge_port}/api/services")
    print(f" [*]   gRPC API:  http://{bridge_host}:{bridge_port}/api/grpc/services/<name>")
    print(f" [*]   Consul:    http://{bridge_host}:{bridge_port}/api/consul/*")
    print(f" [*]   Nomad:     http://{bridge_host}:{bridge_port}/api/nomad/*")
    print(f" [*]   Swagger:   http://{bridge_host}:{bridge_port}/docs")

    try:
        print(" [*] Starting FastAPI bridge. Press CTRL+C to stop.")
        bridge.start(request_handler, services_info_provider)
        bridge.wait()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n [*] Shutting down...")
        try:
            bridge.stop()
            if bridge_transport is not None:
                bridge_transport.disconnect()
            if bridge_registry is not None:
                bridge_registry.cleanup()
        except (KeyboardInterrupt, SystemExit, Exception):
            pass
        print(" [*] Bridge stopped.")


if __name__ == '__main__':
    main()
