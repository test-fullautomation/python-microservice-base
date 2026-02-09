# MicroserviceBase
[![License: Apache v2](https://img.shields.io/pypi/l/robotframework.svg)](http://www.apache.org/licenses/LICENSE-2.0.html)

**A Python framework for building, managing, and orchestrating microservices with RabbitMQ-based communication.**

MicroserviceBase provides the foundation for creating microservices that communicate through RabbitMQ, with a built-in GUI for monitoring, a local process hub for lifecycle management, and a service registry for dynamic discovery. Whether you're building test automation infrastructure, managing distributed services, or creating IoT device controllers, MicroserviceBase gives you the tools to develop and deploy microservices reliably.

## Why MicroserviceBase?

### The Problem

In distributed systems and test automation environments, you often need to:

- Create services that communicate via message broker (RabbitMQ)
- Register and discover services dynamically
- Monitor service status in real-time via a GUI
- Manage service processes (start, stop, import) from a central dashboard
- Connect to multiple brokers simultaneously
- Package everything as a standalone desktop application

Building this from scratch leads to boilerplate code, inconsistent service patterns, and complex deployment.

### The Solution

MicroserviceBase provides a complete framework:

```
+-----------------+     +-----------------+     +-----------------+
|  Service A      |     |  Service B      |     |  Service C      |
|  (Calculator)   |     |  (Cleware)      |     |  (Custom)       |
+--------+--------+     +--------+--------+     +--------+--------+
         |                       |                       |
         +-----------------------+-----------------------+
                                 |
                          +------+------+
                          |  RabbitMQ   |
                          |  Broker     |
                          +------+------+
                                 |
                    +------------+------------+
                    |                         |
             +------+------+          +------+------+
             |  Service    |          |  FastAPI    |
             |  Registry   |          |  Bridge     |
             +-------------+          +------+------+
                                             |
                                      +------+------+
                                      |  Manager    |
                                      |  GUI        |
                                      +-------------+
```

## Key Features

- **Microservice Framework** - Base classes for creating services with RPC and pub/sub patterns
- **Service Registry** - Dynamic service registration and discovery via RabbitMQ exchange
- **FastAPI Bridge** - REST API and WebSocket gateway connecting GUI to microservices
- **Manager GUI** - Electron + browser-based dashboard for monitoring and controlling services
- **Local Process Hub** - Start, stop, and manage service processes with crash recovery
- **Multi-Broker Support** - Connect to multiple RabbitMQ brokers simultaneously
- **Service Import** - Import microservice packages (folder or zip) into the local hub
- **Service Creator** - Interactive wizard for scaffolding new microservices
- **Hexagonal Architecture** - Clean separation via ports and adapters pattern
- **Standalone Installer** - Package as Windows desktop application (DevAtServGUI)

## Architecture

MicroserviceBase follows hexagonal (ports & adapters) architecture:

```
+-------------------------------------------------------------+
|                      GUI Layer                               |
|  Electron App  |  Web Browser  |  Service Plugins            |
+-------------------------------------------------------------+
                          |
+-------------------------------------------------------------+
|                   FastAPI Bridge                             |
|  REST API  |  WebSocket  |  Local Hub Manager                |
+-------------------------------------------------------------+
                          |
+-------------------------------------------------------------+
|                    Domain Layer                               |
|  ServiceBase  |  ServiceRegistry  |  Factory                 |
+-------------------------------------------------------------+
                          |
+-------------------------------------------------------------+
|                   Ports (Interfaces)                          |
|  TransportPort  |  RegistryPort  |  UIBridgePort             |
+-------------------------------------------------------------+
                          |
+-------------------------------------------------------------+
|                 Adapters (Implementations)                    |
|  RabbitMQ Transport  |  RabbitMQ Registry  |  FastAPI Bridge  |
|  Local Hub Manager   |  Service Executor                     |
+-------------------------------------------------------------+
```

### Project Structure

```
python-microservice-base/
+-- MicroserviceBase/
|   +-- __init__.py
|   +-- factory.py                  # Factory for creating components
|   +-- domain/
|   |   +-- service_base.py         # Base class for all microservices
|   |   +-- service_registry.py     # Service registration and discovery
|   +-- ports/
|   |   +-- transport.py            # Transport interface
|   |   +-- registry.py             # Registry interface
|   |   +-- ui_bridge.py            # UI bridge interface
|   +-- adapters/
|   |   +-- transport/
|   |   |   +-- rabbitmq_adapter.py # RabbitMQ transport implementation
|   |   +-- registry/
|   |   |   +-- amqp_registry_adapter.py  # RabbitMQ registry implementation
|   |   +-- ui_bridge/
|   |   |   +-- fastapi_bridge.py   # FastAPI REST/WS bridge
|   |   +-- local_hub/
|   |       +-- local_hub_manager.py# Process lifecycle management
|   |       +-- service_executor.py # Process execution with graceful shutdown
|   +-- MicroserviceManagerGUI/
|       +-- electron/               # Electron wrapper (main.js, preload.js)
|       +-- web/                    # Browser-compatible HTML/CSS/JS
|       |   +-- js/                 # App logic, dashboards, clients
|       |   +-- css/                # Styles
|       |   +-- services/           # Dynamically loaded service plugins
|       +-- python/                 # Python launchers and config
+-- examples/                       # Example scripts
+-- docs/
|   +-- adr/                        # Architecture Decision Records
|   +-- diagrams/                   # PlantUML diagrams
+-- pyproject.toml
```

## Installation

```bash
# From source (recommended for developers)
git clone https://github.com/test-fullautomation/python-microservice-base.git
cd python-microservice-base
pip install .

# Development mode
pip install -e .
```

### Prerequisites

- Python 3.10 or higher
- RabbitMQ server (for message broker)
- pika package (RabbitMQ client)
- FastAPI + uvicorn (for bridge)
- Node.js + npm (for GUI development)

### RabbitMQ Setup

```bash
# Using Docker (recommended)
docker run -d -p 5672:5672 -p 15672:15672 rabbitmq:management

# Management UI at http://localhost:15672 (guest/guest)
```

## Quick Start

### 1. Create a Microservice

```python
import sys
from MicroserviceBase.domain.service_base import ServiceBase
from MicroserviceBase.factory import create_transport, create_registry

class CalculatorService(ServiceBase):
    _SERVICE_INFO = {
        'name': 'Calculator',
        'description': 'A simple calculator service.',
        'version': '1.0.0',
        'routing_key': 'service.calculator',
        'gui_support': False,
        'methods': [],
        'methods_info': {},
    }

    def svc_api_add(self, a, b):
        """Add two numbers."""
        return int(a) + int(b)

    def svc_api_multiply(self, a, b):
        """Multiply two numbers."""
        return int(a) * int(b)

# Create transport and registry via factory
transport = create_transport('rabbitmq', cmd_args=sys.argv[1:],
                             service_name='Calculator')
registry = create_registry('rabbitmq', cmd_args=sys.argv[1:],
                            service_name='Calculator')

# Create service, register, and serve
service = CalculatorService(transport=transport, registry=registry)
service.register_service()
service.serve()  # Blocks until interrupted
```

### 2. Start the Service Registry

```bash
python MicroserviceBase/MicroserviceManagerGUI/python/start_registry.py \
    --host localhost --port 5672
```

### 3. Start the FastAPI Bridge

```bash
python MicroserviceBase/MicroserviceManagerGUI/python/start_bridge.py \
    --host localhost --port 5672 --bridge-port 1112
```

The bridge provides:
- REST API: `http://localhost:1112/api/request`
- Services: `http://localhost:1112/api/services`
- WebSocket: `ws://localhost:1112/ws/updates`
- Swagger: `http://localhost:1112/docs`

### 4. Launch the GUI

```bash
cd MicroserviceBase/MicroserviceManagerGUI
npm install
npm start
```

## Manager GUI

The MicroserviceManagerGUI provides a desktop application for monitoring and controlling microservices.

### Features

- **Service Dashboard** - Real-time view of all registered services and their methods
- **RPC Testing** - Send requests to services and view responses
- **Multi-Broker** - Connect to multiple RabbitMQ brokers simultaneously
- **Local Hub** - Start, stop, and manage local service processes
- **Service Import** - Import microservice packages into the local hub
- **Service Creator** - Scaffold new microservices with wizard UI

### Dual Hosting

The GUI runs in two modes:
- **Electron** - Desktop application with native process management
- **Browser** - Access via `http://localhost:1112` when the FastAPI bridge is running

### Standalone Installer (DevAtServGUI)

Package the GUI as a standalone Windows application:

```bash
cd MicroserviceBase/MicroserviceManagerGUI

# Build installer
build.bat

# Or build unpacked (for testing)
build.bat --pack
```

The installer creates:
- Desktop application at `C:\Program Files\DevAtServGUI\`
- User data at `%APPDATA%\devatservgui\` (settings, config, services)

## Local Process Hub

The Local Hub manages service processes directly from the GUI:

### Process Configuration

```json
{
    "ServiceRegistry": {
        "script": "${config_dir}/start_registry.py",
        "args": ["--config", "${config_dir}/config.json"],
        "process_name": "ServiceRegistry",
        "wait_time": 2.0
    },
    "MyService": {
        "script": "${python}",
        "args": ["-m", "MyService"],
        "cwd": "${config_dir}/services",
        "process_name": "MyService",
        "wait_time": 1.0
    }
}
```

Placeholders:
- `${python}` - Resolves to `sys.executable`
- `${config_dir}` - Resolves to the directory containing `hub_processes.json`

### Hub REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/local-hub/start` | POST | Start the local hub |
| `/api/local-hub/stop` | POST | Stop the local hub |
| `/api/local-hub/status` | GET | Hub status and process list |
| `/api/local-hub/config` | GET/POST | Manage process configurations |
| `/api/local-hub/processes/start` | POST | Start processes by name |
| `/api/local-hub/processes/stop` | POST | Stop processes by name |
| `/api/local-hub/import-service` | POST | Import a microservice package |

## Examples

The `examples/` directory contains working examples:

| Example | Description |
|---------|-------------|
| `01_basic_service.py` | Basic microservice with RPC methods |
| `02_service_client.py` | RPC client calling a running service |
| `03_service_registry.py` | Service Registry with discovery |
| `04_eventbus_transport.py` | EventBus transport adapter |
| `05_alias_routing.py` | Alias-based request routing |
| `06_fastapi_bridge.py` | FastAPI bridge with REST/WebSocket |
| `07_mock_fleet_api.py` | Mock fleet API for testing |
| `08_fleet_demo.py` | Fleet orchestration demo |

## Diagrams

Architecture diagrams are available in `docs/diagrams/` in PlantUML format:

| Diagram | Description |
|---------|-------------|
| `overview.puml` | System overview |
| `architecture.puml` | Hexagonal architecture |
| `component.puml` | Component dependencies |
| `class_domain.puml` | Domain layer classes |
| `class_ports.puml` | Port interfaces |
| `class_adapters.puml` | Adapter implementations |
| `gui_architecture.puml` | GUI dual-host architecture |
| `sequence_rpc.puml` | RPC call sequence |
| `sequence_registration.puml` | Service registration flow |
| `sequence_shutdown.puml` | Graceful shutdown sequence |
| `sequence_service_import.puml` | Service import flow |
| `state_process_lifecycle.puml` | Process state machine |

## Architecture Decision Records (ADRs)

Design decisions are documented in `docs/adr/`:

| ADR | Title |
|-----|-------|
| ADR-001 | Hexagonal Architecture |
| ADR-002 | Factory Pattern and Dependency Injection |
| ADR-003 | Dual-Host GUI Architecture |
| ADR-004 | FastAPI Bridge for Browser GUI |
| ADR-005 | Multi-Broker Connection Architecture |
| ADR-006 | Service Executor with RPC Shutdown |
| ADR-007 | Local Hub Manager |
| ADR-008 | Service Import with Module Execution |
| ADR-009 | Registry Shutdown Notification |
| ADR-010 | Windows Process Lifecycle Fixes |
| ADR-011 | Config Placeholder Persistence |
| ADR-012 | Electron Bridge Lifecycle Decoupling |

## Package Documentation

A detailed documentation of **MicroserviceBase** can be found here:
[MicroserviceBase.pdf](https://github.com/test-fullautomation/python-microservice-base/blob/develop/MicroserviceBase/MicroserviceBase.pdf)

## Feedback

To give us a feedback, you can send an email to [Nguyen Huynh Tri Cuong](mailto:Cuong.NguyenHuynhTri@vn.bosch.com) or [Thomas Pollerspoeck](mailto:Thomas.Pollerspoeck@de.bosch.com)

In case you want to report a bug or request any interesting feature, please don't hesitate to raise a ticket.

## Maintainers

[Nguyen Huynh Tri Cuong](mailto:Cuong.NguyenHuynhTri@vn.bosch.com)

## Contributors

[Nguyen Huynh Tri Cuong](mailto:Cuong.NguyenHuynhTri@vn.bosch.com)

[Thomas Pollerspoeck](mailto:Thomas.Pollerspoeck@de.bosch.com)

## License

Copyright 2020-2026 Robert Bosch GmbH

Licensed under the Apache License, Version 2.0 (the "License"); you
may not use this file except in compliance with the License. You may
obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
