# QGIS SDK admission for the CPP-A platform (A is the QGIS SDK owner).
#
# Reuse policy (prompt A1 / docs/development/cpp-platform/00-baseline.md):
#   * The vendored QGIS 4.2.0 install tree produced by the verified bridge
#     recipe is consumed READ-ONLY via imported targets. Paths default to the
#     main worktree on the host and are cache-overridable (or injected via
#     same-named environment variables); no machine-absolute paths are baked
#     into the repository for Linux.
#   * Manifest mismatch (Qt/compiler/CRT/version) => rebuild into this
#     worktree under build/qgis-vendor with <=2 jobs; never write the main
#     repo tree.
#   * One Qt ABI per process. On the Windows host: Qt 6.8.0 msvc2022_64. On
#     Linux: the single system Qt 6 dev prefix the vendored QGIS .so set
#     actually resolves against (ldd evidence), pinned via PWB_QT_PREFIX.
#     No PySide, no conda, no second Qt.

# ---- SDK locations: cache var > environment > host default ----
function(pwb_sdk_path var default)
    if(NOT DEFINED ${var})
        if(DEFINED ENV{${var}})
            set(${var} "$ENV{${var}}" CACHE PATH "${var} (from environment)")
        else()
            set(${var} "${default}" CACHE PATH "${var}")
        endif()
    endif()
endfunction()

if(WIN32)
    pwb_sdk_path(PWB_QT_PREFIX "C:/deps/Qt/6.8.0/msvc2022_64")
    pwb_sdk_path(PALEO_QGIS_SOURCE_DIR
        "C:/Users/wangj.KEVIN/projects/paleo-workbench/third_party/qgis")
    pwb_sdk_path(PALEO_QGIS_SDK_DIR
        "C:/Users/wangj.KEVIN/projects/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor/output")
    pwb_sdk_path(PALEO_QGIS_BUILD_DIR
        "C:/Users/wangj.KEVIN/projects/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor")
else()
    # Sibling main checkout of the same bare repo on this host
    # (<repo>/main); overridable per machine via cache or environment.
    get_filename_component(PWB_SIBLING_MAIN
        "${CMAKE_CURRENT_SOURCE_DIR}/../../main" ABSOLUTE)
    pwb_sdk_path(PWB_QT_PREFIX "/usr")
    pwb_sdk_path(PALEO_QGIS_SOURCE_DIR "${PWB_SIBLING_MAIN}/third_party/qgis")
    pwb_sdk_path(PALEO_QGIS_SDK_DIR
        "${PWB_SIBLING_MAIN}/native/qgis_render_bridge/build/qgis-vendor/output")
    pwb_sdk_path(PALEO_QGIS_BUILD_DIR
        "${PWB_SIBLING_MAIN}/native/qgis_render_bridge/build/qgis-vendor")
endif()

# PWB_QT_PREFIX must actually constrain find_package — not just PATH. When
# set, it is prepended to CMAKE_PREFIX_PATH and the resolved Qt6 package is
# verified to live inside it; anything else is a configure error.
if(PWB_QT_PREFIX)
    list(PREPEND CMAKE_PREFIX_PATH "${PWB_QT_PREFIX}")
endif()
find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Widgets Xml Svg PrintSupport)
if(PWB_QT_PREFIX)
    cmake_path(IS_PREFIX PWB_QT_PREFIX "${Qt6_DIR}" _qt_in_prefix)
    if(NOT _qt_in_prefix)
        message(FATAL_ERROR
            "Qt6 resolved outside PWB_QT_PREFIX (${PWB_QT_PREFIX}): ${Qt6_DIR}. "
            "A second Qt ABI would enter the process — fix the prefix instead "
            "of weakening the check.")
    endif()
endif()

if(NOT EXISTS "${PALEO_QGIS_SOURCE_DIR}/UPSTREAM.md")
    message(FATAL_ERROR "vendored QGIS source snapshot missing: ${PALEO_QGIS_SOURCE_DIR}")
endif()
foreach(_lib qgis_core qgis_gui qgis_analysis)
    if(WIN32)
        if(NOT EXISTS "${PALEO_QGIS_SDK_DIR}/lib/${_lib}.lib")
            message(FATAL_ERROR "QGIS SDK import library missing: ${PALEO_QGIS_SDK_DIR}/lib/${_lib}.lib (rebuild the vendor SDK per 00-baseline.md)")
        endif()
    else()
        if(NOT EXISTS "${PALEO_QGIS_SDK_DIR}/lib/lib${_lib}.so")
            message(FATAL_ERROR "QGIS SDK shared library missing: ${PALEO_QGIS_SDK_DIR}/lib/lib${_lib}.so (rebuild the vendor SDK per 00-baseline.md)")
        endif()
    endif()
endforeach()

# Import the QGIS libraries (Windows: import lib + DLL; Linux: .so).
foreach(_comp Core Gui Analysis)
    string(TOLOWER "${_comp}" _lower)
    add_library(PwbQgis::${_comp} SHARED IMPORTED GLOBAL)
    if(WIN32)
        set_target_properties(PwbQgis::${_comp} PROPERTIES
            IMPORTED_IMPLIB   "${PALEO_QGIS_SDK_DIR}/lib/qgis_${_lower}.lib"
            IMPORTED_LOCATION "${PALEO_QGIS_SDK_DIR}/bin/qgis_${_lower}.dll")
    else()
        set_target_properties(PwbQgis::${_comp} PROPERTIES
            IMPORTED_LOCATION "${PALEO_QGIS_SDK_DIR}/lib/libqgis_${_lower}.so")
    endif()
endforeach()

# QGIS core/gui headers include across their component subdirectories without
# qualifiers: mirror the upstream target search path (same approach as the
# verified bridge CMake, extended to gui/analysis which the platform needs).
file(GLOB_RECURSE PWB_QGIS_CORE_HEADERS   CONFIGURE_DEPENDS
    "${PALEO_QGIS_SOURCE_DIR}/src/core/*.h"   "${PALEO_QGIS_SOURCE_DIR}/src/core/*.hpp")
file(GLOB_RECURSE PWB_QGIS_GUI_HEADERS    CONFIGURE_DEPENDS
    "${PALEO_QGIS_SOURCE_DIR}/src/gui/*.h"    "${PALEO_QGIS_SOURCE_DIR}/src/gui/*.hpp")
file(GLOB_RECURSE PWB_QGIS_ANALYSIS_HEADERS CONFIGURE_DEPENDS
    "${PALEO_QGIS_SOURCE_DIR}/src/analysis/*.h" "${PALEO_QGIS_SOURCE_DIR}/src/analysis/*.hpp")
function(pwb_qgis_header_dirs out_var)
    set(_dirs)
    foreach(_header IN LISTS ARGN)
        get_filename_component(_dir "${_header}" DIRECTORY)
        list(APPEND _dirs "${_dir}")
    endforeach()
    list(REMOVE_DUPLICATES _dirs)
    set(${out_var} "${_dirs}" PARENT_SCOPE)
endfunction()
pwb_qgis_header_dirs(PWB_QGIS_CORE_DIRS   ${PWB_QGIS_CORE_HEADERS})
pwb_qgis_header_dirs(PWB_QGIS_GUI_DIRS    ${PWB_QGIS_GUI_HEADERS})
pwb_qgis_header_dirs(PWB_QGIS_ANALYSIS_DIRS ${PWB_QGIS_ANALYSIS_HEADERS})

add_library(PwbQgis::Sdk INTERFACE IMPORTED GLOBAL)
target_include_directories(PwbQgis::Sdk INTERFACE
    "${PALEO_QGIS_SOURCE_DIR}/src/core"
    "${PALEO_QGIS_SOURCE_DIR}/src/gui"
    "${PALEO_QGIS_SOURCE_DIR}/src/analysis"
    ${PWB_QGIS_CORE_DIRS}
    # QGIS public headers include their vendored nlohmann
    # (qgsabstractgeometry.h -> nlohmann/json_fwd.hpp); the snapshot's
    # external/ tree is part of the SDK's own header closure.
    "${PALEO_QGIS_SOURCE_DIR}/external/nlohmann"
)
# gui/analysis recursive dirs appended separately (readability of long lists).
target_include_directories(PwbQgis::Sdk INTERFACE ${PWB_QGIS_GUI_DIRS})
target_include_directories(PwbQgis::Sdk INTERFACE ${PWB_QGIS_ANALYSIS_DIRS})
target_include_directories(PwbQgis::Sdk INTERFACE
    "${PALEO_QGIS_BUILD_DIR}"
    "${PALEO_QGIS_BUILD_DIR}/src/core"
    "${PALEO_QGIS_BUILD_DIR}/src/gui"
    "${PALEO_QGIS_BUILD_DIR}/src/analysis"
)
# QGIS public headers include <ogr_api.h> whenever the vendored build was
# configured against GDAL (qgsvectorfilewriter.h). The vendored .so set
# already links a GDAL — surface its headers through the SDK so consumers
# compile against the same ABI they run. QUIET: SDK snapshots built without
# this exposure keep the previous include closure.
find_package(GDAL QUIET)
if(GDAL_FOUND AND GDAL_INCLUDE_DIR)
    target_include_directories(PwbQgis::Sdk INTERFACE "${GDAL_INCLUDE_DIR}")
endif()
target_link_libraries(PwbQgis::Sdk INTERFACE
    PwbQgis::Core PwbQgis::Gui PwbQgis::Analysis
    Qt6::Core Qt6::Gui Qt6::Widgets Qt6::Xml Qt6::Svg Qt6::PrintSupport)

# BEGIN CONV-27
# Generated ui_*.h (e.g. ui_qgsrendererpropsdialogbase.h pulled by the
# symbology dialogs) live in the vendor build's src/ui autogen dir.
target_include_directories(PwbQgis::Sdk INTERFACE
    "${PALEO_QGIS_BUILD_DIR}/src/ui")
# QGIS headers include their bundled/external dependencies unqualified
# (nlohmann/json_fwd.hpp from qgsabstractgeometry.h, qwt from gui headers,
# spatialindex from analysis headers, geos_c.h from geometry headers). The
# vendored QGIS build carried these as -isystem; the imported SDK must too
# or every consumer TU fails at the first core header. geos/gdal headers
# come from the same deps prefix the vendor build resolved against
# (PWB_QGIS_DEPS_PREFIX, cache/env overridable).
pwb_sdk_path(PWB_QGIS_DEPS_PREFIX "/home/kevin/pwb-sdks/root/usr")
file(GLOB _pwb_qwt_dir "${PALEO_QGIS_SOURCE_DIR}/external/qwt-*")
target_include_directories(PwbQgis::Sdk INTERFACE
    "${PALEO_QGIS_SOURCE_DIR}/external/nlohmann"
    "${PALEO_QGIS_SOURCE_DIR}/external/spatialindex/include"
    "${PWB_QGIS_DEPS_PREFIX}/include")
if(_pwb_qwt_dir)
    list(GET _pwb_qwt_dir 0 _pwb_qwt_first)
    target_include_directories(PwbQgis::Sdk INTERFACE "${_pwb_qwt_first}")
endif()
# END CONV-27

if(WIN32)
    # Runtime closure location for tests/apps (PATH prepend + prefix path).
    set(PALEO_QGIS_RUNTIME "${PALEO_QGIS_SDK_DIR}/bin" CACHE INTERNAL "QGIS runtime DLL dir")
    set(PWB_QT_RUNTIME "${PWB_QT_PREFIX}/bin" CACHE INTERNAL "Qt runtime DLL dir")
else()
    # Linux: shared objects and QGIS provider plugins live under lib/.
    set(PALEO_QGIS_RUNTIME "${PALEO_QGIS_SDK_DIR}/lib" CACHE INTERNAL "QGIS runtime SO dir")
    set(PWB_QT_RUNTIME "${PWB_QT_PREFIX}/lib" CACHE INTERNAL "Qt runtime SO dir")
endif()
