# CONV-32 — workflow_interpretation replay tests. Each binary takes its
# frozen oracle fixture path as argv[1] (workflow_graph tests pattern).
set(WORKFLOW_INTERPRETATION_FIXTURE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/fixtures)

add_executable(workflow_interpretation_fault_lifecycle_test fault_lifecycle_test.cpp)
target_link_libraries(workflow_interpretation_fault_lifecycle_test
    PRIVATE Pwb::WorkflowInterpretation)
target_compile_features(workflow_interpretation_fault_lifecycle_test PRIVATE cxx_std_20)
add_test(NAME workflow_interpretation.fault_lifecycle
         COMMAND workflow_interpretation_fault_lifecycle_test)

add_executable(workflow_interpretation_registry_test registry_test.cpp)
target_link_libraries(workflow_interpretation_registry_test
    PRIVATE Pwb::WorkflowInterpretation)
target_compile_features(workflow_interpretation_registry_test PRIVATE cxx_std_20)
add_test(NAME workflow_interpretation.registry
         COMMAND workflow_interpretation_registry_test
                 ${WORKFLOW_INTERPRETATION_FIXTURE_DIR}/workflow_interpretation_registry_oracle.json)

add_executable(workflow_interpretation_factor_test factor_product_test.cpp)
target_link_libraries(workflow_interpretation_factor_test
    PRIVATE Pwb::WorkflowInterpretation)
target_compile_features(workflow_interpretation_factor_test PRIVATE cxx_std_20)
add_test(NAME workflow_interpretation.factor
         COMMAND workflow_interpretation_factor_test
                 ${WORKFLOW_INTERPRETATION_FIXTURE_DIR}/workflow_interpretation_factor_oracle.json)

add_executable(workflow_interpretation_constraint_test constraint_product_test.cpp)
target_link_libraries(workflow_interpretation_constraint_test
    PRIVATE Pwb::WorkflowInterpretation)
target_compile_features(workflow_interpretation_constraint_test PRIVATE cxx_std_20)
add_test(NAME workflow_interpretation.constraint
         COMMAND workflow_interpretation_constraint_test
                 ${WORKFLOW_INTERPRETATION_FIXTURE_DIR}/workflow_interpretation_constraint_oracle.json)

add_executable(workflow_interpretation_compilation_test compilation_test.cpp)
target_link_libraries(workflow_interpretation_compilation_test
    PRIVATE Pwb::WorkflowInterpretation)
target_compile_features(workflow_interpretation_compilation_test PRIVATE cxx_std_20)
add_test(NAME workflow_interpretation.compilation
         COMMAND workflow_interpretation_compilation_test
                 ${WORKFLOW_INTERPRETATION_FIXTURE_DIR}/workflow_interpretation_compilation_oracle.json)

add_executable(workflow_interpretation_integrated_test integrated_test.cpp)
target_link_libraries(workflow_interpretation_integrated_test
    PRIVATE Pwb::WorkflowInterpretation)
target_compile_features(workflow_interpretation_integrated_test PRIVATE cxx_std_20)
add_test(NAME workflow_interpretation.integrated
         COMMAND workflow_interpretation_integrated_test
                 ${WORKFLOW_INTERPRETATION_FIXTURE_DIR}/workflow_interpretation_integrated_oracle.json)
