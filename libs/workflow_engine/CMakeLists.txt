# CPP workflow_engine — in-memory DAG executor (full-conversion plan M7
# executor slice). Topological order, failure short-circuit, cooperative
# cancel, per-node stdout logging; node bodies from an explicitly
# registered function table (noop + mapping_kernel wrappers). Qt-free,
# Python-free; frozen against tools/oracle/generate_workflow_engine_fixtures.py.
add_library(pwb_workflow_engine STATIC
    src/engine.cpp
    src/ops.cpp
    # CONV-32 — run store / reproduction / receipts / plan views /
    # store-driven lifecycle engine (dag/store.py + reproduction.py +
    # receipt.py + plan_view.py + the engine.py full surface).
    src/store.cpp
    src/reproduction.cpp
    src/receipt.cpp
    src/plan_view.cpp
    src/run_engine.cpp
    # CONV-33 — portable *.paleo-workflow.json recipes (workflow/recipe.py):
    # security gates (forbidden keys / absolute paths), fail-closed migrate,
    # atomic indent=1 save, load/clone/diff/inspect. Round-1 = contract
    # freeze stubs (fail-loud).
    src/recipe.cpp)
add_library(Pwb::WorkflowEngine ALIAS pwb_workflow_engine)
target_include_directories(pwb_workflow_engine PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_workflow_engine PUBLIC cxx_std_20)
if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "pwb_workflow_engine requires Pwb::Domain "
        "(configure with -DPWB_BUILD_DATA=ON)")
endif()
# CONV-32: store/reproduction/run_engine persist and drive the
# workflow_spec DTOs (CONV-06).
if(NOT TARGET Pwb::WorkflowSpec)
    message(FATAL_ERROR
        "pwb_workflow_engine requires Pwb::WorkflowSpec "
        "(configure with -DPWB_BUILD_CONV_06=ON)")
endif()
target_link_libraries(pwb_workflow_engine PUBLIC Pwb::Domain Pwb::WorkflowSpec)
target_link_libraries(pwb_workflow_engine PRIVATE Pwb::MappingKernel)

if(BUILD_TESTING)
    add_subdirectory(workflow_engine_tests)
endif()
