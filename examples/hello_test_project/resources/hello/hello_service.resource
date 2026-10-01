*** Settings ***
Documentation     Auto-generated Robot resource for the Hello Service gRPC service.
...               Source proto: hello.proto
...               Generated:    2026-09-15
...               DO NOT EDIT — regenerate via ``python -m MicroserviceBase.tools.robot_gen``
...               or the Manager GUI's "Generate Robot resources" button.
Library           QConnectBase.ConnectionManager    WITH NAME    conn_manager
Library           Collections

*** Variables ***
${HELLO_SERVICE_FQN}    hello.v1.HelloService

*** Keywords ***
Hello Service Open Connection
    [Documentation]    Open a QConnectBase GrpcClient connection to Hello Service.
    ...                Pass either ``target`` (direct host:port) OR
    ...                ``service_name`` + ``consul_addr`` (Consul lookup).
    ...                ``proto_dir`` is only needed when the server lacks
    ...                server reflection (typical for C++ services without
    ...                grpc++_reflection compiled in).
    ...
    ...                Named ``Open Connection`` (not ``Connect``) so the
    ...                helper can't collide with a proto-defined
    ...                ``Connect()`` RPC on the same service.
    [Arguments]    ${conn_name}    ${target}=${EMPTY}    ${service_name}=${EMPTY}
    ...            ${consul_addr}=${EMPTY}    ${proto_dir}=${EMPTY}
    ...            ${timeout_seconds}=30.0
    &{conf}=    Create Dictionary
    ...    conn_type=GrpcClient
    ...    target=${target}
    ...    service_name=${service_name}
    ...    consul_addr=${consul_addr}
    ...    full_service_name=${HELLO_SERVICE_FQN}
    ...    proto_dir=${proto_dir}
    ...    timeout_seconds=${timeout_seconds}
    conn_manager.connect    conn_name=${conn_name}    conn_conf=${conf}

Hello Service Close Connection
    [Documentation]    Close the Hello Service connection opened by ${conn_name}.
    ...                Named ``Close Connection`` so it can't collide with
    ...                a proto-defined ``Disconnect()`` RPC.
    [Arguments]    ${conn_name}
    conn_manager.disconnect    ${conn_name}

Hello Service Greet
    [Documentation]    Call hello.v1.HelloService.Greet.
    ...                Request fields: name:string
    ...                Returns: string
    [Arguments]    ${conn_name}    ${name}
    &{args}=    Create Dictionary    name=${name}
    ${cmd}=    Evaluate    json.dumps({"method":"Greet","args":${args}})    json
    ${res}=    conn_manager.verify    conn_name=${conn_name}    send_cmd=${cmd}
    RETURN    ${res}

Hello Service Echo
    [Documentation]    Call hello.v1.HelloService.Echo.
    ...                Request fields: payload:string
    ...                Returns: string
    [Arguments]    ${conn_name}    ${payload}
    &{args}=    Create Dictionary    payload=${payload}
    ${cmd}=    Evaluate    json.dumps({"method":"Echo","args":${args}})    json
    ${res}=    conn_manager.verify    conn_name=${conn_name}    send_cmd=${cmd}
    RETURN    ${res}

Hello Service Tick
    [Documentation]    Call server-streaming hello.v1.HelloService.Tick.
    ...                Request fields: count:int32, interval_ms:int32
    ...                Returns: list of int32 events
    ...
    ...                NOTE: server-streaming RPCs are surfaced as a single
    ...                ``conn_manager.verify`` call.  QConnectBase's GrpcClient
    ...                currently buffers the entire response stream into a list;
    ...                long-running streams may block.  For incremental delivery
    ...                use the lower-level ``wait_4_trace`` keyword directly.
    [Arguments]    ${conn_name}    ${count}    ${interval_ms}
    &{args}=    Create Dictionary    count=${count}    interval_ms=${interval_ms}
    ${cmd}=    Evaluate    json.dumps({"method":"Tick","args":${args}})    json
    ${res}=    conn_manager.verify    conn_name=${conn_name}    send_cmd=${cmd}
    RETURN    ${res}

