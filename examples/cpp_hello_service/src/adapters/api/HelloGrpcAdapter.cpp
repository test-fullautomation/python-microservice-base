#include "HelloGrpcAdapter.h"

#include <chrono>
#include <thread>

namespace hello {

grpc::Status HelloGrpcAdapter::Greet(grpc::ServerContext*,
                                     const hello::v1::GreetRequest* request,
                                     hello::v1::GreetResponse* response) {
    response->set_message(m_domain.greet(request->name()));
    return grpc::Status::OK;
}

grpc::Status HelloGrpcAdapter::Echo(grpc::ServerContext*,
                                    const hello::v1::EchoRequest* request,
                                    hello::v1::EchoResponse* response) {
    response->set_payload(m_domain.echo(request->payload()));
    return grpc::Status::OK;
}

grpc::Status HelloGrpcAdapter::Tick(grpc::ServerContext* ctx,
                                    const hello::v1::TickRequest* request,
                                    grpc::ServerWriter<hello::v1::TickEvent>* writer) {
    const int count = request->count();
    const int interval_ms = request->interval_ms() > 0 ? request->interval_ms() : 1000;
    int seq = 0;
    while (count == 0 || seq < count) {
        if (ctx->IsCancelled()) break;
        hello::v1::TickEvent ev;
        ev.set_sequence(seq);
        ev.set_message("tick #" + std::to_string(seq));
        if (!writer->Write(ev)) break;
        ++seq;
        if (interval_ms > 0)
            std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
    }
    return grpc::Status::OK;
}

}  // namespace hello
