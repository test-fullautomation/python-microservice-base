#  Nomad job spec for the hello_service sample.
#
#  This file tells Nomad how to launch the Python service and what env vars
#  to set.  The service itself registers with Consul on startup via
#  ServiceRunner, so no service block is needed here (though you can add one
#  for Nomad-native Consul integration if you prefer).
#
#  Submit from the GUI: Nomad tab -> Submit Job -> paste this file.
#  Or from the command line:
#      nomad job run hello.nomad.hcl
#
#  Prerequisites:
#    - Consul agent running on http://127.0.0.1:8500
#    - Nomad agent running in dev mode
#    - MicroserviceBase installed in the Python interpreter below
#    - proto stubs generated: python scripts/generate_protos.py

job "hello" {
  datacenters = ["dc1"]
  type        = "service"

  group "hello" {
    count = 1

    # Dynamic port allocation — Nomad picks a free port and injects it as
    # NOMAD_PORT_grpc / NOMAD_IP_grpc into the task's environment.
    network {
      port "grpc" {}
    }

    task "server" {
      driver = "raw_exec"

      config {
        # Pin the Python interpreter explicitly — Nomad's PATH may not
        # resolve `python` to the one where grpcio/pika/MicroserviceBase
        # are installed.  Change this path if your install lives elsewhere.
        command = "C:/Program Files/RobotFramework/python3/python.exe"
        args    = [
          "D:/Project/robot/github/microsoft-base-develop/examples/hello_service/main.py"
        ]
      }

      env {
        # Ensure Python can resolve sibling modules (context.py, domain/, ...)
        # regardless of the cwd Nomad chose for the alloc.  main.py also
        # prepends its own directory to sys.path, but setting PYTHONPATH is
        # a belt-and-braces fallback for tools that import main as a module.
        PYTHONPATH = "D:/Project/robot/github/microsoft-base-develop/examples/hello_service"

        # ServiceRunner reads these via HelloSettings (prefix HELLO_).
        HELLO_GRPC_PORT      = "${NOMAD_PORT_grpc}"
        # Advertise 127.0.0.1 instead of ${NOMAD_IP_grpc} — Consul's gRPC
        # health check must be able to reach this address.  On a single
        # machine with `consul agent -dev`, localhost is the safest bet;
        # ${NOMAD_IP_grpc} sometimes resolves to an interface that Consul
        # can't contact, which causes Consul to mark the service critical
        # and our DeregisterCriticalServiceAfter=1m setting cleans it up.
        HELLO_ADVERTISE_ADDR = "127.0.0.1"
        HELLO_CONSUL_ADDR    = "http://127.0.0.1:8500"
        HELLO_GREETING       = "Hello"
        HELLO_LOG_LEVEL      = "INFO"
      }

      resources {
        cpu    = 100   # MHz
        memory = 128   # MB
      }
    }
  }
}
