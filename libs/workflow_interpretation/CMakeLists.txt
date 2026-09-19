# CONV-32 — workflow interpretation domain spine (Qt-free): constraint
# capabilities + algorithm registry, factor products + summaries,
# constraint products + interpretation revisions, integrated
# interpretation + compilation input sets. Ported from
# paleo_workbench/workflow/interpretation/* + workflow/
# constraint_capabilities.py; frozen against
# tools/oracle/generate_workflow_interpretation_*_fixtures.py.
add_library(pwb_workflow_interpretation STATIC
    src/algorithm_registry.cpp
    src/compilation.cpp
    src/constraint_capabilities.cpp
    src/constraint_product.cpp
    src/factor_product.cpp
    src/integrated_interpretation.cpp
    src/revision.cpp
    src/summaries.cpp
)
add_library(Pwb::WorkflowInterpretation ALIAS pwb_workflow_interpretation)

target_include_directories(pwb_workflow_interpretation
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_compile_features(pwb_workflow_interpretation PUBLIC cxx_std_20)
target_link_libraries(pwb_workflow_interpretation PUBLIC
    Pwb::WorkflowGraph
    Pwb::WorkflowRuntime
    Pwb::FactorFusion
    Pwb::Domain
)

add_subdirectory(workflow_interpretation_tests)
