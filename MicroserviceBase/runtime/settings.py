"""
Base Pydantic settings for microservices.

Every service subclasses :class:`BaseServiceSettings` and adds its own
fields.  Environment variables are loaded with a service-specific
prefix.

Example::

    class HelloSettings(BaseServiceSettings):
        model_config = SettingsConfigDict(env_prefix="HELLO_", env_file=".env")

        greeting: str = "Hello"

The base provides the fields that every service needs to talk to Consul
and expose a gRPC server.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """
Common settings shared by all microservices.

Subclasses add service-specific fields and set ``env_prefix`` to the
service's name (e.g. ``HELLO_``).

**Attributes:**

* ``service_name``

  / *Type*: str / *Default*: "" /

  Logical service name used for Consul registration.

* ``service_host``

  / *Type*: str / *Default*: "0.0.0.0" /

  Address the gRPC server binds to.  ``0.0.0.0`` makes the service
  reachable on any interface; Consul registers the advertised address
  from ``advertise_addr`` if set, otherwise falls back to the local
  hostname.

* ``grpc_port``

  / *Type*: int / *Default*: 0 /

  TCP port for the gRPC server.  ``0`` means "let the operating system
  pick a free port".  The chosen port is then announced to Consul.

* ``advertise_addr``

  / *Type*: str / *Default*: "" /

  Address announced to Consul.  Leave empty to use the local hostname.

* ``consul_addr``

  / *Type*: str / *Default*: "http://localhost:8500" /

  Consul HTTP API endpoint.

* ``consul_token``

  / *Type*: str / *Default*: "" /

  Optional ACL token for Consul.

* ``log_level``

  / *Type*: str / *Default*: "INFO" /

  Python logging level name (``DEBUG``, ``INFO``, ``WARNING``,
  ``ERROR``, ``CRITICAL``).
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = ""
    service_host: str = "0.0.0.0"
    grpc_port: int = 0  # 0 => dynamic allocation

    advertise_addr: str = ""
    consul_addr: str = "http://localhost:8500"
    consul_token: str = ""

    log_level: str = "INFO"
