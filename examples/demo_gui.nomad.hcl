#  Demo job: a service WITH a GUI.
#
#  Runs the hello_service sample under Nomad as "hello-gui" and tells the
#  Manager GUI which plugin to show for it (HELLO_GUI -> Consul Meta.gui).
#  Selecting the service in the Manager GUI's Services view then opens the
#  panel shipped in
#      MicroserviceBase/MicroserviceManagerGUI/web/services/HelloService1.0.0/
#  instead of the runtime card. Runs alongside examples/demo.nomad.hcl
#  (service "hello", no GUI) so both cases can be shown side by side.
#
#  Run from the repo root; `repo` is the one setting without a default:
#      nomad job run -var repo=<path-to-this-repository> examples/demo_gui.nomad.hcl
#      nomad job run -var repo=<path-to-this-repository> -var consul_addr=http://127.0.0.1:8501 examples/demo_gui.nomad.hcl
#      nomad job stop -purge demo-gui
#
#  Prerequisites: same as demo.nomad.hcl.

variable "python" {
  description = "Interpreter with MicroserviceBase installed."
  type        = string
  default     = "C:/Program Files/RobotFramework/python3/python.exe"
}

variable "repo" {
  description = "Checkout of python-microservice-base (forward slashes, no spaces)."
  type        = string
  # Placeholder: set it with -var repo=... or replace it before submitting.
  default     = "<path-to-this-repository>"
}

variable "consul_addr" {
  description = "Consul HTTP API the service registers with."
  type        = string
  default     = "http://127.0.0.1:8500"
}

variable "gui" {
  description = "GUI plugin folder under the Manager GUI's web/services/."
  type        = string
  default     = "HelloService1.0.0"
}

job "demo-gui" {
  datacenters = ["dc1"]
  type        = "service"

  group "hello-gui" {
    count = 1

    network {
      port "grpc" {}
    }

    task "hello-gui" {
      driver = "raw_exec"

      config {
        command = var.python
        args    = ["${var.repo}/examples/hello_service/main.py"]
      }

      env {
        PYTHONPATH       = "${var.repo}/examples/hello_service"
        PYTHONUNBUFFERED = "1"

        HELLO_SERVICE_NAME   = "hello-gui"
        HELLO_GRPC_PORT      = "${NOMAD_PORT_grpc}"
        HELLO_ADVERTISE_ADDR = "127.0.0.1"
        HELLO_CONSUL_ADDR    = var.consul_addr
        HELLO_GREETING       = "Hello from the GUI-enabled instance"
        HELLO_LOG_LEVEL      = "INFO"

        # Registered as Consul Meta.gui; the Manager GUI loads
        # web/services/<gui>/ when this service is selected.
        HELLO_GUI = var.gui
      }

      resources {
        cpu    = 100
        memory = 128
      }
    }
  }
}
