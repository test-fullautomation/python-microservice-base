#  Demo job: the bench of the Manager GUI, on live services.
#
#  Starts the two services the "ara demo bench" composition needs, next to
#  the climate chamber that is already running:
#
#    signals   the mocked signal cluster (signal-in, signal-out,
#              signal-proc-foo-bar and signal-discovery) that Graph Studio's
#              run_cluster.py starts. Nomad registers signal-discovery in
#              Consul, so the GUI finds the live signals by itself, and its
#              Meta.gui names the component that shows them.
#    hello     examples/hello_service: a form, a streamed log and the
#              sandboxed HTML panel.
#
#  It runs on the demo cluster (taf_repo_proposal, nomad/jobs/
#  demo_cluster.nomad), whose server listens on http://127.0.0.1:4746 --
#  not on the bootstrap agent the GUI starts.
#
#  One setting is yours: base_repo, where this repository is checked out
#  (forward slashes, no spaces). The taf_repo_proposal checkout comes from
#  the node itself (meta.repo_root, which demo_cluster.nomad sets on every
#  client), so nothing else names a local path.
#
#  In the Manager GUI: Nomad -> Connect to Existing Cluster ->
#  http://127.0.0.1:4746 -> Submit Job -> this file, replace the
#  <path-to-this-repository> placeholder below with your checkout, Submit.
#  From a terminal:
#
#      nomad job run -address=http://127.0.0.1:4746 \
#          -var base_repo=<path-to-this-repository> examples/ara_demo.nomad.hcl
#      nomad job stop -address=http://127.0.0.1:4746 -purge ara-demo
#
#  The walkthrough is in
#  MicroserviceBase/MicroserviceManagerGUI/docs/md/bench_demo.md.
#
#  Both groups run on client1, so every service of the demo registers in
#  the same Consul agent (127.0.0.1:8500).

variable "base_repo" {
  description = "python-microservice-base checkout (hello service, run_cluster.py), forward slashes, no spaces"
  type        = string
  # Placeholder: a job submitted with it unchanged fails its tasks with
  # "can't open file '<path-to-this-repository>/...'" in the task log.
  default = "<path-to-this-repository>"
}

variable "python" {
  description = "Interpreter with MicroserviceBase and the signals dependencies (RobotFramework AIO's by default)"
  type        = string
  default     = "C:/Program Files/RobotFramework/python3/python.exe"
}

variable "consul_addr" {
  description = "Consul agent of the node the demo runs on"
  type        = string
  default     = "http://127.0.0.1:8500"
}

variable "sweep" {
  description = <<-EOD
    Sweep the setpoint 0 -> 5 V and back, so the bench has a moving output.
    Switch it off while a test drives the setpoint itself (the flow runner
    demo): -var sweep=false, or set the default to false in the GUI's
    Submit Job box. Resubmitting updates the job in place.
    EOD
  type        = bool
  default     = true
}

job "ara-demo" {
  datacenters = ["*"]
  type        = "service"

  constraint {
    attribute = "${node.unique.name}"
    value     = "client1"
  }

  # ---------------------------------------------------------------- signals
  group "signals" {
    count = 1

    network {
      port "discovery" { static = 50210 }
      port "signal_in" { static = 50200 }
      port "signal_out" { static = 50201 }
      port "signal_proc" { static = 50202 }
    }

    # Nomad registers it; the GUI's bridge looks signal-discovery up in
    # Consul and streams from the graph services it names.
    service {
      name = "signal-discovery"
      port = "discovery"
      # Loopback, like the rest of the demo: the host address would send the
      # GUI's gRPC through the corporate HTTP proxy, which refuses it.
      address  = "127.0.0.1"
      provider = "consul"
      tags     = ["signals", "discovery", "sim"]
      meta {
        gui = "SignalBench1.0.0"
      }
    }

    task "cluster" {
      driver = "raw_exec"
      config {
        command = var.python
        args = ["${var.base_repo}/MicroserviceBase/MicroserviceManagerGUI/graph-studio/tools/run_cluster.py",
          "--signals-root", "${node.meta.repo_root}/services/signals",
        "--all", "--discovery-port", "50210"]
      }
      env {
        PYTHONUTF8       = "1"
        PYTHONUNBUFFERED = "1"
      }
      kill_timeout = "15s"
      resources {
        cpu    = 500
        memory = 512
      }
    }

    # Without a writer the setpoint stays at 0 V and its strip is a flat
    # line. This sweeps it 0 -> 5 V and back, once a minute, so the bench
    # shows the output following the command. Only while var.sweep is on:
    # a test that writes the setpoint must be its only writer.
    dynamic "task" {
      for_each = var.sweep ? ["sweep"] : []
      labels   = ["sweep"]
      content {
        driver = "raw_exec"
        config {
          command = var.python
          args    = ["local/sweep.py"]
        }
        template {
          destination = "local/sweep.py"
          data        = <<-EOP
          """Triangle sweep of bench.dut.setpoint.voltage_V, 0 -> 5 V -> 0,
          one period a minute, so the demo bench has a moving output."""
          import os, sys, time
          sys.path.insert(0, os.environ["SIGNALS_ROOT"])
          import grpc
          from proto import signal_pb2, signal_pb2_grpc

          NAME = "bench.dut.setpoint.voltage_V"
          STEP, PERIOD, TOP = 0.5, 60.0, 5.0
          stub = signal_pb2_grpc.SignalQueryServiceStub(
              grpc.insecure_channel("127.0.0.1:50201"))
          while True:
              t = (time.time() % PERIOD) / PERIOD          # 0 .. 1
              v = TOP * (2 * t if t < 0.5 else 2 * (1 - t))  # up, then down
              try:
                  stub.SetSignal(signal_pb2.SetSignalRequest(name=NAME, value=v),
                                 timeout=5)
              except grpc.RpcError as exc:                    # graph restarting
                  print("set failed:", exc.code(), flush=True)
              time.sleep(STEP)
        EOP
        }
        env {
          PYTHONUNBUFFERED = "1"
          # Node meta is interpolated in env, not in template text.
          SIGNALS_ROOT = "${node.meta.repo_root}/services/signals"
        }
        kill_timeout = "5s"
        resources {
          cpu    = 100
          memory = 128
        }
      }
    }
  }

  # ------------------------------------------------------------------ hello
  group "hello" {
    count = 1

    network {
      port "grpc" {}
    }

    task "hello" {
      driver = "raw_exec"
      config {
        command = var.python
        args    = ["${var.base_repo}/examples/hello_service/main.py"]
      }
      env {
        PYTHONPATH           = "${var.base_repo}/examples/hello_service;${var.base_repo}"
        PYTHONUNBUFFERED     = "1"
        HELLO_SERVICE_NAME   = "hello-demo"
        HELLO_GRPC_PORT      = "${NOMAD_PORT_grpc}"
        HELLO_ADVERTISE_ADDR = "127.0.0.1"
        HELLO_CONSUL_ADDR    = var.consul_addr
        HELLO_GUI            = "HelloService1.0.0"
      }
      kill_timeout = "10s"
      resources {
        cpu    = 200
        memory = 256
      }
    }
  }
}
