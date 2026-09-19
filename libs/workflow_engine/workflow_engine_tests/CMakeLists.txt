add_executable(workflow_engine.run engine_run_test.cpp)
target_compile_features(workflow_engine.run PRIVATE cxx_std_20)
target_link_libraries(workflow_engine.run PRIVATE
    Pwb::WorkflowEngine Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(workflow_engine.run PRIVATE
    PWB_ENGINE_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/workflow_engine_oracle.json")
add_test(NAME workflow_engine.run COMMAND workflow_engine.run)
set_tests_properties(workflow_engine.run PROPERTIES TIMEOUT 120)

# CONV-32 — store/reproduction, receipt/plan_view, lifecycle engine replays.
set(WORKFLOW_ENGINE_FIXTURE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/fixtures)

add_executable(workflow_engine_store_test store_test.cpp)
target_compile_features(workflow_engine_store_test PRIVATE cxx_std_20)
target_link_libraries(workflow_engine_store_test PRIVATE Pwb::WorkflowEngine)
add_test(NAME workflow_engine.store
         COMMAND workflow_engine_store_test
                 ${WORKFLOW_ENGINE_FIXTURE_DIR}/workflow_store_oracle.json)
set_tests_properties(workflow_engine.store PROPERTIES TIMEOUT 120)

add_executable(workflow_engine_receipt_test receipt_plan_view_test.cpp)
target_compile_features(workflow_engine_receipt_test PRIVATE cxx_std_20)
target_link_libraries(workflow_engine_receipt_test PRIVATE Pwb::WorkflowEngine)
add_test(NAME workflow_engine.receipt_plan_view
         COMMAND workflow_engine_receipt_test
                 ${WORKFLOW_ENGINE_FIXTURE_DIR}/workflow_receipt_plan_view_oracle.json)
set_tests_properties(workflow_engine.receipt_plan_view PROPERTIES TIMEOUT 120)

add_executable(workflow_engine_lifecycle_test engine_lifecycle_test.cpp)
target_compile_features(workflow_engine_lifecycle_test PRIVATE cxx_std_20)
target_link_libraries(workflow_engine_lifecycle_test PRIVATE Pwb::WorkflowEngine)
add_test(NAME workflow_engine.lifecycle
         COMMAND workflow_engine_lifecycle_test
                 ${WORKFLOW_ENGINE_FIXTURE_DIR}/workflow_engine_lifecycle_oracle.json)
set_tests_properties(workflow_engine.lifecycle PROPERTIES TIMEOUT 180)
