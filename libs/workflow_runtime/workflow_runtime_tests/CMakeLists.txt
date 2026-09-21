find_package(Threads REQUIRED)
add_executable(workflow_runtime_contracts_test runtime_test.cpp)
target_link_libraries(workflow_runtime_contracts_test
    PRIVATE Pwb::WorkflowRuntime Threads::Threads)
target_compile_features(workflow_runtime_contracts_test PRIVATE cxx_std_20)

set(WORKFLOW_RUNTIME_FIXTURE
    ${CMAKE_CURRENT_SOURCE_DIR}/fixtures/workflow_runtime_oracle.json)

add_test(NAME workflow_runtime.contracts
         COMMAND workflow_runtime_contracts_test ${WORKFLOW_RUNTIME_FIXTURE})

# CONV-33 — orchestration surface replays. Round-1 skeletons (contract
# freeze); round-2 replaces each main with the frozen-oracle replay and
# lands the fixtures from tools/oracle/generate_workflow_*_fixtures.py.
set(WORKFLOW_RUNTIME_FIXTURE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/fixtures)

add_executable(workflow_runtime_qc_test qc_test.cpp)
target_compile_features(workflow_runtime_qc_test PRIVATE cxx_std_20)
target_link_libraries(workflow_runtime_qc_test PRIVATE Pwb::WorkflowRuntime)
add_test(NAME workflow_runtime.qc
         COMMAND workflow_runtime_qc_test
                 ${WORKFLOW_RUNTIME_FIXTURE_DIR}/workflow_qc_oracle.json)

add_executable(workflow_runtime_service_test service_test.cpp)
target_compile_features(workflow_runtime_service_test PRIVATE cxx_std_20)
target_link_libraries(workflow_runtime_service_test PRIVATE Pwb::WorkflowRuntime)
add_test(NAME workflow_runtime.service
         COMMAND workflow_runtime_service_test
                 ${WORKFLOW_RUNTIME_FIXTURE_DIR}/workflow_service_oracle.json)

add_executable(workflow_runtime_run_orchestration_test
               run_orchestration_test.cpp)
target_compile_features(workflow_runtime_run_orchestration_test
                        PRIVATE cxx_std_20)
target_link_libraries(workflow_runtime_run_orchestration_test
                      PRIVATE Pwb::WorkflowRuntime)
add_test(NAME workflow_runtime.run_orchestration
         COMMAND workflow_runtime_run_orchestration_test
                 ${WORKFLOW_RUNTIME_FIXTURE_DIR}/run_orchestration_oracle.json)

add_executable(workflow_runtime_versioning_test versioning_test.cpp)
target_compile_features(workflow_runtime_versioning_test PRIVATE cxx_std_20)
target_link_libraries(workflow_runtime_versioning_test PRIVATE Pwb::WorkflowRuntime)
add_test(NAME workflow_runtime.versioning
         COMMAND workflow_runtime_versioning_test
                 ${WORKFLOW_RUNTIME_FIXTURE_DIR}/workflow_versioning_oracle.json)
