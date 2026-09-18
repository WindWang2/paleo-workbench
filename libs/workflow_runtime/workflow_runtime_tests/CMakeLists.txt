add_executable(workflow_runtime_contracts_test runtime_test.cpp)
target_link_libraries(workflow_runtime_contracts_test
    PRIVATE Pwb::WorkflowRuntime)
target_compile_features(workflow_runtime_contracts_test PRIVATE cxx_std_20)

set(WORKFLOW_RUNTIME_FIXTURE
    ${CMAKE_CURRENT_SOURCE_DIR}/fixtures/workflow_runtime_oracle.json)

add_test(NAME workflow_runtime.contracts
         COMMAND workflow_runtime_contracts_test ${WORKFLOW_RUNTIME_FIXTURE})
