# CONV-26 — workflow runtime closure: freshness / recompute / constraint
# lifecycle / provenance graph / runtime service over the workflow cores.
add_library(pwb_workflow_runtime STATIC
    src/catalog_seam.cpp
    src/constraint_versions.cpp
    src/current_context.cpp
    src/freshness.cpp
    src/node_adapters.cpp
    src/provenance_graph.cpp
    src/recompute_plan.cpp
    src/runtime_service.cpp
    src/staleness.cpp
)
add_library(Pwb::WorkflowRuntime ALIAS pwb_workflow_runtime)

target_include_directories(pwb_workflow_runtime
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(pwb_workflow_runtime
    PUBLIC
        Pwb::Domain
        Pwb::WorkflowEngine
        Pwb::WorkflowGraph
        Pwb::FactorHost
)
target_compile_features(pwb_workflow_runtime PUBLIC cxx_std_20)

add_subdirectory(workflow_runtime_tests)
