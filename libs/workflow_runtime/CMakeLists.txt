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
    # CONV-33 — top-level orchestration surfaces (round-1 contract-freeze
    # stubs, fail-loud): service.py (step-status authority) +
    # orchestrator.py (headless cursor) + qc.py / map_qa_rules.py (QC &
    # extended QA) + versioning.py (expert finalize). Landing corrected
    # vs findings: service/orchestrator/versioning live HERE (not
    # workflow_engine) — they compose this library's freshness/recompute
    # surfaces; engine is a downstream PUBLIC dep, no cycles.
    src/orchestrator.cpp
    src/service.cpp
    src/qc.cpp
    src/map_qa_rules.cpp
    src/versioning.cpp
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
        # CONV-33: service/qc/versioning public headers expose the project
        # version-lifecycle DTOs (version_models.hpp).
        Pwb::Project
    PRIVATE
        Pwb::FactorHost  # canonical_encode (src/ only — public headers clean)
)
target_compile_features(pwb_workflow_runtime PUBLIC cxx_std_20)
# CONV-33: the orchestration surfaces expose pwb::project DTOs publicly.
if(NOT TARGET Pwb::Project)
    message(FATAL_ERROR
        "pwb_workflow_runtime requires Pwb::Project "
        "(configure with -DPWB_BUILD_DATA=ON)")
endif()

add_subdirectory(workflow_runtime_tests)
