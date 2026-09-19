# UI-02 — ui_widgets tests. ctest names: ui_widgets.* (Qt-free, headless
# except where offscreen/QGIS is required). The core test links no Qt;
# the modelview/widgets tests run under QT_QPA_PLATFORM=offscreen; the
# QGIS test only exists where the vendored SDK was admitted and uses the
# same runtime-closure env as tests/cpp/platform.

# Qt-free cores (epoch switching / facies / HUD / QC / tree sync).
add_executable(ui_widgets.core core_test.cpp)
target_compile_features(ui_widgets.core PRIVATE cxx_std_20)
target_link_libraries(ui_widgets.core PRIVATE Pwb::UiWidgetsCore)
target_include_directories(ui_widgets.core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_widgets.core COMMAND ui_widgets.core)
set_tests_properties(ui_widgets.core PROPERTIES TIMEOUT 120)

if(TARGET pwb_ui_widgets)
    # Model/view battery: virtual table model, stable selection, keyed
    # reconciliation, latest-only async query.
    add_executable(ui_widgets.modelview modelview_test.cpp)
    target_compile_features(ui_widgets.modelview PRIVATE cxx_std_20)
    target_link_libraries(ui_widgets.modelview PRIVATE
        Pwb::UiWidgets Qt6::Widgets)
    target_include_directories(ui_widgets.modelview PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_widgets.modelview COMMAND ui_widgets.modelview)
    set_tests_properties(ui_widgets.modelview PROPERTIES
        TIMEOUT 300
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")

    # Component smoke: every ported widget constructs + responds.
    add_executable(ui_widgets.widgets_smoke widgets_smoke_test.cpp)
    target_compile_features(ui_widgets.widgets_smoke PRIVATE cxx_std_20)
    target_link_libraries(ui_widgets.widgets_smoke PRIVATE
        Pwb::UiWidgets Qt6::Widgets)
    target_include_directories(ui_widgets.widgets_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_widgets.widgets_smoke
             COMMAND ui_widgets.widgets_smoke)
    set_tests_properties(ui_widgets.widgets_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()

# QGIS stack tests — real QGIS session, same runtime closure the
# platform tests use (vendor lib + Qt lib on PATH/LD_LIBRARY_PATH,
# PROJ/GDAL data pinned, offscreen).
if(TARGET pwb_ui_widgets_qgis)
    # PROJ/GDAL data dirs: same derivation as tests/cpp/platform.
    if(EXISTS "${PALEO_QGIS_SDK_DIR}/share/proj")
        set(PWB_PROJ_DATA "${PALEO_QGIS_SDK_DIR}/share/proj")
    else()
        set(PWB_PROJ_DATA "/usr/share/proj")
    endif()
    if(EXISTS "${PALEO_QGIS_SDK_DIR}/data/pcs.csv")
        set(PWB_GDAL_DATA "${PALEO_QGIS_SDK_DIR}/data")
    elseif(EXISTS "/usr/share/gdal/pcs.csv")
        set(PWB_GDAL_DATA "/usr/share/gdal")
    else()
        set(PWB_GDAL_DATA "")
    endif()
    set(PWB_UIW_GDAL_ENV "")
    if(PWB_GDAL_DATA)
        set(PWB_UIW_GDAL_ENV ";GDAL_DATA=${PWB_GDAL_DATA}")
    endif()

    add_executable(ui_widgets.qgis qgis_test.cpp)
    target_compile_features(ui_widgets.qgis PRIVATE cxx_std_20)
    target_link_libraries(ui_widgets.qgis PRIVATE
        Pwb::UiWidgetsQgis Qt6::Widgets)
    target_include_directories(ui_widgets.qgis PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_widgets.qgis COMMAND ui_widgets.qgis)
    set_tests_properties(ui_widgets.qgis PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_UIW_GDAL_ENV}"
        TIMEOUT 300)
endif()
