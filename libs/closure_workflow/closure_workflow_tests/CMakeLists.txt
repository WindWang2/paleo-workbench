find_package(Threads REQUIRED)

set(CLOSURE_FIXTURE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/fixtures)

# cpp-close-02 — frozen-oracle replays + the acceptance closed loop.
add_executable(closure_workflow_resolve_test resolve_test.cpp)
target_compile_features(closure_workflow_resolve_test PRIVATE cxx_std_20)
target_link_libraries(closure_workflow_resolve_test
    PRIVATE Pwb::ClosureWorkflow Pwb::MappingKernel Threads::Threads)
add_test(NAME closure_workflow.resolve
         COMMAND closure_workflow_resolve_test
                 ${CLOSURE_FIXTURE_DIR}/closure_resolve_oracle.json)

add_executable(closure_workflow_map_product_test map_product_test.cpp)
target_compile_features(closure_workflow_map_product_test PRIVATE cxx_std_20)
target_link_libraries(closure_workflow_map_product_test
    PRIVATE Pwb::ClosureWorkflow Pwb::MappingKernel Threads::Threads)
add_test(NAME closure_workflow.map_product
         COMMAND closure_workflow_map_product_test
                 ${CLOSURE_FIXTURE_DIR}/closure_map_product_oracle.json)

add_executable(closure_workflow_fusion_test fusion_test.cpp)
target_compile_features(closure_workflow_fusion_test PRIVATE cxx_std_20)
target_link_libraries(closure_workflow_fusion_test
    PRIVATE Pwb::ClosureWorkflow Pwb::MappingKernel Threads::Threads)
add_test(NAME closure_workflow.fusion
         COMMAND closure_workflow_fusion_test
                 ${CLOSURE_FIXTURE_DIR}/closure_fusion_oracle.json)

add_executable(closure_workflow_e2e_test closure_e2e_test.cpp)
target_compile_features(closure_workflow_e2e_test PRIVATE cxx_std_20)
target_link_libraries(closure_workflow_e2e_test
    PRIVATE Pwb::ClosureWorkflow Pwb::MappingKernel Threads::Threads)
add_test(NAME closure_workflow.e2e COMMAND closure_workflow_e2e_test)

# V14-COMPILATION-PUBLISH — production fusion grid seams (decode / catalog
# pin loading / live resolution) + the real fusion path through them.
add_executable(closure_workflow_grid_seams_test grid_seams_test.cpp)
target_compile_features(closure_workflow_grid_seams_test PRIVATE cxx_std_20)
target_link_libraries(closure_workflow_grid_seams_test
    PRIVATE Pwb::ClosureWorkflow Pwb::MappingKernel Threads::Threads)
add_test(NAME closure_workflow.grid_seams
         COMMAND closure_workflow_grid_seams_test)
set_tests_properties(closure_workflow.grid_seams PROPERTIES TIMEOUT 120)
