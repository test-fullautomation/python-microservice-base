*** Settings ***
Documentation     Starter suite for the ``hello`` service.
...               Created by Microservice Manager and never overwritten by it: edit freely.
...               Run from the project root:  python -m robot -d results testsuites/hello_smoke.robot
Library           RobotFramework_TestsuitesManagement    WITH NAME    testsuites
Resource          ../resources/hello/hello_service.resource
Suite Setup       Open Service Connections
Suite Teardown    Close Service Connections

*** Variables ***
# CONSUL_ADDR normally comes from config/robot_config.jsonp (params.global);
# this value is only the fallback.
${CONSUL_ADDR}      http://127.0.0.1:8500
${SERVICE_NAME}     hello
# The service's protos, copied into the project; used when it has no server reflection.
${PROTO_DIR}        ${CURDIR}/../proto/hello

*** Test Cases ***
hello Is Reachable
    [Documentation]    The suite setup resolved the service through Consul and opened
    ...                a connection; replace this with real checks.
    No Operation
    # Example -- call Greet, then check the result:
    # ${res}=    Hello Service Greet    hello_service    name=<string>
    # Log    ${res}

*** Keywords ***
Open Service Connections
    testsuites.testsuite_setup
    Hello Service Open Connection    hello_service
    ...    service_name=${SERVICE_NAME}    consul_addr=${CONSUL_ADDR}    proto_dir=${PROTO_DIR}

Close Service Connections
    Run Keyword And Ignore Error    Hello Service Close Connection    hello_service
    testsuites.testsuite_teardown
