cmake_minimum_required(VERSION 3.21)
project(qgis_render_bridge LANGUAGES CXX)

option(PALEO_WITH_QGIS_RENDERER "Build the optional QGIS renderer bridge" OFF)
set(QGIS_PREFIX_PATH "$ENV{QGIS_PREFIX_PATH}" CACHE PATH "QGIS installation prefix")

find_path(QGIS_INCLUDE_DIR
    NAMES qgsapplication.h
    HINTS "${QGIS_PREFIX_PATH}/include" "${QGIS_PREFIX_PATH}/include/qgis"
    PATH_SUFFIXES qgis
)
find_library(QGIS_CORE_LIBRARY
    NAMES qgis_core
    HINTS "${QGIS_PREFIX_PATH}/lib"
)
find_library(QGIS_GUI_LIBRARY
    NAMES qgis_gui
    HINTS "${QGIS_PREFIX_PATH}/lib"
)

set(QGIS_FOUND FALSE)
set(QGIS_VERSION "")
if(QGIS_INCLUDE_DIR AND QGIS_CORE_LIBRARY)
    set(QGIS_FOUND TRUE)
    file(STRINGS "${QGIS_INCLUDE_DIR}/qgsconfig.h" _qgis_version_line
        REGEX "QGIS_VERSION[ _]+\"")
    string(REGEX REPLACE ".*\"([^\"]+).*" "\\1" QGIS_VERSION "${_qgis_version_line}")
endif()

message(STATUS "QGIS_FOUND=${QGIS_FOUND}")
message(STATUS "QGIS_VERSION=${QGIS_VERSION}")
message(STATUS "QGIS_PREFIX_PATH=${QGIS_PREFIX_PATH}")
message(STATUS "QGIS_CORE_LIBRARY=${QGIS_CORE_LIBRARY}")
message(STATUS "QGIS_GUI_LIBRARY=${QGIS_GUI_LIBRARY}")

if(PALEO_WITH_QGIS_RENDERER)
    if(NOT QGIS_FOUND)
        message(FATAL_ERROR "PALEO_WITH_QGIS_RENDERER requires QGIS headers and qgis_core")
    endif()
    find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Xml)
    add_library(qgis_render_bridge_core STATIC src/qgis_render_bridge.cpp)
    target_include_directories(qgis_render_bridge_core PUBLIC src "${QGIS_INCLUDE_DIR}")
    target_compile_features(qgis_render_bridge_core PUBLIC cxx_std_20)
    target_compile_definitions(qgis_render_bridge_core PRIVATE PALEO_QGIS_PREFIX_PATH="${QGIS_PREFIX_PATH}")
    target_link_libraries(qgis_render_bridge_core PUBLIC "${QGIS_CORE_LIBRARY}" Qt6::Core Qt6::Gui Qt6::Widgets Qt6::Xml)

    add_executable(qgis_render_bridge_selftest src/standalone_test.cpp)
    target_link_libraries(qgis_render_bridge_selftest PRIVATE qgis_render_bridge_core)
endif()
