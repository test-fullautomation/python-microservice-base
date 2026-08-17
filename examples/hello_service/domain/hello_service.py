"""Pure business logic for the hello service.

No gRPC, no Consul, no I/O — just async Python.  This is what unit tests
exercise directly, and what the gRPC adapter delegates to.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class HelloService:
    """Stateless greeting service.

    The only configuration is the greeting prefix (e.g. ``"Hello"`` or
    ``"Bonjour"``), which comes from the service settings.
    """

    greeting: str = "Hello"

    async def greet(self, name: str) -> str:
        """Return a greeting for *name*."""
        who = name.strip() or "world"
        return f"{self.greeting}, {who}!"

    async def echo(self, payload: str) -> str:
        """Return *payload* unchanged."""
        return payload

    async def tick(self, count: int, interval_ms: int) -> AsyncIterator[tuple[int, str]]:
        """Emit ``(sequence, message)`` pairs asynchronously.

        If *count* is ``0`` the stream is unbounded — the caller is expected
        to cancel the iterator (the gRPC adapter does this on client
        disconnect).
        """
        delay = max(interval_ms, 0) / 1000.0
        seq = 0
        while count == 0 or seq < count:
            yield seq, f"tick #{seq}"
            seq += 1
            if delay > 0:
                await asyncio.sleep(delay)
