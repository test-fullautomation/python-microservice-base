#include "TestServiceGrpcAdapter.h"

namespace test_service {

grpc::Status TestServiceGrpcAdapter::Echo(
    grpc::ServerContext*,
    const test_service::v1::EchoRequest* request,
    test_service::v1::EchoResponse* response) {
    response->set_result(m_domain.echo(request->message()));
    return grpc::Status::OK;
}

grpc::Status TestServiceGrpcAdapter::Add(
    grpc::ServerContext*,
    const test_service::v1::AddRequest* request,
    test_service::v1::AddResponse* response) {
    response->set_result(m_domain.add(request->a(), request->b()));
    return grpc::Status::OK;
}

}  // namespace test_service
