add_executable(workflow_engine.run engine_run_test.cpp)
target_compile_features(workflow_engine.run PRIVATE cxx_std_20)
target_link_libraries(workflow_engine.run PRIVATE
    Pwb::WorkflowEngine Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(workflow_engine.run PRIVATE
    PWB_ENGINE_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/workflow_engine_oracle.json")
add_test(NAME workflow_engine.run COMMAND workflow_engine.run)
set_tests_properties(workflow_engine.run PROPERTIES TIMEOUT 120)
