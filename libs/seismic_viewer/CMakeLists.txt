# pwb::seismic_viewer — D-line embeddable 2-D seismic slice viewer.
#
# Standalone entry (protocol):
#   cmake -S libs/seismic_viewer -B build/cpp-seismic-viewer
#
# Consumption:
#   * Standalone (this file is a project entry): pulls in the base
#     Visualization library from the same checkout when Pwb::Visualization is
#     not already defined — never a copy of its sources.
#   * add_subdirectory(libs/seismic_viewer) from the root build (A): reuses
#     the already-defined base targets.
#
# Switches (viewer and tests are separate):
#   * The production target Pwb::SeismicViewer and the example consumer are
#     always built; BUILD_TESTING=OFF yields a fully usable module.
#   * PWB_SEISMIC_VIEWER_BUILD_TESTS=ON (default) additionally registers the
#     seismic_viewer.* tests. Enabling tests without a usable Qt 6.8+ Widgets
#     SDK or without the frozen fixtures is a configure ERROR (fail-closed),
#     never a silent skip.

cmake_minimum_required(VERSION 3.24)

project(PaleoSeismicViewer VERSION 3.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(PWB_SEISMIC_VIEWER_BUILD_TESTS "Build the seismic_viewer.* test suite" ON)

# The viewer is a Qt Widgets library: a missing SDK aborts configure in every
# consumption mode (fail-closed; there is no headless fallback for the widget
# target itself).
find_package(Qt6 6.8 REQUIRED COMPONENTS Widgets)

# Base Visualization contract (ISeismicVolume, map_slice_to_indexed8). Reuse
# the target when the consuming superproject already provides it.
if(NOT TARGET Pwb::Visualization)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../visualization visualization)
endif()

add_library(pwb_seismic_viewer
    src/color_maps.cpp
    src/colorbar_widget.cpp
    src/crossplot_core.cpp
    src/display_core.cpp
    src/horizon_core.cpp
    src/isosurface_core.cpp
    src/slice_controller.cpp
    src/seismic_slice_widget.cpp
)
add_library(Pwb::SeismicViewer ALIAS pwb_seismic_viewer)
set_target_properties(pwb_seismic_viewer PROPERTIES
    EXPORT_NAME SeismicViewer
    OUTPUT_NAME pwb-seismic-viewer
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_seismic_viewer PUBLIC cxx_std_20)
target_include_directories(pwb_seismic_viewer
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
# VIZ-D: the crossplot core reuses the frozen single-trace attribute kernels
# (seismic.envelope / seismic.instantaneous_frequency) through the science
# SDK. The dependency is PRIVATE (only crossplot_core.cpp consumes it) and
# uses the plain target name so the root build's later
# add_subdirectory(libs/seismic_attributes) resolves it at generate time;
# the standalone entry pulls the sibling directory in itself.
if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR AND NOT TARGET pwb_seismic_attributes)
    set(PWB_SEISMIC_ATTRIBUTES_BUILD_TESTS OFF) # standalone: only the viewer's own tests
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../seismic_attributes seismic_attributes)
endif()
target_link_libraries(pwb_seismic_viewer
    PUBLIC Pwb::Visualization Qt6::Widgets
    PRIVATE pwb_seismic_attributes
)
if(MSVC)
    target_compile_options(pwb_seismic_viewer PRIVATE /utf-8 /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_seismic_viewer PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Minimal production consumer (also the A-line embedding sample).
add_executable(seismic_viewer_example examples/seismic_viewer_consumer.cpp)
target_compile_features(seismic_viewer_example PRIVATE cxx_std_20)
target_link_libraries(seismic_viewer_example PRIVATE Pwb::SeismicViewer Qt6::Widgets)
if(MSVC)
    target_compile_options(seismic_viewer_example PRIVATE /utf-8 /W3)
else()
    target_compile_options(seismic_viewer_example PRIVATE -Wall -Wextra)
endif()

if(PWB_SEISMIC_VIEWER_BUILD_TESTS)
    include(CTest)
    if(BUILD_TESTING)
        # Fail-closed fixture gate: the frozen tiny_sgy oracle (C-line,
        # read-only input) must exist at configure time.
        set(PWB_SEISMIC_VIEWER_SCIENCE_FIXTURES
            "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/cpp/science/fixtures"
            CACHE PATH "Read-only science fixtures root (tiny_sgy oracle)")
        if(NOT EXISTS
           "${PWB_SEISMIC_VIEWER_SCIENCE_FIXTURES}/seismic/tiny_sgy/manifest.json")
            message(FATAL_ERROR
                "seismic_viewer tests are ON but the frozen tiny_sgy fixture is "
                "missing under ${PWB_SEISMIC_VIEWER_SCIENCE_FIXTURES}/seismic/tiny_sgy")
        endif()
        enable_testing()
        add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../tests/cpp/seismic_viewer
                         seismic_viewer_tests)
    endif()
endif()
