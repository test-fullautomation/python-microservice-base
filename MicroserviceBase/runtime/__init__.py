"""MicroserviceBase runtime library.

Public API used by service authors:

- :class:`ServiceRunner` — start a gRPC service with Consul registration,
  reflection, and graceful shutdown.
- :class:`ServicerEntry` — one servicer to bind to the gRPC server.
- :class:`ConsulRegistration` — low-level Consul register/deregister.
- :class:`BaseServiceSettings` — Pydantic parent class for service settings.
"""

from .consul import ConsulRegistration
from .reflection import enable_reflection
from .server import ServiceRunner, ServicerEntry
from .settings import BaseServiceSettings

__all__ = [
    "BaseServiceSettings",
    "ConsulRegistration",
    "ServiceRunner",
    "ServicerEntry",
    "enable_reflection",
]
