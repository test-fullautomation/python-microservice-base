# ADR-029: Robot Framework as the primary test client

## Status

Proposed

## Date

2026-05-10

## Author

Audit follow-up.  Aligns with the TA reference at
[`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal).

## Reviewer

- (pending)

## History

| Date       | Version | Description |
|------------|---------|-------------|
| 2026-05-07 | 1.0     | Initial draft — proposed a bespoke `MicroserviceBaseLibrary` Robot keyword library wrapping `LocalProtoClient` |
| 2026-05-10 | 1.1     | Implementation switched: instead of a custom keyword library, ship a `GrpcClient` connection type for the existing **QConnectBase** library.  Robot keywords (`Connect`, `Send Command`, `Verify`, `Disconnect`) are reused unchanged. |
| 2026-05-22 | 1.2     | **Robot resource generator added on top of `GrpcClient`.**  The earlier "JSON-string response surface" trade-off (see *Negative consequences*) is now mitigated by an emitter that turns a folder of `.proto` files into typed per-service `.resource` libraries (one keyword per RPC, prefixed with the service name).  Generator UI in the Manager GUI methods panel; CLI at `MicroserviceBase.tools.robot_gen`; HTTP at `POST /api/scaffold/robot`.  Tests get the readability of a per-method keyword wrapper without the maintenance cost &mdash; regenerate, don't hand-write.  See [`../../MicroserviceBase/MicroserviceManagerGUI/docs/md/robot_generator.md`](https://github.com/test-fullautomation/python-microservice-base/blob/develop/MicroserviceBase/MicroserviceManagerGUI/docs/md/robot_generator.md). |

## Context

The framework's services are built to run automated tests against
hardware (PPS, signal generators, scopes, HIL boxes).  Until now the
"how do you actually drive the services from a test" story has been
implicit:

- C++ tests via `qt_client_grpcpp` example (one-off integration
  scripts)
- Python tests via `LocalProtoClient` with hand-written test scripts
- GUI's API Explorer for interactive ad-hoc calls

What's missing is a **canonical test-authoring path** for the people
who actually write tests — testers and engineers who aren't paid to
write C++ or to wrangle gRPC channels.

The TA reference standardises on **Robot Framework**: a keyword-driven
test framework with a syntax that non-developers can read and write,
plus a library ecosystem that includes gRPC support.

This is the right fit because:

- Bosch / BITS has existing Robot Framework expertise and infrastructure
- Robot test logs are auditable — keywords + arguments + pass/fail are
  legible to non-engineers
- A **QConnectBase** library is already in widespread use across BITS
  test suites for TCP, Serial, SSH, RabbitMQ, and Winapp connections.
  All five share the same four keywords (`Connect` / `Send Command` /
  `Verify` / `Disconnect`).  Adding gRPC as another connection type
  reuses muscle memory and ops tooling instead of inventing a parallel
  keyword vocabulary.

## Decision

**Robot Framework is the primary test-authoring entry point**, and
**QConnectBase is the keyword library that drives every connection
type — including gRPC.**

Components:

- **`QConnectBase.grpc.GrpcClient`** — new connection type contributed
  upstream to QConnectBase at
  [`qconnect_base/QConnectBase/grpc/grpc_client.py`](https://github.com/test-fullautomation/QConnectBase/blob/develop/QConnectBase/grpc/grpc_client.py).
  Subclasses the existing `ConnectionBase` and is auto-discovered by
  `ConnectionManager` the same way as `TCPIPClient`, `SerialClient`,
  `SSHClient`, `RabbitmqClient`.
- Internally delegates to **`MicroserviceBase.adapters.grpc_bridge.reflect_client.GrpcReflectClient`**
  (gRPC server reflection) with an automatic fallback to
  **`LocalProtoClient`** when the server doesn't ship `grpc++_reflection`
  (typical for C++ services built against vcpkg's grpc port).
- **Two addressing modes**:
  - Direct: `target: "host:port"` in `conn_conf` — for ad-hoc / unit-test usage.
  - Consul-resolved: `service_name: "hello"` + `consul_addr:
    "http://localhost:8500"` — for integration tests against a running
    cluster.  Resolution uses the same code path the GUI's bridge uses
    (`MicroserviceBase.runtime.consul.resolve_via_consul`).
- **Send command shape**: a JSON document.
  - `{"method": "Greet", "args": {"name": "World"}}` when
    `full_service_name` is fixed in the connection config.
  - `{"service": "pkg.HelloService", "method": "Greet",
    "args": {…}}` to override the service per call (handy for
    multi-service binaries from the `multi_proto` scaffold layout).
- **Response handling**: gRPC response message → `MessageToDict` → JSON
  string → put on the QConnectBase trace queue.  The standard `Verify`
  keyword's regex matching works against the JSON, so testers don't
  learn anything new.

### Robot Framework usage

```robot
*** Settings ***
Library    QConnectBase.connection_manager.ConnectionManager

*** Test Cases ***
Greet
    Connect    grpc_hello    conn_conf={'conn_type': 'GrpcClient',
    ...                                  'service_name': 'hello',
    ...                                  'consul_addr': 'http://localhost:8500',
    ...                                  'full_service_name': 'hello.v1.HelloService'}
    ${res}=  Verify    grpc_hello
    ...                send_cmd={"method": "Greet", "args": {"name": "World"}}
    ...                search_pattern=Hello, World
    Should Be Equal    ${res}[0]    Hello, World!
    [Teardown]   Disconnect    grpc_hello
```

This is the **same shape** as a TCP test or a RabbitMQ test in the
existing test suites — only `conn_type` and the `send_cmd` payload
shape differ.

### Test repo layout

- Robot tests live in a separate repo (or a `tests/` subfolder for
  scaffold-generated services) and import `QConnectBase` as their
  Library.
- CI integration: Robot's `output.xml` + `report.html` artefacts fold
  into existing test-result viewers — no new tooling.

This does **not** replace direct-gRPC testing for unit tests inside
the service repo (e.g. C++ gtest against the in-process gRPC server).
QConnectBase + Robot is for **integration / system tests** that drive
real services over the network.

## Consequences

### Positive

- **Tests are written by the people who should write them** — testers,
  not service developers.
- **Same four keywords as every other connection type** in QConnectBase
  (`Connect` / `Send Command` / `Verify` / `Disconnect`).  Testers
  already familiar with the TCP, Serial, SSH, or RabbitMQ flow learn
  the gRPC flow in minutes.
- **No new keyword library to maintain.**  The earlier draft of this
  ADR proposed a bespoke `MicroserviceBaseLibrary` keyword library;
  the QConnectBase route reuses ~600 lines of already-shipping
  threading + trace-queue + regex-match infrastructure.
- **Reuses framework infrastructure** — Consul resolution and gRPC
  reflection are picked up by importing `MicroserviceBase`, not
  re-implemented.
- **Test logs are legible** — Robot's HTML report is shareable with
  non-technical stakeholders.
- **Aligns with TA reference and Bosch test-authoring conventions.**

### Negative

- **Two test ecosystems to maintain** — gtest/pytest for unit tests
  + Robot for integration tests.  This is the existing reality in any
  non-trivial project.
- **QConnectBase upstream dependency** — the `GrpcClient` lives in the
  QConnectBase repo, so changes go through that project's review path
  and release cadence.  Mitigated by the fact that the QConnectBase
  manager auto-loads any `robotframework_qconnect*` site-package, so a
  hot-fix can be shipped as a sibling pip package without an upstream
  PR if needed.
- **JSON-string response surface** — testers regex-match the response,
  not strongly-typed proto fields.  Acceptable given Robot's text-first
  nature.  Mitigated since 1.2 by the
  [Robot resource generator](https://github.com/test-fullautomation/python-microservice-base/blob/develop/MicroserviceBase/MicroserviceManagerGUI/docs/md/robot_generator.md)
  which emits one typed keyword per RPC on top of `GrpcClient`, giving
  tests `Com Setup Device Service Set Interface Type    conn=device
  type=0` instead of a raw `send_cmd` string.

### Neutral

- The Manager GUI's API Explorer remains useful for *interactive*
  ad-hoc calls — Robot is for *scripted* tests.  Different tools,
  different jobs.
- The `MicroserviceBaseLibrary` mentioned in v1.0 of this ADR is
  **not** going to be built; the same job is done by `GrpcClient` +
  the existing QConnectBase keywords.

## Alternatives Considered

### 1. Bespoke `MicroserviceBaseLibrary` keyword library *(v1.0 of this ADR — superseded)*

A Python package exporting Robot keywords like `Connect To Service`,
`Call Method`, `Stream Telemetry For` etc., wrapping `LocalProtoClient`
internally.

Rejected because:
- Reinvents the threading + queue + regex-match infrastructure that
  QConnectBase already ships.
- Introduces a *new* keyword vocabulary that testers would have to
  learn alongside the QConnectBase one they already know.
- Splits the test-client story across two libraries (one for
  RabbitMQ-era services, one for gRPC-era services).

### 2. pytest + custom fixtures (Acceptable but worse)

Engineers can write integration tests in pytest using gRPC clients
directly.

Worse because:
- Not accessible to non-developer testers.
- No standard reporting format usable by stakeholders.
- Each project reinvents fixtures for service connection / Consul
  resolution.

### 3. xUnit-family in C++ (Rejected for integration tests)

Fine for unit tests inside a C++ service.  Wrong tool for cross-service
integration tests where the test author isn't the service author.

### 4. Custom DSL (Rejected)

Could write a microservice-base-specific test DSL.

Rejected because:
- Robot Framework is already a mature DSL with most of what we need.
- Bosch testers already know Robot.
- Inventing a DSL is a multi-quarter project.

### 5. Cucumber / Gherkin (Rejected)

Similar value proposition to Robot.

Rejected because:
- Less ecosystem support for gRPC clients in Cucumber.
- TA reference uses Robot — consistency wins.

## References

- Reference architecture:
  [`taf_repo_proposal`](https://github.boschdevcloud.com/BITS-Test-Automation-Solutions/taf_repo_proposal)
- Robot Framework: <https://robotframework.org/>
- QConnectBase library: <https://github.com/test-fullautomation/QConnectBase>
- New gRPC connection type:
  `QConnectBase/grpc/grpc_client.py` (upstream PR pending) —
  subclasses `ConnectionBase`, uses `MicroserviceBase.adapters.grpc_bridge`.
- [ADR-028 gRPC + reflection as primary RPC](028-grpc-reflection-primary-rpc.md) — `GrpcClient` reuses the reflection client this ADR established.
- [ADR-023 Multi-node Consul cluster](023-multi-node-consul-cluster.md) — `GrpcClient`'s Consul-resolved mode talks to this cluster.
