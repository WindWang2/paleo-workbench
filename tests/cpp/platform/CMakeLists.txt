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
# GDAL data: only the real GDAL data dir (marker file probe) counts — the
# vendor output/data on Linux is QGIS resources, not GDAL's csv tree.
if(EXISTS "${PALEO_QGIS_SDK_DIR}/data/pcs.csv")
    set(PWB_GDAL_DATA "${PALEO_QGIS_SDK_DIR}/data")
elseif(EXISTS "/usr/share/gdal/pcs.csv")
    set(PWB_GDAL_DATA "/usr/share/gdal")
else()
    set(PWB_GDAL_DATA "")
endif()
if(PWB_GDAL_DATA)
    set(PWB_GDAL_DATA_ENV ";GDAL_DATA=${PWB_GDAL_DATA}")
else()
    set(PWB_GDAL_DATA_ENV "")
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
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
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
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
    TIMEOUT 300)

# Project session test: real MainWindow + real B store (.paleo open /
# recovery / working copies / save / reopen). Needs B in the build.
if(PWB_BUILD_DATA)
    add_executable(platform_project_session test_project_session.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/main_window.cpp)
    set_target_properties(platform_project_session PROPERTIES AUTOMOC ON)
    target_compile_features(platform_project_session PRIVATE cxx_std_20)
    target_include_directories(platform_project_session PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform)
    target_link_libraries(platform_project_session PRIVATE
        Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy Pwb::Data)
    target_compile_definitions(platform_project_session PRIVATE
        PWB_TEST_SRC_DIR="${CMAKE_CURRENT_SOURCE_DIR}")
    add_test(NAME platform.project_session COMMAND platform_project_session)
    set_tests_properties(platform.project_session PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 300)
endif()

# Attribute UI test (M1): real MainWindow with D's slice dock + E's
# kernels + real B store in one process. Only when all of D/E/B are built;
# the same guards the app itself uses.
if(PWB_BUILD_DATA AND PWB_BUILD_SEISMIC_VIEWER
        AND PWB_BUILD_SEISMIC_ATTRIBUTES)
    add_executable(platform_attribute_ui test_attribute_ui.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/main_window.cpp)
    set_target_properties(platform_attribute_ui PROPERTIES AUTOMOC ON)
    target_compile_features(platform_attribute_ui PRIVATE cxx_std_20)
    target_include_directories(platform_attribute_ui PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform)
    target_link_libraries(platform_attribute_ui PRIVATE
        Pwb::Application Pwb::Ui Pwb::Qgis Pwb::ToolPolicy Pwb::Data
        Pwb::SeismicViewer Pwb::SeismicAttributes Pwb::Visualization
        Pwb::Science Pwb::Workflow)
    target_compile_definitions(platform_attribute_ui PRIVATE
        PWB_TEST_SRC_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
        PWB_WITH_SEISMIC_VIEWER=1 PWB_WITH_SEISMIC_ATTRIBUTES=1)
    # M3: real SEG-Y import path (reader + B publication) when present.
    if(PWB_BUILD_SEISMIC_IO)
        target_link_libraries(platform_attribute_ui PRIVATE Pwb::SeismicIo)
        target_compile_definitions(platform_attribute_ui PRIVATE
            PWB_WITH_SEISMIC_IO=1
            PWB_REALDATA_DIR="${CMAKE_SOURCE_DIR}/tests/fixtures/realdata"
            PWB_ATTRIBUTE_FIXTURES="${CMAKE_SOURCE_DIR}/tests/cpp/seismic_attributes/fixtures")
    endif()
    add_test(NAME platform.attribute_ui COMMAND platform_attribute_ui)
    set_tests_properties(platform.attribute_ui PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 300)
endif()

# App-level smoke: the real executable's self-check (fixtures + render +
# export in one process, exit code is the verdict).
add_test(NAME platform.qgis_smoke_app COMMAND pwb-platform --self-check)
set_tests_properties(platform.qgis_smoke_app PROPERTIES
    ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
    TIMEOUT 300)
