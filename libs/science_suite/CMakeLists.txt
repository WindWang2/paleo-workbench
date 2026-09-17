# Paleo Workbench science suite — C-line standalone entry (protocol:
#   cmake -S libs/science_suite -B build/cpp-science ).
#
# Groups:
#   * Qt-free core: Pwb::Science, Pwb::Workflow, Pwb::Visualization and the
#     mandatory tests science.contracts / science.algorithms / science.workflow
#     / science.seismic. No Python runtime, no Qt Widgets, no QGIS.
#   * opt-in production viewer (-DPWB_SCIENCE_BUILD_VIEWER=ON): builds (or
#     consumes, via PWB_WELL_LOG_ENGINE_ROOT) the well-log-engine SDK — this
#     track is its only builder — and the real WellLogView host adapter
#     Pwb::VisualizationWellLog plus the standalone consumer example. Works
#     with tests off; turning the option ON without a usable Qt 6.8+ / WLE
#     configuration is a configure ERROR — never a silent skip.
#   * opt-in viewer tests (-DPWB_SCIENCE_VIEWER_TESTS=ON): additionally
#     registers science.viewer.well_log. Requires BUILD_VIEWER and
#     BUILD_TESTS; registered only AFTER the adapter target exists (the
#     baseline registered tests first, so the TARGET guard never matched).
#
# Heavy builds/tests must go through scripts/cpp-migration/Invoke-ResourceGate.ps1
# (shared lock + >=8 GiB free memory + 2 jobs) on the Windows host; on this
# Linux verification box the PowerShell gate cannot run (no pwsh) — heavy
# steps run serialized with free memory checked manually (see
# docs/development/cpp-science/v3-verification.md).

cmake_minimum_required(VERSION 3.24)

project(PaleoScienceSuite VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(PWB_SCIENCE_BUILD_TESTS "Build the science test suite" ON)
option(PWB_SCIENCE_BUILD_VIEWER
    "Build the real well-log-engine/Qt viewer adapter Pwb::VisualizationWellLog \
(requires Qt 6.8+ and WLE; fail-closed; independent of tests)"
    OFF)
option(PWB_SCIENCE_VIEWER_TESTS
    "Register the science.viewer.well_log test (requires PWB_SCIENCE_BUILD_VIEWER \
and PWB_SCIENCE_BUILD_TESTS; fail-closed)"
    OFF)

# Option consistency is validated up front so a misconfigured request fails
# with its own message, before any subdirectory can complain first.
if(PWB_SCIENCE_VIEWER_TESTS)
    if(NOT PWB_SCIENCE_BUILD_TESTS)
        message(FATAL_ERROR
            "PWB_SCIENCE_VIEWER_TESTS=ON requires PWB_SCIENCE_BUILD_TESTS=ON")
    endif()
    if(NOT PWB_SCIENCE_BUILD_VIEWER)
        message(FATAL_ERROR
            "PWB_SCIENCE_VIEWER_TESTS=ON requires PWB_SCIENCE_BUILD_VIEWER=ON "
            "(the test exercises the real WLE-backed adapter)")
    endif()
endif()

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../algorithms algorithms)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../workflow workflow)
add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../visualization visualization)

if(PWB_SCIENCE_BUILD_VIEWER)
    # Fail-closed dependency gate: a missing Qt 6.8+ SDK must abort configure,
    # never degrade to a skipped adapter or test.
    find_package(Qt6 6.8 REQUIRED COMPONENTS Widgets OpenGLWidgets)

    if(DEFINED PWB_WELL_LOG_ENGINE_ROOT)
        # Consume the prebuilt read-only WLE install tree (the artifact this
        # track delivers to A): imported targets, no second SDK build.
        if(NOT EXISTS
            "${PWB_WELL_LOG_ENGINE_ROOT}/lib/cmake/WellLog/WellLogConfig.cmake")
            message(FATAL_ERROR
                "PWB_WELL_LOG_ENGINE_ROOT is set but not a WLE install tree "
                "(missing lib/cmake/WellLog/WellLogConfig.cmake): "
                "${PWB_WELL_LOG_ENGINE_ROOT}")
        endif()
        list(APPEND CMAKE_PREFIX_PATH "${PWB_WELL_LOG_ENGINE_ROOT}")
        # The WLE package config does not declare components (every target
        # loads unconditionally), so plain CONFIG discovery + target check.
        find_package(WellLog CONFIG REQUIRED)
        if(NOT TARGET WellLog::QtWidgets)
            message(FATAL_ERROR
                "WellLog package found but WellLog::QtWidgets target missing "
                "(install built without WELLLOG_BUILD_QT_WIDGETS?)")
        endif()
    else()
        # Build the pinned-gitlink WLE SDK from source. This track is its
        # only builder; product binding decisions (Python bindings, text
        # pipeline) stay off.
        if(NOT DEFINED PWB_WELL_LOG_ENGINE_DIR)
            set(PWB_WELL_LOG_ENGINE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../well-log-engine")
        endif()
        if(NOT EXISTS "${PWB_WELL_LOG_ENGINE_DIR}/CMakeLists.txt")
            message(FATAL_ERROR
                "PWB_SCIENCE_BUILD_VIEWER=ON but well-log-engine not found at "
                "${PWB_WELL_LOG_ENGINE_DIR} (initialize the submodule at the "
                "pinned gitlink, or point PWB_WELL_LOG_ENGINE_ROOT at a "
                "prebuilt install tree)")
        endif()
        set(WELLLOG_BUILD_PYTHON OFF)
        set(WELLLOG_BUILD_TEXT OFF)  # Windows: no harfbuzz/ICU pkg-config; view works without
        set(WELLLOG_BUILD_TESTS OFF)
        set(WELLLOG_BUILD_BENCHMARKS OFF)
        set(WELLLOG_BUILD_QT_WIDGETS ON)
        add_subdirectory("${PWB_WELL_LOG_ENGINE_DIR}" well-log-engine)
    endif()

    # Host adapter (Pwb::VisualizationWellLog) lives with the visualization
    # library sources; its public header is under libs/visualization/include.
    add_subdirectory(
        "${CMAKE_CURRENT_SOURCE_DIR}/../visualization/src/well_log" well_log_adapter)
endif()

# Tests come last: the viewer test registration below must see the adapter
# target that the block above may have created (baseline bug: tests were
# added first, so `TARGET Pwb::VisualizationWellLog` was always false and
# science.viewer.well_log was never registered).
if(PWB_SCIENCE_BUILD_TESTS)
    enable_testing()
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../tests/cpp/science science_tests)
endif()

if(PWB_SCIENCE_VIEWER_TESTS AND NOT TARGET Pwb::VisualizationWellLog)
    message(FATAL_ERROR
        "PWB_SCIENCE_VIEWER_TESTS=ON but Pwb::VisualizationWellLog does "
        "not exist — the viewer build failed silently, which is a "
        "configuration error, never a skipped test")
endif()
