// RabbitMQConnection.cpp — Cross-platform RAII wrapper around rabbitmq-c.
//
// Extracted from cpp_mfc_service_template, with MFC/Windows dependencies removed.

#include "RabbitMQConnection.h"

#ifdef _WIN32
#  include <winsock2.h>   // struct timeval
#else
#  include <sys/time.h>   // struct timeval
#endif

#include <amqp.h>
#include <amqp_tcp_socket.h>
#include <amqp_framing.h>

#include <cstring>

// ---------------------------------------------------------------------------
// Construction / destruction
// ---------------------------------------------------------------------------

RabbitMQConnection::RabbitMQConnection() = default;

RabbitMQConnection::~RabbitMQConnection() {
    Disconnect();
}

// ---------------------------------------------------------------------------
// Connect
// ---------------------------------------------------------------------------

bool RabbitMQConnection::Connect(const std::string& host, int port,
                                  const std::string& vhost,
                                  const std::string& user,
                                  const std::string& pass) {
    Disconnect();

    m_conn = amqp_new_connection();
    if (!m_conn) {
        m_lastError = "amqp_new_connection() failed";
        return false;
    }

    m_socket = amqp_tcp_socket_new(m_conn);
    if (!m_socket) {
        m_lastError = "amqp_tcp_socket_new() failed";
        Disconnect();
        return false;
    }

    int rc = amqp_socket_open(m_socket, host.c_str(), port);
    if (rc != AMQP_STATUS_OK) {
        m_lastError = "amqp_socket_open() failed: " + std::string(amqp_error_string2(rc));
        Disconnect();
        return false;
    }

    amqp_rpc_reply_t reply = amqp_login(m_conn, vhost.c_str(),
                                         /*channel_max=*/0,
                                         /*frame_max=*/AMQP_DEFAULT_FRAME_SIZE,
                                         /*heartbeat=*/10,
                                         AMQP_SASL_METHOD_PLAIN,
                                         user.c_str(), pass.c_str());
    if (!CheckRpcReply("amqp_login", reply)) {
        Disconnect();
        return false;
    }

    amqp_channel_open(m_conn, m_channel);
    if (!CheckRpcReply("amqp_channel_open", amqp_get_rpc_reply(m_conn))) {
        Disconnect();
        return false;
    }

    m_connected = true;
    return true;
}

// ---------------------------------------------------------------------------
// DeclareExchange
// ---------------------------------------------------------------------------

bool RabbitMQConnection::DeclareExchange(const std::string& name,
                                          const std::string& type,
                                          bool durable) {
    if (!m_connected) return false;

    amqp_exchange_declare(m_conn, m_channel,
                          amqp_cstring_bytes(name.c_str()),
                          amqp_cstring_bytes(type.c_str()),
                          /*passive=*/0,
                          /*durable=*/durable ? 1 : 0,
                          /*auto_delete=*/0,
                          /*internal=*/0,
                          amqp_empty_table);

    return CheckRpcReply("exchange_declare(" + name + ")", amqp_get_rpc_reply(m_conn));
}

// ---------------------------------------------------------------------------
// DeclareQueue
// ---------------------------------------------------------------------------

std::string RabbitMQConnection::DeclareQueue(const std::string& name,
                                              bool durable,
                                              bool exclusive,
                                              bool auto_delete) {
    if (!m_connected) return "";

    amqp_queue_declare_ok_t* r = amqp_queue_declare(
        m_conn, m_channel,
        name.empty() ? amqp_empty_bytes : amqp_cstring_bytes(name.c_str()),
        /*passive=*/0,
        /*durable=*/durable ? 1 : 0,
        /*exclusive=*/exclusive ? 1 : 0,
        /*auto_delete=*/auto_delete ? 1 : 0,
        amqp_empty_table);

    if (!CheckRpcReply("queue_declare(" + name + ")", amqp_get_rpc_reply(m_conn))) {
        return "";
    }

    return std::string(static_cast<char*>(r->queue.bytes), r->queue.len);
}

// ---------------------------------------------------------------------------
// PurgeQueue
// ---------------------------------------------------------------------------

bool RabbitMQConnection::PurgeQueue(const std::string& name) {
    if (!m_connected) return false;

    amqp_queue_purge(m_conn, m_channel, amqp_cstring_bytes(name.c_str()));
    return CheckRpcReply("queue_purge(" + name + ")", amqp_get_rpc_reply(m_conn));
}

// ---------------------------------------------------------------------------
// BindQueue
// ---------------------------------------------------------------------------

bool RabbitMQConnection::BindQueue(const std::string& queue,
                                    const std::string& exchange,
                                    const std::string& routing_key) {
    if (!m_connected) return false;

    amqp_queue_bind(m_conn, m_channel,
                    amqp_cstring_bytes(queue.c_str()),
                    amqp_cstring_bytes(exchange.c_str()),
                    amqp_cstring_bytes(routing_key.c_str()),
                    amqp_empty_table);

    return CheckRpcReply("queue_bind", amqp_get_rpc_reply(m_conn));
}

// ---------------------------------------------------------------------------
// SetPrefetch
// ---------------------------------------------------------------------------

bool RabbitMQConnection::SetPrefetch(int count) {
    if (!m_connected) return false;

    amqp_basic_qos(m_conn, m_channel,
                    /*prefetch_size=*/0,
                    /*prefetch_count=*/static_cast<uint16_t>(count),
                    /*global=*/0);
    return CheckRpcReply("basic_qos", amqp_get_rpc_reply(m_conn));
}

// ---------------------------------------------------------------------------
// StartConsume
// ---------------------------------------------------------------------------

bool RabbitMQConnection::StartConsume(const std::string& queue) {
    if (!m_connected) return false;

    amqp_basic_consume(m_conn, m_channel,
                       amqp_cstring_bytes(queue.c_str()),
                       amqp_empty_bytes,  // consumer tag (auto-generated)
                       /*no_local=*/0,
                       /*no_ack=*/0,
                       /*exclusive=*/0,
                       amqp_empty_table);

    return CheckRpcReply("basic_consume", amqp_get_rpc_reply(m_conn));
}

// ---------------------------------------------------------------------------
// Publish
// ---------------------------------------------------------------------------

bool RabbitMQConnection::Publish(const std::string& exchange,
                                  const std::string& routing_key,
                                  const std::string& body,
                                  int delivery_mode,
                                  const std::string& correlation_id,
                                  const std::string& reply_to) {
    if (!m_connected) return false;

    amqp_basic_properties_t props;
    memset(&props, 0, sizeof(props));
    props._flags = AMQP_BASIC_CONTENT_TYPE_FLAG;
    props.content_type = amqp_cstring_bytes("application/json");

    if (delivery_mode > 0) {
        props._flags |= AMQP_BASIC_DELIVERY_MODE_FLAG;
        props.delivery_mode = static_cast<uint8_t>(delivery_mode);
    }
    if (!correlation_id.empty()) {
        props._flags |= AMQP_BASIC_CORRELATION_ID_FLAG;
        props.correlation_id = amqp_cstring_bytes(correlation_id.c_str());
    }
    if (!reply_to.empty()) {
        props._flags |= AMQP_BASIC_REPLY_TO_FLAG;
        props.reply_to = amqp_cstring_bytes(reply_to.c_str());
    }

    int rc = amqp_basic_publish(m_conn, m_channel,
                                 amqp_cstring_bytes(exchange.c_str()),
                                 amqp_cstring_bytes(routing_key.c_str()),
                                 /*mandatory=*/0,
                                 /*immediate=*/0,
                                 &props,
                                 amqp_cstring_bytes(body.c_str()));

    return CheckStatus("basic_publish", rc);
}

// ---------------------------------------------------------------------------
// ConsumeOne
// ---------------------------------------------------------------------------

ConsumedMessage RabbitMQConnection::ConsumeOne(int timeout_sec) {
    ConsumedMessage msg;
    if (!m_connected) return msg;

    amqp_envelope_t envelope;
    struct timeval tv;
    tv.tv_sec  = timeout_sec;
    tv.tv_usec = 0;

    amqp_maybe_release_buffers(m_conn);
    amqp_rpc_reply_t reply = amqp_consume_message(m_conn, &envelope,
                                                   &tv, /*flags=*/0);

    if (reply.reply_type == AMQP_RESPONSE_NORMAL) {
        msg.received     = true;
        msg.body         = std::string(static_cast<char*>(envelope.message.body.bytes),
                                       envelope.message.body.len);
        msg.delivery_tag = envelope.delivery_tag;

        // Extract reply_to
        if (envelope.message.properties._flags & AMQP_BASIC_REPLY_TO_FLAG) {
            msg.reply_to = std::string(
                static_cast<char*>(envelope.message.properties.reply_to.bytes),
                envelope.message.properties.reply_to.len);
        }
        // Extract correlation_id
        if (envelope.message.properties._flags & AMQP_BASIC_CORRELATION_ID_FLAG) {
            msg.correlation_id = std::string(
                static_cast<char*>(envelope.message.properties.correlation_id.bytes),
                envelope.message.properties.correlation_id.len);
        }

        amqp_destroy_envelope(&envelope);
    }
    else if (reply.reply_type == AMQP_RESPONSE_LIBRARY_EXCEPTION &&
             reply.library_error == AMQP_STATUS_TIMEOUT) {
        // Timeout — no message, not an error.
        msg.received = false;
    }
    else {
        // Real error.
        CheckRpcReply("consume_message", reply);
        msg.received = false;
    }

    return msg;
}

// ---------------------------------------------------------------------------
// Ack
// ---------------------------------------------------------------------------

bool RabbitMQConnection::Ack(uint64_t delivery_tag) {
    if (!m_connected) return false;
    int rc = amqp_basic_ack(m_conn, m_channel, delivery_tag, /*multiple=*/0);
    return CheckStatus("basic_ack", rc);
}

// ---------------------------------------------------------------------------
// Disconnect
// ---------------------------------------------------------------------------

void RabbitMQConnection::Disconnect() {
    if (m_conn) {
        if (m_connected) {
            amqp_channel_close(m_conn, m_channel, AMQP_REPLY_SUCCESS);
            amqp_connection_close(m_conn, AMQP_REPLY_SUCCESS);
        }
        amqp_destroy_connection(m_conn);
        m_conn      = nullptr;
        m_socket    = nullptr;
        m_connected = false;
    }
}

// ---------------------------------------------------------------------------
// Error helpers
// ---------------------------------------------------------------------------

bool RabbitMQConnection::CheckRpcReply(const std::string& context,
                                        amqp_rpc_reply_t reply) {
    if (reply.reply_type == AMQP_RESPONSE_NORMAL) return true;

    std::ostringstream oss;
    oss << context << ": ";

    switch (reply.reply_type) {
    case AMQP_RESPONSE_NONE:
        oss << "missing RPC reply";
        break;
    case AMQP_RESPONSE_LIBRARY_EXCEPTION:
        oss << amqp_error_string2(reply.library_error);
        break;
    case AMQP_RESPONSE_SERVER_EXCEPTION:
        if (reply.reply.id == AMQP_CONNECTION_CLOSE_METHOD) {
            auto* m = static_cast<amqp_connection_close_t*>(reply.reply.decoded);
            oss << "server connection error " << m->reply_code << ": "
                << std::string(static_cast<char*>(m->reply_text.bytes), m->reply_text.len);
        } else if (reply.reply.id == AMQP_CHANNEL_CLOSE_METHOD) {
            auto* m = static_cast<amqp_channel_close_t*>(reply.reply.decoded);
            oss << "server channel error " << m->reply_code << ": "
                << std::string(static_cast<char*>(m->reply_text.bytes), m->reply_text.len);
        } else {
            oss << "unknown server error, method id=" << reply.reply.id;
        }
        break;
    default:
        oss << "unknown reply type " << reply.reply_type;
        break;
    }

    m_lastError = oss.str();
    return false;
}

bool RabbitMQConnection::CheckStatus(const std::string& context, int status) {
    if (status == AMQP_STATUS_OK) return true;
    m_lastError = context + ": " + amqp_error_string2(status);
    return false;
}
