cmake_minimum_required(VERSION 3.21)
project(qgis_render_bridge LANGUAGES CXX)

option(PALEO_WITH_QGIS_RENDERER "Build the optional vendored-QGIS renderer bridge" OFF)
set(PALEO_QGIS_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/qgis" CACHE PATH
    "Path to the fixed QGIS source snapshot")
set(PALEO_QGIS_BUILD_DIR "${CMAKE_CURRENT_BINARY_DIR}/qgis_vendor" CACHE PATH
    "Out-of-tree build directory for the fixed QGIS source snapshot")
set(PALEO_QGIS_BUILD_JOBS "2" CACHE STRING "Parallel jobs for the QGIS source build")

if(PALEO_WITH_QGIS_RENDERER)
    include(ExternalProject)

    if(NOT EXISTS "${PALEO_QGIS_SOURCE_DIR}/UPSTREAM.md")
        message(FATAL_ERROR "PALEO_WITH_QGIS_RENDERER requires the vendored QGIS source at ${PALEO_QGIS_SOURCE_DIR}")
    endif()

    find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Xml Svg)

    set(PALEO_QGIS_OUTPUT_DIR "${PALEO_QGIS_BUILD_DIR}/output")
    set(PALEO_QGIS_LIBRARY_DIR "${PALEO_QGIS_OUTPUT_DIR}/lib")
    if(WIN32)
        set(PALEO_QGIS_CORE_LIBRARY "${PALEO_QGIS_LIBRARY_DIR}/qgis_core.lib")
        set(PALEO_QGIS_GUI_LIBRARY "${PALEO_QGIS_LIBRARY_DIR}/qgis_gui.lib")
        set(PALEO_QGIS_ANALYSIS_LIBRARY "${PALEO_QGIS_LIBRARY_DIR}/qgis_analysis.lib")
    else()
        set(PALEO_QGIS_CORE_LIBRARY "${PALEO_QGIS_LIBRARY_DIR}/libqgis_core${CMAKE_SHARED_LIBRARY_SUFFIX}")
        set(PALEO_QGIS_GUI_LIBRARY "${PALEO_QGIS_LIBRARY_DIR}/libqgis_gui${CMAKE_SHARED_LIBRARY_SUFFIX}")
        set(PALEO_QGIS_ANALYSIS_LIBRARY "${PALEO_QGIS_LIBRARY_DIR}/libqgis_analysis${CMAKE_SHARED_LIBRARY_SUFFIX}")
    endif()

    # QGIS needs its own source directory to be CMAKE_SOURCE_DIR, so build this
    # fixed source snapshot as a nested project instead of add_subdirectory().
    ExternalProject_Add(paleo_qgis_vendor
        SOURCE_DIR "${PALEO_QGIS_SOURCE_DIR}"
        BINARY_DIR "${PALEO_QGIS_BUILD_DIR}"
        CMAKE_ARGS
            -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}
            -DWITH_PYTHON=OFF
            -DWITH_BINDINGS=OFF
            -DWITH_DESKTOP=OFF
            -DWITH_QGIS_PROCESS=OFF
            -DWITH_3D=OFF
            -DWITH_GUI=ON
            -DWITH_ANALYSIS=ON
            -DWITH_AUTH=ON
            -DWITH_CRASH_HANDLER=OFF
            -DWITH_SERVER=OFF
            -DWITH_CUSTOM_WIDGETS=OFF
            -DWITH_QUICK=OFF
            -DWITH_QTWEBENGINE=OFF
            -DWITH_QTPOSITIONING=OFF
            -DWITH_INTERNAL_SPATIALINDEX=ON
            -DUSE_OPENCL=OFF
            -DENABLE_TESTS=OFF
            -DENABLE_LOCAL_BUILD_SHORTCUTS=ON
            -DUSE_CCACHE=OFF
            -DCMAKE_FIND_USE_PACKAGE_REGISTRY=FALSE
            -DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=FALSE
        BUILD_COMMAND "${CMAKE_COMMAND}" --build <BINARY_DIR> --target resources qgis_core qgis_gui qgis_analysis --parallel ${PALEO_QGIS_BUILD_JOBS}
        INSTALL_COMMAND ""
        BUILD_BYPRODUCTS
            "${PALEO_QGIS_CORE_LIBRARY}"
            "${PALEO_QGIS_GUI_LIBRARY}"
            "${PALEO_QGIS_ANALYSIS_LIBRARY}"
    )

    function(paleo_import_qgis_library target_name library_path)
        add_library(${target_name} SHARED IMPORTED GLOBAL)
        set_target_properties(${target_name} PROPERTIES IMPORTED_LOCATION "${library_path}")
        add_dependencies(${target_name} paleo_qgis_vendor)
    endfunction()

    paleo_import_qgis_library(paleo_qgis_core "${PALEO_QGIS_CORE_LIBRARY}")
    paleo_import_qgis_library(paleo_qgis_gui "${PALEO_QGIS_GUI_LIBRARY}")
    paleo_import_qgis_library(paleo_qgis_analysis "${PALEO_QGIS_ANALYSIS_LIBRARY}")

    # QGIS's public Core headers intentionally use unqualified includes across
    # its component subdirectories. Mirror the upstream Core target's complete
    # source-header search path instead of relying on a system QGIS install.
    file(GLOB_RECURSE PALEO_QGIS_CORE_HEADERS CONFIGURE_DEPENDS
        "${PALEO_QGIS_SOURCE_DIR}/src/core/*.h"
        "${PALEO_QGIS_SOURCE_DIR}/src/core/*.hpp"
    )
    set(PALEO_QGIS_CORE_INCLUDE_DIRS)
    foreach(header_path IN LISTS PALEO_QGIS_CORE_HEADERS)
        get_filename_component(header_dir "${header_path}" DIRECTORY)
        list(APPEND PALEO_QGIS_CORE_INCLUDE_DIRS "${header_dir}")
    endforeach()
    list(REMOVE_DUPLICATES PALEO_QGIS_CORE_INCLUDE_DIRS)

    add_library(qgis_render_bridge_core STATIC
        src/qgis_render_bridge.cpp
        src/style_codec.cpp
        src/gui_service.cpp
        src/geometry_service.cpp
    )
    target_include_directories(qgis_render_bridge_core SYSTEM PUBLIC
        "${PALEO_QGIS_SOURCE_DIR}/src/core"
        ${PALEO_QGIS_CORE_INCLUDE_DIRS}
        "${PALEO_QGIS_BUILD_DIR}"
        "${PALEO_QGIS_BUILD_DIR}/src/core"
    )
    target_include_directories(qgis_render_bridge_core PUBLIC src)
    target_compile_features(qgis_render_bridge_core PUBLIC cxx_std_20)
    target_compile_definitions(qgis_render_bridge_core PRIVATE
        PALEO_QGIS_PREFIX_PATH="${PALEO_QGIS_OUTPUT_DIR}"
    )
    target_link_libraries(qgis_render_bridge_core PUBLIC
        paleo_qgis_core
        paleo_qgis_gui
        paleo_qgis_analysis
        Qt6::Core
        Qt6::Gui
        Qt6::Widgets
        Qt6::Xml
        Qt6::Svg
    )
    set_target_properties(qgis_render_bridge_core PROPERTIES
        BUILD_RPATH "${PALEO_QGIS_LIBRARY_DIR}"
    )

    add_executable(qgis_render_bridge_selftest src/standalone_test.cpp)
    target_link_libraries(qgis_render_bridge_selftest PRIVATE qgis_render_bridge_core)
    set_target_properties(qgis_render_bridge_selftest PROPERTIES
        BUILD_RPATH "${PALEO_QGIS_LIBRARY_DIR}"
    )
endif()
