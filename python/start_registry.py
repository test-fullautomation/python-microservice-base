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
# File: start_registry.py
#
# Description:
#   Standalone entry point to start the Service Registry only.
#   Useful when running the registry separately from the bridge.
#
# Usage:
#   python start_registry.py [--host BROKER_HOST] [--port BROKER_PORT]
#                            [--config CONFIG_PATH]
#
# *******************************************************************************
"""
Standalone Service Registry launcher.

Starts the Service Registry that tracks all services, handles registration
events, and broadcasts updates to UI clients via a fanout exchange.
"""

import argparse
import json
import logging
import sys
import threading
from pathlib import Path

# Add the repository root to sys.path so MicroserviceBase can be imported.
# Path: python/ -> MicroserviceManagerGUI/ -> MicroserviceBase/ -> repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from MicroserviceBase.domain.service_registry import ServiceRegistry
from MicroserviceBase.factory import create_transport, create_registry


def _setup_logging():
    """Configure logging to write to a file next to this script.

    When spawned by the ProcessHub executor, stdout/stderr are captured
    into pipes that nobody reads.  Writing to a full pipe blocks the
    process, so the StreamHandler is only added when stdout is a real
    terminal (interactive use).  The FileHandler always captures output.
    """
    log_path = Path(__file__).resolve().parent / 'registry.log'
    handlers = [logging.FileHandler(str(log_path), mode='a')]
    if sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=handlers,
    )


logger = logging.getLogger(__name__)


def _load_config(config_path):
    """Load config.json and return the dict (empty dict on failure)."""
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("Could not load config from %s: %s", config_path, exc)
        return {}


def parse_args():
    parser = argparse.ArgumentParser(description='Start the Service Registry')
    parser.add_argument('--config', default=None,
                        help='Path to config.json (default: config.json next to this script)')
    parser.add_argument('--host', default=None,
                        help='RabbitMQ broker host (overrides config)')
    parser.add_argument('--port', default=None,
                        help='RabbitMQ broker port (overrides config)')
    return parser.parse_args()


def main():
    _setup_logging()
    args = parse_args()

    # Resolve config path
    config_path = args.config or str(Path(__file__).resolve().parent / 'config.json')
    config = _load_config(config_path)

    # Merge: CLI args > config.json > built-in defaults
    broker_host = args.host or config.get('broker_host', 'localhost')
    broker_port = args.port or config.get('broker_port', '5672')
    update_exchange = config.get('update_exchange_name', 'services_update')

    cmd_args = ['--host', broker_host, '--port', str(broker_port)]

    transport = create_transport('rabbitmq', cmd_args=cmd_args,
                                 service_name='ServiceRegistry')
    registry = create_registry('rabbitmq', cmd_args=cmd_args,
                                service_name='ServiceRegistry',
                                update_exchange_name=update_exchange)

    service_registry = ServiceRegistry(transport=transport, registry=registry)

    logger.info("Service Registry starting (broker %s:%s)", broker_host, broker_port)

    try:
        def _on_service_event(ch, method, props, body):
            if isinstance(body, bytes):
                body = json.loads(body.decode('utf-8'))
            logger.info("Service event received: %s", body)
            service_registry.handle_update(body)
            service_registry.notify_updates()

        discovery_thread = threading.Thread(
            target=registry.subscribe_to_events,
            args=(_on_service_event,),
            daemon=True,
        )
        discovery_thread.start()

        service_registry.register_service()

        logger.info("Service Registry running. Press CTRL+C to stop.")
        service_registry.serve()
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        try:
            service_registry._broadcast_shutdown_sentinel()
        except Exception:
            logger.debug("Failed to broadcast shutdown sentinel", exc_info=True)
        service_registry.unregister_service()
        service_registry.close()
        registry.cleanup()
        logger.info("Registry stopped.")


if __name__ == '__main__':
    main()
