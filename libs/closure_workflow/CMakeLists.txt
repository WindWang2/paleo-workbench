# cpp-close-02 — workflow orchestration / versioning / recompute closure:
# the consumers CONV-33 findings A3 left to this line. map_product +
# integrated_compilation consume the runtime cores over the catalog seam;
# FileCatalogRepository persists provenance; the scheduler face submits
# runs on the app's single heavy queue; the host bindings wire the UI-14
# controller seams to the real services.
add_library(pwb_closure_workflow STATIC
    src/python_json.cpp
    src/persistent_catalog.cpp
    src/map_product.cpp
    src/map_compile.cpp
    src/integrated_compilation.cpp
    # V14-COMPILATION-PUBLISH — production fusion grid-loading seams.
    src/grid_seams.cpp
    src/workflow_scheduler.cpp
    src/cache_run_rail.cpp
    src/host_bindings.cpp
)
add_library(Pwb::ClosureWorkflow ALIAS pwb_closure_workflow)

target_include_directories(pwb_closure_workflow
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(pwb_closure_workflow
    PUBLIC
        Pwb::Domain
        Pwb::Project
        Pwb::WorkflowEngine
        Pwb::WorkflowGraph
        Pwb::WorkflowRuntime
        Pwb::WorkflowInterpretation
        Pwb::FactorFusion
        Pwb::MappingKernel
        Pwb::Prediction
        Pwb::JobRuntime
    PRIVATE
        Pwb::FactorHost  # python_repr_double (src/ only)
)
target_compile_features(pwb_closure_workflow PUBLIC cxx_std_20)

if(BUILD_TESTING)
    add_subdirectory(closure_workflow_tests)
endif()
