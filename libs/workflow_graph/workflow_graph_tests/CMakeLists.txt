add_executable(workflow_graph_contracts_test contracts_test.cpp)
target_link_libraries(workflow_graph_contracts_test
    PRIVATE Pwb::WorkflowGraph)
target_compile_features(workflow_graph_contracts_test PRIVATE cxx_std_20)

set(WORKFLOW_GRAPH_FIXTURE
    ${CMAKE_CURRENT_SOURCE_DIR}/fixtures/workflow_graph_oracle.json)

add_test(NAME workflow_graph.contracts
         COMMAND workflow_graph_contracts_test ${WORKFLOW_GRAPH_FIXTURE})
