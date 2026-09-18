# pwb::geo3d_viz — CONV-GEO3D native 3D geomodel viewer.
#
# C++ migration of the Python 3D visualization runtime (pyqtgraph
# GLViewWidget stack): scene model + geological scene adapter + Qt6 OpenGL
# viewport + workspace controller, consuming the existing pwb::geomodel
# contract kernels (CONV-12/22). Python sources stay as the behavior
# oracle; this library is the product chain (no Python dependency).
#
# Consumption:
#   * Root build (primary): -DPWB_BUILD_GEO3D_VIZ=ON turns this on and
#     implies CONV-22 (geomodel contracts) + data (Pwb::Domain).
#   * Standalone: cmake -S libs/geo3d_viz -B build — pulls Pwb::Domain,
#     Pwb::Ingest and pwb_geomodel (CONV-22 sources on) from the same
#     checkout. Never a copy of their sources.
#
# The viewer needs Qt 6.8+ Widgets/OpenGLWidgets; a missing SDK is a
# configure ERROR (fail-closed — there is no headless variant of a
# viewport, only the GL-less runtime degradation inside it).

cmake_minimum_required(VERSION 3.24)

project(PaleoGeo3DViz VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Widgets OpenGLWidgets)

# Standalone entry: reuse the sibling kernel targets from this checkout
# when the consuming superproject has not defined them already.
if(NOT TARGET Pwb::Domain)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../domain
                     ${CMAKE_CURRENT_BINARY_DIR}/domain)
endif()
if(NOT TARGET Pwb::Ingest)
    set(PWB_BUILD_CONV_19 ON)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../ingest
                     ${CMAKE_CURRENT_BINARY_DIR}/ingest)
endif()
if(NOT TARGET Pwb::GeoModel)
    set(PWB_BUILD_CONV_22 ON)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../geomodel
                     ${CMAKE_CURRENT_BINARY_DIR}/geomodel)
endif()

add_library(pwb_geo3d_viz STATIC
    src/scene_object_manager.cpp
    src/orbit_camera.cpp
    src/scene_adapter.cpp
    src/workspace_controller.cpp
    src/geo3d_viewport_widget.cpp
    # AUTOMOC scans headers listed as sources for Q_OBJECT (the headers
    # live in include/, not next to the sources).
    include/pwb/geo3d_viz/workspace_controller.hpp
    include/pwb/geo3d_viz/geo3d_viewport_widget.hpp
)
add_library(Pwb::Geo3DViz ALIAS pwb_geo3d_viz)
set_target_properties(pwb_geo3d_viz PROPERTIES
    EXPORT_NAME Geo3DViz
    OUTPUT_NAME pwb-geo3d-viz
    POSITION_INDEPENDENT_CODE ON
    AUTOMOC ON
)
target_compile_features(pwb_geo3d_viz PUBLIC cxx_std_20)
target_include_directories(pwb_geo3d_viz
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
target_link_libraries(pwb_geo3d_viz
    PUBLIC
        Pwb::GeoModel
        Pwb::Domain
        Qt6::Core
        Qt6::Gui
        Qt6::Widgets
        Qt6::OpenGLWidgets
)
if(MSVC)
    target_compile_options(pwb_geo3d_viz PRIVATE /utf-8 /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_geo3d_viz PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Minimal production consumer: builds a demo scene, opens the viewport and
# exits — the A-line embedding sample and the offscreen smoke canary.
add_executable(geo3d_viewer_example examples/geo3d_viewer_example.cpp)
target_compile_features(geo3d_viewer_example PRIVATE cxx_std_20)
target_link_libraries(geo3d_viewer_example PRIVATE Pwb::Geo3DViz Qt6::Widgets)
if(MSVC)
    target_compile_options(geo3d_viewer_example PRIVATE /utf-8 /W3)
else()
    target_compile_options(geo3d_viewer_example PRIVATE -Wall -Wextra)
endif()

if(BUILD_TESTING)
    enable_testing()
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../tests/cpp/geo3d_viz
                     geo3d_viz_tests)
endif()
