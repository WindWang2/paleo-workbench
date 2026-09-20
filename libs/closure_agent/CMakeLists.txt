add_library(pwb_closure_agent STATIC
    src/spec.cpp
    src/registry.cpp
    src/context.cpp
    src/executor.cpp
    src/intent.cpp
    src/planner.cpp
    src/events.cpp
    src/checkpoint.cpp
    src/model_transport.cpp
    src/tool_source.cpp
    src/session.cpp
)
add_library(Pwb::ClosureAgent ALIAS pwb_closure_agent)
set_target_properties(pwb_closure_agent PROPERTIES
    EXPORT_NAME ClosureAgent
    OUTPUT_NAME pwb-closure-agent
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_closure_agent PUBLIC cxx_std_20)
target_include_directories(pwb_closure_agent PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
# PUBLIC: the headers expose pwb::providers types (CancelToken, TypedInput,
# ProviderContext) and pwb::domain::Json. Provider dispatch reuses the line-10
# SDK — the provider registry itself is NOT rebuilt here.
target_link_libraries(pwb_closure_agent PUBLIC Pwb::Providers)

# Workflow adapter (line 02 consumption) — only when the RunEngine target
# exists (configure with PWB_BUILD_CONV_06 + PWB_BUILD_CONV_07). Defined
# BEFORE the tests subdirectory so the adapter test can gate on it.
if(TARGET Pwb::WorkflowEngine)
    add_library(pwb_closure_agent_workflow STATIC
        workflow/workflow_engine_runner.cpp
    )
    add_library(Pwb::ClosureAgentWorkflow ALIAS pwb_closure_agent_workflow)
    set_target_properties(pwb_closure_agent_workflow PROPERTIES
        EXPORT_NAME ClosureAgentWorkflow
        OUTPUT_NAME pwb-closure-agent-workflow
        POSITION_INDEPENDENT_CODE ON
    )
    target_compile_features(pwb_closure_agent_workflow PUBLIC cxx_std_20)
    target_link_libraries(pwb_closure_agent_workflow PUBLIC
        Pwb::ClosureAgent Pwb::WorkflowEngine
    )
endif()

if(BUILD_TESTING)
    add_subdirectory(closure_agent_tests)
endif()
