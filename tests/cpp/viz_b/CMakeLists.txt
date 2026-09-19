# VIZ-B — integration test + standalone real-engine example. Added from
# the cross_well lib CMakeLists once the viz-B cores and the UI-04 worker
# closure exist in this configure.

if(NOT TARGET Pwb::VisualizationCrossWellQt)
    message(FATAL_ERROR "tests/cpp/viz_b needs Pwb::VisualizationCrossWellQt")
endif()
if(NOT TARGET Pwb::UiWorkers)
    message(FATAL_ERROR "tests/cpp/viz_b needs Pwb::UiWorkers (DTW worker)")
endif()

set(VIZ_B_WELL_TIE_FIXTURE
    "${CMAKE_SOURCE_DIR}/libs/visualization/src/well_tie/well_tie_tests/fixtures/viz_b_well_tie_oracle.json")

add_executable(viz_b.integration viz_b_integration_test.cpp)
target_compile_features(viz_b.integration PRIVATE cxx_std_20)
set_target_properties(viz_b.integration PROPERTIES AUTOMOC ON)
target_link_libraries(viz_b.integration PRIVATE
    Pwb::VisualizationCrossWellQt Pwb::VisualizationWellTieQt
    Pwb::UiWorkers Pwb::Domain Qt6::Widgets)
target_compile_definitions(viz_b.integration PRIVATE
    PWB_VIZ_B_CROSS_WELL_FIXTURE="${CMAKE_SOURCE_DIR}/libs/visualization/src/cross_well/cross_well_tests/fixtures/viz_b_cross_well_oracle.json"
    PWB_VIZ_B_WELL_TIE_FIXTURE="${VIZ_B_WELL_TIE_FIXTURE}")
add_test(NAME viz_b.integration COMMAND viz_b.integration)
set_tests_properties(viz_b.integration PROPERTIES
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
    TIMEOUT 600)

# Standalone real-engine example — the independent-engine evidence (no
# GUI shell; offscreen paint entries).
add_executable(viz_b.engines_example viz_b_engines_example.cpp)
target_compile_features(viz_b.engines_example PRIVATE cxx_std_20)
set_target_properties(viz_b.engines_example PROPERTIES AUTOMOC ON)
target_link_libraries(viz_b.engines_example PRIVATE
    Pwb::VisualizationCrossWellQt Pwb::VisualizationWellTieQt
    Pwb::UiWorkers Pwb::Domain Qt6::Widgets)
add_test(NAME viz_b.engines_example COMMAND viz_b.engines_example
    "${CMAKE_SOURCE_DIR}/libs/visualization/src/cross_well/cross_well_tests/fixtures/viz_b_cross_well_oracle.json"
    "${CMAKE_CURRENT_BINARY_DIR}/example_output"
    "${VIZ_B_WELL_TIE_FIXTURE}")
set_tests_properties(viz_b.engines_example PROPERTIES
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
    TIMEOUT 600)

# Dock smoke: the REAL platform dock + JobCenter, compiled and exercised
# without the full pwb-platform binary (which is currently blocked by an
# unrelated upstream TU error — see docs/development/cpp-viz-b/ledger.md).
add_executable(viz_b.dock_smoke viz_b_dock_smoke.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_b_cross_well_dock.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/job_center.cpp)
target_compile_features(viz_b.dock_smoke PRIVATE cxx_std_20)
set_target_properties(viz_b.dock_smoke PROPERTIES AUTOMOC ON)
target_include_directories(viz_b.dock_smoke PRIVATE
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform)
target_link_libraries(viz_b.dock_smoke PRIVATE
    Pwb::VisualizationCrossWellQt Pwb::VisualizationWellTieQt
    Pwb::UiWorkers Pwb::UiWellseisQt Pwb::Domain Pwb::JobQt
    Qt6::Widgets)
target_compile_definitions(viz_b.dock_smoke PRIVATE
    PWB_VIZ_B_CROSS_WELL_FIXTURE="${CMAKE_SOURCE_DIR}/libs/visualization/src/cross_well/cross_well_tests/fixtures/viz_b_cross_well_oracle.json")
add_test(NAME viz_b.dock_smoke COMMAND viz_b.dock_smoke)
set_tests_properties(viz_b.dock_smoke PROPERTIES
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
    TIMEOUT 300)
