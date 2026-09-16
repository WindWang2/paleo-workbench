# Paleo Workbench science suite — C-line standalone entry (protocol:
#   cmake -S libs/science_suite -B build/cpp-science ).
#
# Groups:
#   * Qt-free core: Pwb::Science, Pwb::Workflow, Pwb::Visualization and the
#     mandatory tests science.contracts / science.algorithms / science.workflow
#     / science.seismic. No Python runtime, no Qt Widgets, no QGIS.
#   * opt-in viewer tests (-DPWB_SCIENCE_VIEWER_TESTS=ON): builds the
#     well-log-engine SDK (this track is its only builder) and the real
#     WellLogView host adapter, then runs science.viewer.well_log. Turning the
#     option ON without a usable Qt 6.8+ / WLE configuration is a configure
#     ERROR — never a silent skip.
#
# Heavy builds/tests must go through scripts/cpp-migration/Invoke-ResourceGate.ps1
# (shared lock + >=8 GiB free memory + 2 jobs).

cmake_minimum_required(VERSION 3.24)

project(PaleoScienceSuite VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(PWB_SCIENCE_BUILD_TESTS "Build the science test suite" ON)
option(PWB_SCIENCE_VIEWER_TESTS
    "Build the real well-log-engine/Qt viewer adapter and its tests (requires Qt 6.8+; fail-closed)"
    OFF)

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../algorithms algorithms)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../workflow workflow)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../visualization visualization)

if(PWB_SCIENCE_BUILD_TESTS)
    enable_testing()
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../tests/cpp/science science_tests)
endif()

if(PWB_SCIENCE_VIEWER_TESTS)
    if(NOT PWB_SCIENCE_BUILD_TESTS)
        message(FATAL_ERROR
            "PWB_SCIENCE_VIEWER_TESTS=ON requires PWB_SCIENCE_BUILD_TESTS=ON")
    endif()
    if(NOT DEFINED PWB_WELL_LOG_ENGINE_DIR)
        set(PWB_WELL_LOG_ENGINE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../well-log-engine")
    endif()
    if(NOT EXISTS "${PWB_WELL_LOG_ENGINE_DIR}/CMakeLists.txt")
        message(FATAL_ERROR
            "PWB_SCIENCE_VIEWER_TESTS=ON but well-log-engine not found at "
            "${PWB_WELL_LOG_ENGINE_DIR} (initialize the submodule at the pinned gitlink)")
    endif()
    # Fail-closed dependency gate: a missing Qt 6.8+ SDK must abort configure,
    # never degrade to a skipped test.
    find_package(Qt6 6.8 REQUIRED COMPONENTS Widgets OpenGLWidgets)

    # well-log-engine SDK: this track is its only builder. Product binding
    # decisions (Python bindings, text pipeline) stay off.
    set(WELLLOG_BUILD_PYTHON OFF)
    set(WELLLOG_BUILD_TEXT OFF)   # Windows: no harfbuzz/ICU pkg-config; view works without
    set(WELLLOG_BUILD_TESTS OFF)
    set(WELLLOG_BUILD_BENCHMARKS OFF)
    set(WELLLOG_BUILD_QT_WIDGETS ON)
    add_subdirectory("${PWB_WELL_LOG_ENGINE_DIR}" well-log-engine)

    # Host adapter (Pwb::VisualizationWellLog) lives with the visualization
    # library sources; it is only reachable through this opt-in path.
    add_subdirectory(
        "${CMAKE_CURRENT_SOURCE_DIR}/../visualization/src/well_log" well_log_adapter)
endif()
