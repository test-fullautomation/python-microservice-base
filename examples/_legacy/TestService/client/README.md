# TestService Client

C++ gRPC client for the `test_service` service.

## Quick start

```bash
# 1. Generate stubs (one time, from the project root)
cd proto
generate_stubs.bat        # Windows
./generate_stubs.sh       # Linux
cd ..

# 2. Build the client
cd client
mkdir build && cd build
cmake -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake ..
cmake --build . --config Release

# 3. Run
test_service_client test_service               # Consul discovery
test_service_client --direct host:port  # direct connection
```

Proto stubs are shared with the service from `../proto/`.
Uses `ServiceClient<TestServiceService>` from MicroserviceBase runtime for
automatic Consul discovery and channel management.
