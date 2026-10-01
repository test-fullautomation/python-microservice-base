*** Settings ***
Documentation     Hand-written keywords for the ``hello`` service.
...
...               They build on the generated ``hello/hello_service.resource``.
...               Keep project keywords here, not in the generated file: an
...               export regenerates that file (and refuses to overwrite it once
...               it has been edited), while this file is never touched.
Resource          hello/hello_service.resource

*** Variables ***
${HELLO}              hello_service
${HELLO_SERVICE}      hello
# Copied protos -- only used when the service has no server reflection.
${HELLO_PROTO_DIR}    ${CURDIR}/../proto/hello

*** Keywords ***
Open Hello Connection
    [Documentation]    Resolve ``${HELLO_SERVICE}`` through Consul (``${CONSUL_ADDR}``,
    ...                from config/robot_config.jsonp) and open the connection.
    Hello Service Open Connection    ${HELLO}
    ...    service_name=${HELLO_SERVICE}    consul_addr=${CONSUL_ADDR}    proto_dir=${HELLO_PROTO_DIR}

Close Hello Connection
    Run Keyword And Ignore Error    Hello Service Close Connection    ${HELLO}

Greeting Should Address
    [Documentation]    Greet ``${name}`` and check the reply ends with ``, <expected_name>!``.
    ...
    ...                Only the ending is checked: the prefix is deployment
    ...                configuration (HELLO_GREETING) -- "Hello" by default,
    ...                "Hello from instance 0" in examples/demo.nomad.hcl.
    [Arguments]    ${name}    ${expected_name}=${name}
    ${res}=    Hello Service Greet    ${HELLO}    name=${name}
    Should End With    ${res}[message]    , ${expected_name}!
    RETURN    ${res}[message]

Echo Should Round Trip
    [Documentation]    Echo ``${payload}`` and check it comes back unchanged.
    [Arguments]    ${payload}
    ${res}=    Hello Service Echo    ${HELLO}    payload=${payload}
    Should Be Equal    ${res}[payload]    ${payload}

Collect Ticks
    [Documentation]    Run the server-streaming Tick RPC and return its events.
    ...                The call returns once the stream ends, so keep ``count`` finite.
    [Arguments]    ${count}    ${interval_ms}=0
    ${res}=    Hello Service Tick    ${HELLO}    count=${count}    interval_ms=${interval_ms}
    Should Be True    ${res}[streaming]
    Should Not Be True    ${res}[truncated]    The stream was truncated by the collection limit
    RETURN    ${res}[events]
