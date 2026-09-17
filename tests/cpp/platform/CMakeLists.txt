# Platform tests — CTest names are platform.* (protocol: independent
# validation). Zero tests, all-skip or stub output never counts as passing
# (--no-tests=error in the gate). GUI tests run offscreen; the runtime
# closure (QGIS vendor lib + Qt lib) is prepended to PATH/LD_LIBRARY_PATH so
# tests exercise the real provider/plugin/CRS stack, never a fallback.

# PROJ data: the Windows vendor tree carries share/proj; on Linux the .so
# set resolves PROJ from the system package (/usr/share/proj).
if(EXISTS "${PALEO_QGIS_SDK_DIR}/share/proj")
    set(PWB_PROJ_DATA "${PALEO_QGIS_SDK_DIR}/share/proj")
else()
    set(PWB_PROJ_DATA "/usr/share/proj")
endif()
# GDAL data likewise.
if(EXISTS "${PALEO_QGIS_SDK_DIR}/data/gdal")
    set(PWB_GDAL_DATA "${PALEO_QGIS_SDK_DIR}/data/gdal")
elseif(EXISTS "${PALEO_QGIS_SDK_DIR}/data")
    set(PWB_GDAL_DATA "${PALEO_QGIS_SDK_DIR}/data")
else()
    set(PWB_GDAL_DATA "/usr/share/gdal")
endif()

function(pwb_add_platform_test name)
    add_executable(platform_${name} ${ARGN})
    target_compile_features(platform_${name} PRIVATE cxx_std_20)
    target_link_libraries(platform_${name} PRIVATE
        Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy)
    target_include_directories(platform_${name} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_compile_definitions(platform_${name} PRIVATE
        PWB_TEST_SRC_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
    add_test(NAME platform.${name} COMMAND platform_${name})
    set_tests_properties(platform.${name} PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA};GDAL_DATA=${PWB_GDAL_DATA}"
        TIMEOUT 300)
endfunction()

pwb_add_platform_test(toolpolicy_matrix test_tool_policy.cpp)
pwb_add_platform_test(toolpolicy_golden test_tool_policy_golden.cpp)
pwb_add_platform_test(qgis_smoke test_qgis_smoke.cpp)
pwb_add_platform_test(edit_cycle test_edit_cycle.cpp)
pwb_add_platform_test(lifecycle_cycles test_lifecycle.cpp)
pwb_add_platform_test(export_layout test_export.cpp)
pwb_add_platform_test(adapters_substitutes test_adapters.cpp)

# UI wiring test compiles the real MainWindow (moc included) next to the app.
add_executable(platform_ui_wiring test_ui_wiring.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/main_window.cpp)
set_target_properties(platform_ui_wiring PROPERTIES AUTOMOC ON)
target_compile_features(platform_ui_wiring PRIVATE cxx_std_20)
target_include_directories(platform_ui_wiring PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform)
target_link_libraries(platform_ui_wiring PRIVATE
    Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy)
add_test(NAME platform.ui_wiring COMMAND platform_ui_wiring)
set_tests_properties(platform.ui_wiring PROPERTIES
    ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA};GDAL_DATA=${PWB_GDAL_DATA}"
    TIMEOUT 300)

# App-level smoke: the real executable's self-check (fixtures + render +
# export in one process, exit code is the verdict).
add_test(NAME platform.qgis_smoke_app COMMAND pwb-platform --self-check)
set_tests_properties(platform.qgis_smoke_app PROPERTIES
    ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA};GDAL_DATA=${PWB_GDAL_DATA}"
    TIMEOUT 300)
