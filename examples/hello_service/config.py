"""Settings for the hello service.

Environment variables are read with the ``HELLO_`` prefix, e.g.:

    HELLO_GRPC_PORT=50051
    HELLO_CONSUL_ADDR=http://127.0.0.1:8500
    HELLO_GREETING=Hola

``grpc_port`` defaults to ``0`` (OS-assigned), which matches the Nomad +
Consul dynamic port allocation pattern.
"""

from __future__ import annotations

from pydantic_settings import SettingsConfigDict

from MicroserviceBase.runtime import BaseServiceSettings


class Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(
        env_prefix="HELLO_",
        env_file=".env",
        extra="ignore",
    )

    # Override the default service_name from the base.
    service_name: str = "hello"

    # Service-specific
    greeting: str = "Hello"
