# CONV-23 — workflow.contracts oracle conformance: replays the frozen
# contract/registry/validation/readiness/report cases against the C++
# contract layer.
add_executable(workflow.contracts contracts_test.cpp)
target_compile_features(workflow.contracts PRIVATE cxx_std_20)
target_link_libraries(workflow.contracts PRIVATE Pwb::WorkflowContracts Pwb::Domain)
target_compile_definitions(workflow.contracts PRIVATE
    PWB_CONTRACTS_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/workflow_contract_oracle.json")
add_test(NAME workflow.contracts COMMAND workflow.contracts)
set_tests_properties(workflow.contracts PROPERTIES TIMEOUT 120)
