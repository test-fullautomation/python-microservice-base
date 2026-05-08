# Nomad job spec for TestService.
#
# Submit from the GUI:  Service Network > Nomad > Submit Job
# Or from the CLI:     nomad job run test_service.nomad.hcl
#
# Fields:
#   datacenters  — which Nomad datacenter(s) can run this job
#   driver       — raw_exec: direct process, no isolation
#                  exec: chroot isolation (Linux only)
#                  docker: container-based
#   port "grpc"  — dynamic port; Nomad picks a free one and
#                  injects it as NOMAD_PORT_grpc
#   resources    — cpu (MHz) and memory (MB) limits

job "test_service" {
  datacenters = ["dc1"]
  type        = "service"

  group "test_service" {
    count = 1

    network {
      port "grpc" {}  # dynamic port allocation
    }

    task "server" {
      driver = "raw_exec"

      config {
        command = "D:\Project\robot\github\microsoft-base-develop\examples\TestService\dist-msys2\test_service.exe"
      }

      env {
        TEST_SERVICE_GRPC_PORT      = "${NOMAD_PORT_grpc}"
        TEST_SERVICE_ADVERTISE_ADDR = "127.0.0.1"
        TEST_SERVICE_CONSUL_ADDR    = "http://127.0.0.1:8501"
        TEST_SERVICE_LOG_LEVEL      = "INFO"
      }

      resources {
        cpu    = 100   # MHz
        memory = 128   # MB
      }
    }
  }
}
