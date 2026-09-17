add_executable(workflow_spec.validate validate_test.cpp)
target_compile_features(workflow_spec.validate PRIVATE cxx_std_20)
target_link_libraries(workflow_spec.validate PRIVATE
    Pwb::WorkflowSpec Pwb::Domain)
target_compile_definitions(workflow_spec.validate PRIVATE
    PWB_WORKFLOW_SPEC_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/workflow_spec_oracle.json")
add_test(NAME workflow_spec.validate COMMAND workflow_spec.validate)
set_tests_properties(workflow_spec.validate PROPERTIES TIMEOUT 60)
