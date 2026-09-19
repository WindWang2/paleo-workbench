# VIZ-A — line-A acceptance tests: LAS/WLE convergence (ingest preview,
# worker load, dock consistency) and well-log drawing differentials.
# Mounted from the root CMakeLists after science_suite, ingest (CONV-19)
# and ui_workers resolved, so the guarded WLE-bridge targets already exist
# when this directory configures. Tests needing the WLE SDK register only
# when the bridge targets are present; the rest run in every config.

set(VIZ_A_FIXTURE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/fixtures")

function(viz_a_test target source)
    add_executable(${target} ${source})
    target_compile_features(${target} PRIVATE cxx_std_20)
    set_target_properties(${target} PROPERTIES
        CXX_EXTENSIONS OFF
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
    target_compile_definitions(${target} PRIVATE
        PWB_VIZ_A_FIXTURE_ROOT="${VIZ_A_FIXTURE_ROOT}")
    add_test(NAME ${target} COMMAND ${target})
    set_tests_properties(${target} PROPERTIES TIMEOUT 300)
endfunction()

# Provider-less core branches (formatting, classification, honest
# capability-unavailable) — runs without the WLE SDK.
viz_a_test(viz_a.las_preview_core las_preview_core_test.cpp)
target_link_libraries(viz_a.las_preview_core PRIVATE Pwb::Ingest)

# Oracle replay against the frozen Python+WLE-contract fixtures, through
# the registry LAS branch (end-to-end) — requires the WLE bridge.
if(TARGET Pwb::IngestLasWle)
    viz_a_test(viz_a.las_preview_wle las_preview_wle_test.cpp)
    target_link_libraries(viz_a.las_preview_wle PRIVATE
        Pwb::Ingest Pwb::IngestLasWle)
endif()

# Worker seam production adapter: real WLE loads, cancellation, non-LAS
# honesty, resolve integration.
if(TARGET Pwb::UiWorkersWleLoad)
    viz_a_test(viz_a.wle_load wle_load_test.cpp)
    target_link_libraries(viz_a.wle_load PRIVATE
        Pwb::UiWorkers Pwb::UiWorkersWleLoad)
endif()

# Dock/preview/worker three-way consistency over the same files — needs the
# full viewer stack (offscreen Qt).
if(TARGET Pwb::IngestLasWle AND TARGET Pwb::UiWorkersWleLoad
   AND TARGET Pwb::VisualizationWellLog)
    viz_a_test(viz_a.consistency consistency_test.cpp)
    target_link_libraries(viz_a.consistency PRIVATE
        Pwb::Ingest Pwb::IngestLasWle Pwb::UiWorkers Pwb::UiWorkersWleLoad
        Pwb::VisualizationWellLog Qt6::Widgets)
    set_tests_properties(viz_a.consistency PROPERTIES ENVIRONMENT
        "QT_QPA_PLATFORM=offscreen;LIBGL_ALWAYS_SOFTWARE=1")
endif()

# Viewer flow: load -> display -> track adjust -> export; failure, reopen,
# teardown (offscreen Qt + software GL). Also the drawing-differential
# kernels (pattern vocabulary + robust scale) frozen against the Python
# oracle.
if(TARGET Pwb::VisualizationWellLog)
    viz_a_test(viz_a.viewer_flow viewer_flow_test.cpp)
    target_link_libraries(viz_a.viewer_flow PRIVATE
        Pwb::VisualizationWellLog Qt6::Widgets)
    set_tests_properties(viz_a.viewer_flow PROPERTIES ENVIRONMENT
        "QT_QPA_PLATFORM=offscreen;LIBGL_ALWAYS_SOFTWARE=1")

    viz_a_test(viz_a.patterns patterns_test.cpp)
    target_link_libraries(viz_a.patterns PRIVATE
        Pwb::VisualizationWellLog Pwb::Domain)
endif()
