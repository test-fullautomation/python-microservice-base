"""Dependency injection for the hello service.

``create_context()`` wires configuration, domain logic and adapters together.
Keep this file small — it's the only place where concrete classes are chosen,
so swapping adapters (e.g. for tests) is a one-line change.
"""

from __future__ import annotations

from dataclasses import dataclass

from adapters.api.grpc_adapter import HelloGrpcAdapter
from config import Settings
from domain.hello_service import HelloService


@dataclass
class Context:
    settings: Settings
    domain: HelloService
    grpc_adapter: HelloGrpcAdapter


def create_context() -> Context:
    settings = Settings()
    domain = HelloService(greeting=settings.greeting)
    grpc_adapter = HelloGrpcAdapter(domain)
    return Context(settings=settings, domain=domain, grpc_adapter=grpc_adapter)
