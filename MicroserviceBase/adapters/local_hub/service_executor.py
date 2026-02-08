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
# File: service_executor.py
#
# Initially created by Nguyen Huynh Tri Cuong (MS/EMC51) / Feb 2026.
#
# Description:
#
#   Custom ProcessHub executor that sends an RPC shutdown command to a
#   MicroserviceBase service before falling back to signal-based termination.
#
# *******************************************************************************
"""
Service-aware process executor.

Wraps a ``SimpleExecutor`` and attempts graceful RPC shutdown
(``svc_api_shutdown``) before falling back to signal-based stop.
"""

import json
import logging
import time
import uuid
from typing import Callable, Optional

from ProcessHub.process import ProcessExecutor, SimpleExecutor

logger = logging.getLogger(__name__)


class ServiceExecutor(ProcessExecutor):
    """Process executor that sends an RPC shutdown to MicroserviceBase services.

    Delegates all operations to a wrapped ``SimpleExecutor``.  On ``stop()``,
    it first tries to send ``svc_api_shutdown`` via RabbitMQ to the service's
    queue.  If the service exits within ``shutdown_timeout`` seconds the
    process is considered stopped.  Otherwise it falls back to the delegate's
    signal-based stop (CTRL_BREAK_EVENT on Windows, SIGTERM on Linux).
    """

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 5672,
        start_callback: Optional[Callable] = None,
        stop_callback: Optional[Callable] = None,
        stop_timeout: float = 5.0,
        shutdown_timeout: float = 5.0,
    ):
        self._broker_host = broker_host
        self._broker_port = int(broker_port)
        self._shutdown_timeout = shutdown_timeout
        self._delegate = SimpleExecutor(
            start_callback=start_callback,
            stop_callback=stop_callback,
            stop_timeout=stop_timeout,
        )

    # -- Delegated methods --------------------------------------------------

    def start(self, name, config):
        return self._delegate.start(name, config)

    def is_running(self, name):
        return self._delegate.is_running(name)

    def get_pid(self, name):
        return self._delegate.get_pid(name)

    # -- Stop with RPC shutdown attempt -------------------------------------

    def stop(self, name, force=False):
        if self._delegate.is_running(name):
            if self._try_rpc_shutdown(name):
                # Process exited gracefully after RPC
                self._delegate._processes.pop(name, None)
                self._delegate._pids.pop(name, None)
                self._delegate._invoke_stop_callback(name)
                return True, f"Process {name} stopped gracefully via RPC"
        # Fallback to signal-based stop
        return self._delegate.stop(name, force=force)

    def _try_rpc_shutdown(self, process_name):
        """Send ``svc_api_shutdown`` RPC to the service queue.

        Returns ``True`` if the process exited within the timeout.
        """
        import pika

        try:
            conn = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self._broker_host, port=self._broker_port
                )
            )
            ch = conn.channel()
            # Temporary reply queue — required because on_request publishes to
            # props.reply_to; without it the handler would error.
            result = ch.queue_declare(queue="", exclusive=True)
            ch.basic_publish(
                exchange="",
                routing_key=process_name,
                properties=pika.BasicProperties(
                    reply_to=result.method.queue,
                    correlation_id=str(uuid.uuid4()),
                ),
                body=json.dumps({"method": "svc_api_shutdown", "args": None}),
            )
            conn.close()
            logger.info(
                "Sent svc_api_shutdown RPC to queue '%s'", process_name
            )
        except Exception:
            logger.debug(
                "RPC shutdown failed for '%s', will fall back to signal",
                process_name,
                exc_info=True,
            )
            return False

        # Poll for process exit
        deadline = time.monotonic() + self._shutdown_timeout
        while time.monotonic() < deadline:
            if not self._delegate.is_running(process_name):
                logger.info(
                    "Process '%s' exited gracefully after RPC shutdown",
                    process_name,
                )
                return True
            time.sleep(0.3)

        logger.warning(
            "Process '%s' did not exit within %.1fs after RPC shutdown",
            process_name,
            self._shutdown_timeout,
        )
        return False
