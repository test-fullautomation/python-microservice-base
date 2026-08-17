"""Entry point for the hello service.

Run with:

    cd examples/hello_service
    python scripts/generate_protos.py       # once, to create proto/hello_pb2*.py
    python main.py

Or via uv:

    uv run python main.py

The service registers itself with Consul on startup and deregisters on a
Ctrl+C / SIGTERM / SIGBREAK.  With Consul running in dev mode
(``consul agent -dev``) you can verify registration with:

    curl http://localhost:8500/v1/catalog/services
    grpcurl -plaintext -d '{"name": "World"}' <host>:<port> hello.v1.HelloService/Greet
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# When launched by Nomad (raw_exec), the working directory is not the
# service folder, so `from context import ...` fails.  Prepend this
# script's directory to sys.path so sibling modules are importable
# regardless of cwd.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from context import create_context
from proto import hello_pb2, hello_pb2_grpc  # type: ignore[import-not-found]

from MicroserviceBase.runtime import ServiceRunner, ServicerEntry


async def amain() -> None:
    ctx = create_context()

    logging.basicConfig(
        level=ctx.settings.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    full_service_name = hello_pb2.DESCRIPTOR.services_by_name["HelloService"].full_name

    runner = ServiceRunner(
        servicers=[
            ServicerEntry(
                register_fn=hello_pb2_grpc.add_HelloServiceServicer_to_server,
                full_service_name=full_service_name,
                servicer=ctx.grpc_adapter,
            )
        ],
        settings=ctx.settings,
        tags=["v1", "demo"],
    )
    await runner.serve_forever()


if __name__ == "__main__":
    asyncio.run(amain())
