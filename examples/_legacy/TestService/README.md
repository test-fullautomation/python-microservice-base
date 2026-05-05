# TestService

Sample Test

- **Language:** C++
- **GUI:** Qt Widgets GUI
- **Version:** 1.0.0
- **Group:** Services

## Methods


## Prerequisites

- Consul agent running
- vcpkg with grpc, protobuf, curl

### Build

```bash
mkdir build && cd build
cmake -DCMAKE_TOOLCHAIN_FILE=<vcpkg>/scripts/buildsystems/vcpkg.cmake ..
cmake --build . --config Release
```

### Run

```bash
export TEST_SERVICE_CONSUL_ADDR=http://127.0.0.1:8500
./test_service
```

## Verify

```bash
grpcurl -plaintext <host>:<port> list
```
