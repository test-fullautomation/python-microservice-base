*** Settings ***
Documentation     API tests for the ``hello`` service, written on top of the
...               generated keywords (see resources/hello_keywords.resource).
...
...               Run from the project root:  python -m robot -d results testsuites
Library           RobotFramework_TestsuitesManagement    WITH NAME    testsuites
Resource          ../resources/hello_keywords.resource
Suite Setup       Run Keywords    testsuites.testsuite_setup    AND    Open Hello Connection
Suite Teardown    Run Keywords    Close Hello Connection    AND    testsuites.testsuite_teardown
Test Tags         hello    api

*** Test Cases ***
Greet Addresses The Caller By Name
    [Tags]    smoke
    Greeting Should Address    PO

Greet Falls Back To World For A Blank Name
    Greeting Should Address    ${EMPTY}        world
    Greeting Should Address    ${SPACE * 3}    world

Echo Returns The Payload Unchanged
    [Template]    Echo Should Round Trip
    plain text
    Xin chào ✓
    {"nested": [1, 2, 3]}
    ${EMPTY}

Tick Streams The Requested Events In Order
    [Tags]    stream
    ${events}=    Collect Ticks    3
    Length Should Be    ${events}    3
    FOR    ${index}    ${event}    IN ENUMERATE    @{events}
        Should Be Equal As Integers    ${event}[sequence]    ${index}
        Should Be Equal    ${event}[message]    tick #${index}
    END
