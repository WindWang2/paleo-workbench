# QGIS SDK admission for the CPP-A platform (A is the QGIS SDK owner).
#
# Reuse policy (prompt A1 / docs/development/cpp-platform/00-baseline.md):
#   * The vendored QGIS 4.2.0 install tree produced by the verified bridge
#     recipe is consumed READ-ONLY via imported targets. Paths default to the
#     main worktree on this machine and are cache-overridable.
#   * Manifest mismatch (Qt/MSVC/CRT/version) => rebuild into this worktree
#     under build/qgis-vendor with <=2 jobs; never write the main repo tree.
#   * One Qt ABI: Qt 6.8.0 msvc2022_64. No PySide, no conda, no system Qt.

set(PWB_QT_PREFIX "C:/deps/Qt/6.8.0/msvc2022_64" CACHE PATH "Qt 6.8 dev prefix (single ABI)")
set(PALEO_QGIS_SOURCE_DIR "C:/Users/wangj.KEVIN/projects/paleo-workbench/third_party/qgis"
    CACHE PATH "Vendored QGIS 4.2.0 source snapshot (headers; read-only)")
set(PALEO_QGIS_SDK_DIR "C:/Users/wangj.KEVIN/projects/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor/output"
    CACHE PATH "QGIS install tree (lib/bin/plugins/data; read-only)")
set(PALEO_QGIS_BUILD_DIR "C:/Users/wangj.KEVIN/projects/paleo-workbench/native/qgis_render_bridge/build/qgis-vendor"
    CACHE PATH "QGIS build tree that carries the generated qgsconfig.h (read-only)")

find_package(Qt6 6.8 REQUIRED COMPONENTS Core Gui Widgets Xml Svg)

if(NOT EXISTS "${PALEO_QGIS_SOURCE_DIR}/UPSTREAM.md")
    message(FATAL_ERROR "vendored QGIS source snapshot missing: ${PALEO_QGIS_SOURCE_DIR}")
endif()
foreach(_lib qgis_core qgis_gui qgis_analysis)
    if(NOT EXISTS "${PALEO_QGIS_SDK_DIR}/lib/${_lib}.lib")
        message(FATAL_ERROR "QGIS SDK import library missing: ${PALEO_QGIS_SDK_DIR}/lib/${_lib}.lib (rebuild the vendor SDK per 00-baseline.md)")
    endif()
endforeach()

# Import libs + DLLs.
foreach(_comp Core Gui Analysis)
    string(TOLOWER "${_comp}" _lower)
    add_library(PwbQgis::${_comp} SHARED IMPORTED GLOBAL)
    set_target_properties(PwbQgis::${_comp} PROPERTIES
        IMPORTED_IMPLIB   "${PALEO_QGIS_SDK_DIR}/lib/qgis_${_lower}.lib"
        IMPORTED_LOCATION "${PALEO_QGIS_SDK_DIR}/bin/qgis_${_lower}.dll")
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
)
# gui/analysis recursive dirs appended separately (readability of long lists).
target_include_directories(PwbQgis::Sdk INTERFACE ${PWB_QGIS_GUI_DIRS})
target_include_directories(PwbQgis::Sdk INTERFACE ${PWB_QGIS_ANALYSIS_DIRS})
target_include_directories(PwbQgis::Sdk INTERFACE
    "${PALEO_QGIS_BUILD_DIR}"
    "${PALEO_QGIS_BUILD_DIR}/src/core"
)
target_link_libraries(PwbQgis::Sdk INTERFACE
    PwbQgis::Core PwbQgis::Gui PwbQgis::Analysis
    Qt6::Core Qt6::Gui Qt6::Widgets Qt6::Xml Qt6::Svg)

# Runtime closure location for tests/apps (PATH prepend + prefix path).
set(PALEO_QGIS_RUNTIME "${PALEO_QGIS_SDK_DIR}/bin" CACHE INTERNAL "QGIS runtime DLL dir")
set(PWB_QT_RUNTIME "${PWB_QT_PREFIX}/bin" CACHE INTERNAL "Qt runtime DLL dir")
