#pragma once

#include <grpcpp/grpcpp.h>
#include "test_service.grpc.pb.h"
#include "domain/TestServiceService.h"

namespace test_service {

class TestServiceGrpcAdapter final : public test_service::v1::TestServiceService::Service {
public:
    explicit TestServiceGrpcAdapter(TestServiceService& domain) : m_domain(domain) {}

    grpc::Status Echo(grpc::ServerContext*,
        const test_service::v1::EchoRequest*,
        test_service::v1::EchoResponse*) override;

    grpc::Status Add(grpc::ServerContext*,
        const test_service::v1::AddRequest*,
        test_service::v1::AddResponse*) override;

private:
    TestServiceService& m_domain;
};

}  // namespace test_service
