# UI-05 — ui_map tests. ctest names: ui_map.* (Qt-free + offscreen Qt +
# real-QGIS smoke). The oracle replay is headless; the widget smokes run
# under QT_QPA_PLATFORM=offscreen with the QGIS runtime closure on
# LD_LIBRARY_PATH/PATH (same env protocol as tests/cpp/platform).

# QSignalSpy lives in Qt6::Test — not part of the platform component list.
find_package(Qt6 COMPONENTS Test)

# PROJ/GDAL data probes — mirror tests/cpp/platform/CMakeLists.txt so the
# provider stack resolves real CRS/driver data (never a fake success).
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
if(PWB_GDAL_DATA)
    set(PWB_GDAL_DATA_ENV ";GDAL_DATA=${PWB_GDAL_DATA}")
else()
    set(PWB_GDAL_DATA_ENV "")
endif()

# --- oracle replay (Qt-free) ----------------------------------------------
add_executable(ui_map.oracle_replay oracle_replay_test.cpp)
target_compile_features(ui_map.oracle_replay PRIVATE cxx_std_20)
target_link_libraries(ui_map.oracle_replay PRIVATE Pwb::UiMap Pwb::Domain)
target_include_directories(ui_map.oracle_replay PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(ui_map.oracle_replay PRIVATE
    PWB_UI_MAP_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/ui_map_oracle.json")
add_test(NAME ui_map.oracle_replay COMMAND ui_map.oracle_replay)
set_tests_properties(ui_map.oracle_replay PROPERTIES TIMEOUT 120)

# --- Qt widget smoke (offscreen, no QGIS) ----------------------------------
if(TARGET pwb_ui_map_qt)
    add_executable(ui_map.qt_widgets_smoke qt_widgets_smoke_test.cpp)
    target_compile_features(ui_map.qt_widgets_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_map.qt_widgets_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_map.qt_widgets_smoke PRIVATE
        Pwb::UiMapQt Qt6::Widgets Qt6::Test)
    target_include_directories(ui_map.qt_widgets_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_map.qt_widgets_smoke
             COMMAND ui_map.qt_widgets_smoke)
    set_tests_properties(ui_map.qt_widgets_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()

# --- QGIS-backed smoke (offscreen, real runtime) ---------------------------
if(TARGET pwb_ui_map_qgis)
    add_executable(ui_map.qgis_smoke qgis_smoke_test.cpp)
    target_compile_features(ui_map.qgis_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_map.qgis_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_map.qgis_smoke PRIVATE
        Pwb::UiMapQgis Pwb::Qgis Qt6::Widgets Qt6::Test)
    target_include_directories(ui_map.qgis_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_map.qgis_smoke COMMAND ui_map.qgis_smoke)
    set_tests_properties(ui_map.qgis_smoke PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 300)
endif()
