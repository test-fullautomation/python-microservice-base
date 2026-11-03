// RabbitMQConnection.h — Cross-platform RAII wrapper around rabbitmq-c.
//
// Extracted from cpp_mfc_service_template, with MFC/Windows dependencies removed.

#pragma once

#include <string>
#include <cstdint>
#include <sstream>

#include <amqp.h>
#include <amqp_tcp_socket.h>

// Consumed message from the broker.
struct ConsumedMessage {
    bool        received = false;   // true if a message was received
    std::string body;
    std::string reply_to;
    std::string correlation_id;
    uint64_t    delivery_tag = 0;
};

class RabbitMQConnection {
public:
    RabbitMQConnection();
    ~RabbitMQConnection();

    // Non-copyable.
    RabbitMQConnection(const RabbitMQConnection&) = delete;
    RabbitMQConnection& operator=(const RabbitMQConnection&) = delete;

    // Connect to RabbitMQ broker.
    bool Connect(const std::string& host, int port,
                 const std::string& vhost = "/",
                 const std::string& user  = "guest",
                 const std::string& pass  = "guest");

    // Declare an exchange.
    bool DeclareExchange(const std::string& name, const std::string& type,
                         bool durable = false);

    // Declare a queue. Returns the queue name (useful for server-named queues).
    std::string DeclareQueue(const std::string& name, bool durable = false,
                             bool exclusive = false, bool auto_delete = false);

    // Purge all messages from a queue.
    bool PurgeQueue(const std::string& name);

    // Bind a queue to an exchange with a routing key.
    bool BindQueue(const std::string& queue, const std::string& exchange,
                   const std::string& routing_key);

    // Set prefetch count (QoS).
    bool SetPrefetch(int count);

    // Start consuming from a queue (register consumer).
    bool StartConsume(const std::string& queue);

    // Publish a message.
    bool Publish(const std::string& exchange, const std::string& routing_key,
                 const std::string& body, int delivery_mode = 0,
                 const std::string& correlation_id = "",
                 const std::string& reply_to = "");

    // Consume one message with timeout (seconds). Non-blocking if timeout=0.
    ConsumedMessage ConsumeOne(int timeout_sec = 1);

    // Acknowledge a message.
    bool Ack(uint64_t delivery_tag);

    // Close and destroy the connection.
    void Disconnect();

    // Check if connected.
    bool IsConnected() const { return m_connected; }

    // Get last error message.
    const std::string& GetLastError() const { return m_lastError; }

private:
    bool CheckRpcReply(const std::string& context, amqp_rpc_reply_t reply);
    bool CheckStatus(const std::string& context, int status);

    amqp_connection_state_t m_conn       = nullptr;
    amqp_socket_t*          m_socket     = nullptr;
    amqp_channel_t          m_channel    = 1;
    bool                    m_connected  = false;
    std::string             m_lastError;
};
