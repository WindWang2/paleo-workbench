# CONV-25 — workflow dependency graph + evidence selectors (Qt-free).
add_library(pwb_workflow_graph STATIC
    src/graph.cpp
    src/evidence.cpp
)
add_library(Pwb::WorkflowGraph ALIAS pwb_workflow_graph)

target_include_directories(pwb_workflow_graph
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)
target_link_libraries(pwb_workflow_graph PUBLIC Pwb::Domain)
target_compile_features(pwb_workflow_graph PUBLIC cxx_std_20)

if(BUILD_TESTING)
    add_subdirectory(workflow_graph_tests)
endif()
