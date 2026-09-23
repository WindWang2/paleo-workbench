# CLOSURE-AGENT (line 11) tests — oracle conformance against the frozen
# Python agent/harness verdicts, guard-pipeline contracts, session state
# machine e2e (plan -> tool -> result -> audit -> recover), checkpoint
# integrity, events, model transport, and the workflow engine adapter.

add_executable(closure_agent.oracle oracle_test.cpp)
target_compile_features(closure_agent.oracle PRIVATE cxx_std_20)
target_link_libraries(closure_agent.oracle PRIVATE Pwb::ClosureAgent)
target_compile_definitions(closure_agent.oracle PRIVATE
    PWB_CLOSURE_AGENT_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/agent_oracle.json")
add_test(NAME closure_agent.oracle COMMAND closure_agent.oracle)
set_tests_properties(closure_agent.oracle PROPERTIES TIMEOUT 120)

add_executable(closure_agent.executor executor_test.cpp)
target_compile_features(closure_agent.executor PRIVATE cxx_std_20)
target_link_libraries(closure_agent.executor PRIVATE Pwb::ClosureAgent)
add_test(NAME closure_agent.executor COMMAND closure_agent.executor)
set_tests_properties(closure_agent.executor PROPERTIES TIMEOUT 120)

add_executable(closure_agent.session session_test.cpp)
target_compile_features(closure_agent.session PRIVATE cxx_std_20)
target_link_libraries(closure_agent.session PRIVATE Pwb::ClosureAgent)
add_test(NAME closure_agent.session COMMAND closure_agent.session)
set_tests_properties(closure_agent.session PROPERTIES TIMEOUT 300)

add_executable(closure_agent.checkpoint checkpoint_test.cpp)
target_compile_features(closure_agent.checkpoint PRIVATE cxx_std_20)
target_link_libraries(closure_agent.checkpoint PRIVATE Pwb::ClosureAgent)
add_test(NAME closure_agent.checkpoint COMMAND closure_agent.checkpoint)
set_tests_properties(closure_agent.checkpoint PROPERTIES TIMEOUT 120)

add_executable(closure_agent.events events_test.cpp)
target_compile_features(closure_agent.events PRIVATE cxx_std_20)
target_link_libraries(closure_agent.events PRIVATE Pwb::ClosureAgent)
add_test(NAME closure_agent.events COMMAND closure_agent.events)
set_tests_properties(closure_agent.events PROPERTIES TIMEOUT 120)

add_executable(closure_agent.model model_transport_test.cpp)
target_compile_features(closure_agent.model PRIVATE cxx_std_20)
target_link_libraries(closure_agent.model PRIVATE Pwb::ClosureAgent)
add_test(NAME closure_agent.model COMMAND closure_agent.model)
set_tests_properties(closure_agent.model PROPERTIES TIMEOUT 120)

# Phase 4 — Processing algorithm tool conversion (Qt/QGIS-free helper).
add_executable(closure_agent.processing_tools processing_tools_test.cpp)
target_compile_features(closure_agent.processing_tools PRIVATE cxx_std_20)
target_link_libraries(closure_agent.processing_tools PRIVATE Pwb::ClosureAgent)
add_test(NAME closure_agent.processing_tools COMMAND closure_agent.processing_tools)
set_tests_properties(closure_agent.processing_tools PROPERTIES TIMEOUT 120)

# Workflow adapter — only when the line-02 engine is part of this configure.
if(TARGET Pwb::ClosureAgentWorkflow)
    add_executable(closure_agent.workflow workflow_adapter_test.cpp)
    target_compile_features(closure_agent.workflow PRIVATE cxx_std_20)
    target_link_libraries(closure_agent.workflow PRIVATE Pwb::ClosureAgentWorkflow)
    add_test(NAME closure_agent.workflow COMMAND closure_agent.workflow)
    set_tests_properties(closure_agent.workflow PROPERTIES TIMEOUT 300)
endif()
