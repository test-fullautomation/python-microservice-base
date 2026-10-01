# hello_test_project — sample test project

A Robot Framework AIO test project for the
[`hello_service`](../hello_service/README.md) example.

Most of it was created by the Manager GUI's **Add to test project** export —
exactly the files you get when you export a service yourself. On top of that
sit a hand-written keyword resource and an API test suite, showing where your
own work goes.

## What's in it

| Path | Kind | Owned by |
|---|---|---|
| `testproject.json` | manifest | the tool — runner, layout, what was exported (with content hashes) |
| `resources/hello/hello_service.resource` | generated | the tool — one typed keyword per RPC; **don't edit** |
| `proto/hello/hello.proto` | generated | the tool — copied from `examples/hello_service/proto/` |
| `testsuites/config/robot_config.jsonp` | starter | you — RF AIO configuration; `CONSUL_ADDR` lives here |
| `testsuites/hello_smoke.robot` | starter | you — created once by the export, as generated |
| `resources/hello_keywords.resource` | hand-written | you — project keywords on top of the generated ones |
| `testsuites/hello_api.robot` | hand-written | you — the actual API tests |

That split is what makes regeneration safe. When the service API changes, an
export rewrites only the generated files, and only if they were not edited.
Starter and hand-written files are never touched.

## Run it

You need:

- the RF AIO Python interpreter (`robot`, `QConnectBase`,
  `RobotFramework_TestsuitesManagement`);
- Consul, with the `hello` service running and registered as `hello`.

1. Start `hello`, for example from the repository root:

    ```bash
    nomad job run -var repo=<path-to-this-repository> examples/demo.nomad.hcl
    ```

    or run it directly as described in the
    [`hello_service` README](../hello_service/README.md).

2. If Consul is not on `http://127.0.0.1:8500`, change `CONSUL_ADDR` in
   `testsuites/config/robot_config.jsonp`. RF AIO loads that file on its own
   (configuration level 3) and makes the value available as `${CONSUL_ADDR}`.

3. From this folder, with the RF AIO interpreter:

    ```bash
    python -m robot -d results testsuites                  # all 5 tests
    python -m robot -d results --include smoke testsuites  # just the greeting check
    ```

    Reports land in `results/` (ignored by git).

The suites find `hello` through Consul by service name, never by host and
port, so they keep working when Nomad places the service on a new port.

## What the tests show

- **Unary calls return a dictionary** of the response fields:
  `${res}[message]`, `${res}[payload]`.
- **Server-streaming calls** (`Tick`) return once the stream has ended, as
  `{streaming, events, truncated}`; each event is a dictionary
  (`${event}[sequence]`, `${event}[message]`).
- **Data-driven tests** use `[Template]` (`Echo Returns The Payload Unchanged`),
  including Unicode and empty payloads.
- **Assertions tolerate deployment configuration.** The greeting prefix comes
  from `HELLO_GREETING`: `demo.nomad.hcl` answers `Hello from instance 0, PO!`,
  a plain run answers `Hello, PO!`. So `Greeting Should Address` checks only
  the ending.

## Regenerate after the API changes

**From the Manager GUI:** *Developer Tools → Open test project…* → choose this
folder, select `hello` in the Services view, then *Add to test project*. The
plan lists every file:

- **update** — generated and unedited, so it will be regenerated;
- **unchanged** — already identical;
- **edited locally** — left alone unless you allow overwriting;
- **kept** — starter files, never overwritten.

Hand-written files are not part of the export at all.

**Scripted,** from the repository root:

```python
from MicroserviceBase.adapters import test_project as tp

proto = "examples/hello_service/proto/hello.proto"
files, warnings = tp.collect_proto_set(proto)
plan = tp.export_service(
    "examples/hello_test_project", "hello",
    consul_addr="http://127.0.0.1:8500",
    grpc_services=["hello.v1.HelloService"],
    proto_files=files, source={"kind": "proto", "path": proto},
)  # add apply=True to write
for f in plan["files"]:
    print(f"{f['status']:<10} {f['path']}")
```
