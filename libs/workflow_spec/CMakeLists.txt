# CONV-06 — WorkflowSpec DAG pure model + validator, ported from
# paleo_workbench/workflow/dag/{model,validation}.py (full-conversion plan
# M7 leaf: DAG definition, NOT the executor). Qt-free, QGIS-free; frozen
# against the Python oracle (tools/oracle/generate_workflow_spec_fixtures.py).
# Uses pwb::domain::Json (ordered) + pwb::domain::Sha256 for canonical_hash.
add_library(pwb_workflow_spec STATIC
    src/model.cpp
    src/validation.cpp
    src/python_repr.cpp)
add_library(Pwb::WorkflowSpec ALIAS pwb_workflow_spec)
target_include_directories(pwb_workflow_spec PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_workflow_spec PUBLIC cxx_std_20)
if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "pwb_workflow_spec requires Pwb::Domain (configure with "
        "-DPWB_BUILD_DATA=ON)")
endif()
target_link_libraries(pwb_workflow_spec PUBLIC Pwb::Domain)

if(BUILD_TESTING)
    add_subdirectory(workflow_spec_tests)
endif()
