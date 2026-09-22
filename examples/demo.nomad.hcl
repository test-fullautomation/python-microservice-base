#  Demo job: runs the hello_service sample under Nomad so there is something
#  for Consul to list and for the Manager GUI to discover.
#
#  Two instances by default, each on a Nomad-assigned port, both registered
#  in Consul under the service name "hello" (distinct instance IDs) -- enough
#  to show discovery, dynamic ports and scaling in one job.
#
#  Run from the repo root:
#      nomad job run examples/demo.nomad.hcl
#      nomad job run -var count=1 examples/demo.nomad.hcl
#      nomad job run -var python="C:/Python313/python.exe" examples/demo.nomad.hcl
#      nomad job stop -purge demo
#
#  Or paste it into the Manager GUI: Administrator Tools -> Nomad agent
#  -> Submit Job.
#
#  Prerequisites:
#    - consul agent -dev            (http://127.0.0.1:8500)
#    - nomad agent -dev             (raw_exec driver enabled by -dev)
#    - MicroserviceBase installed in the interpreter given by `python`
#    - proto stubs in examples/hello_service/proto (they are checked in)
#
#  The service registers itself with Consul through ServiceRunner, so no
#  Nomad `service` block is needed -- adding one would register it twice.

variable "python" {
  description = "Interpreter with MicroserviceBase installed."
  type        = string
  default     = "C:/Program Files/RobotFramework/python3/python.exe"
}

variable "repo" {
  description = "Checkout of python-microservice-base (forward slashes)."
  type        = string
  default     = "D:/Project/robot/github/microsoft-base-develop"
}

variable "count" {
  description = "How many hello instances to run."
  type        = number
  default     = 2
}

variable "consul_addr" {
  description = "Consul HTTP API the service registers with."
  type        = string
  default     = "http://127.0.0.1:8500"
}

job "demo" {
  datacenters = ["dc1"]
  type        = "service"

  group "hello" {
    count = var.count

    # Nomad picks a free port per instance and injects it as
    # NOMAD_PORT_grpc; the service announces that port to Consul.
    network {
      port "grpc" {}
    }

    task "hello" {
      driver = "raw_exec"

      config {
        # Pinned interpreter: Nomad's PATH may not resolve `python` to the
        # one where grpcio and MicroserviceBase are installed.
        command = var.python
        args    = ["${var.repo}/examples/hello_service/main.py"]
      }

      env {
        # main.py prepends its own directory to sys.path; this is the
        # fallback for anything that imports it as a module.
        PYTHONPATH       = "${var.repo}/examples/hello_service"
        PYTHONUNBUFFERED = "1"   # log lines reach the Nomad alloc log immediately

        # HelloSettings reads these with the HELLO_ prefix.
        HELLO_SERVICE_NAME   = "hello"
        HELLO_GRPC_PORT      = "${NOMAD_PORT_grpc}"
        # 127.0.0.1 rather than ${NOMAD_IP_grpc}: Consul's gRPC health
        # check must reach the address; on a single dev machine loopback
        # is the one that always works.
        HELLO_ADVERTISE_ADDR = "127.0.0.1"
        HELLO_CONSUL_ADDR    = var.consul_addr
        # Per-instance greeting so a client can tell which one answered.
        HELLO_GREETING       = "Hello from instance ${NOMAD_ALLOC_INDEX}"
        HELLO_LOG_LEVEL      = "INFO"
      }

      resources {
        cpu    = 100   # MHz
        memory = 128   # MB
      }
    }
  }
}
