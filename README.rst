.. Copyright 2020-2026 Robert Bosch GmbH

.. Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

.. http://www.apache.org/licenses/LICENSE-2.0

.. Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

Package Description
===================

**MicroserviceBase** is a Python framework for building, managing, and orchestrating
microservices with RabbitMQ-based communication.

It provides the foundation for creating microservices that communicate through RabbitMQ,
with a built-in GUI for monitoring, a local process hub for lifecycle management,
and a service registry for dynamic discovery.

Key Features
------------

* **Microservice Framework** -- Base classes for creating services with RPC and pub/sub patterns
* **Service Registry** -- Dynamic service registration and discovery via RabbitMQ exchange
* **FastAPI Bridge** -- REST API and WebSocket gateway connecting GUI to microservices
* **Manager GUI** -- Electron + browser-based dashboard for monitoring and controlling services
* **Local Process Hub** -- Start, stop, and manage service processes with graceful shutdown
* **Multi-Broker Support** -- Connect to multiple RabbitMQ brokers simultaneously
* **Service Import** -- Import microservice packages (folder or zip) into the local hub
* **Service Creator** -- Interactive wizard for scaffolding new microservices
* **Hexagonal Architecture** -- Clean separation via ports and adapters pattern
* **Standalone Installer** -- Package as Windows desktop application (DevAtServGUI)

How to install
--------------

Installation via GitHub (recommended for developers)

   Clone the **python-microservice-base** repository to your machine.

   .. code::

      git clone https://github.com/test-fullautomation/python-microservice-base.git

   `MicroserviceBase in GitHub <https://github.com/test-fullautomation/python-microservice-base>`_

   Use the following command to install **MicroserviceBase**:

   .. code::

      pip install .

   For development mode:

   .. code::

      pip install -e .

Prerequisites
-------------

* Python 3.10 or higher
* RabbitMQ server (message broker)
* pika package (RabbitMQ client for Python)
* FastAPI and uvicorn (for the bridge)
* Node.js and npm (for GUI development)

Package Documentation
---------------------

A detailed documentation of **MicroserviceBase** can be found here:
`MicroserviceBase.pdf <https://github.com/test-fullautomation/python-microservice-base/blob/develop/MicroserviceBase/MicroserviceBase.pdf>`_

Feedback
--------

To give us a feedback, you can send an email to `Nguyen Huynh Tri Cuong <mailto:Cuong.NguyenHuynhTri@vn.bosch.com>`_
or `Thomas Pollerspoeck <mailto:Thomas.Pollerspoeck@de.bosch.com>`_

In case you want to report a bug or request any interesting feature, please don't hesitate to raise a ticket.

Maintainers
-----------

`Nguyen Huynh Tri Cuong <mailto:Cuong.NguyenHuynhTri@vn.bosch.com>`_

Contributors
------------

`Nguyen Huynh Tri Cuong <mailto:Cuong.NguyenHuynhTri@vn.bosch.com>`_

`Thomas Pollerspoeck <mailto:Thomas.Pollerspoeck@de.bosch.com>`_

License
-------

Copyright 2020-2026 Robert Bosch GmbH

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    |License: Apache v2|

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.


.. |License: Apache v2| image:: https://img.shields.io/pypi/l/robotframework.svg
   :target: http://www.apache.org/licenses/LICENSE-2.0.html
