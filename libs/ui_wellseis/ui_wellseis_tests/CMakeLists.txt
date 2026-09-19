# UI-09 — ui_wellseis tests. ctest names: ui_wellseis.* (Qt-free core +
# offscreen Qt + real-QGIS smoke). The Qt widget smokes run under
# QT_QPA_PLATFORM=offscreen; the QGIS smoke carries the same runtime env
# protocol as libs/ui_map/ui_map_tests.

# QSignalSpy lives in Qt6::Test — not part of the platform component list.
find_package(Qt6 COMPONENTS Test)

# PROJ/GDAL data probes — mirror libs/ui_map/ui_map_tests so the provider
# stack resolves real CRS/driver data (never a fake success).
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

# --- Qt-free core smoke ----------------------------------------------------
add_executable(ui_wellseis.core_smoke core_smoke_test.cpp)
target_compile_features(ui_wellseis.core_smoke PRIVATE cxx_std_20)
target_link_libraries(ui_wellseis.core_smoke PRIVATE
    Pwb::UiWellseis Pwb::Domain Pwb::UiWorkers Pwb::WellScience)
target_include_directories(ui_wellseis.core_smoke PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_wellseis.core_smoke COMMAND ui_wellseis.core_smoke)
set_tests_properties(ui_wellseis.core_smoke PROPERTIES TIMEOUT 120)

# --- Qt widget smoke (offscreen, no QGIS) ----------------------------------
if(TARGET pwb_ui_wellseis_qt)
    add_executable(ui_wellseis.qt_widgets_smoke qt_widgets_smoke_test.cpp)
    target_compile_features(ui_wellseis.qt_widgets_smoke
        PRIVATE cxx_std_20)
    set_target_properties(ui_wellseis.qt_widgets_smoke
        PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_wellseis.qt_widgets_smoke PRIVATE
        Pwb::UiWellseisQt Qt6::Widgets Qt6::Test)
    target_include_directories(ui_wellseis.qt_widgets_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_wellseis.qt_widgets_smoke
             COMMAND ui_wellseis.qt_widgets_smoke)
    set_tests_properties(ui_wellseis.qt_widgets_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()

# --- QGIS-backed smoke (offscreen, real runtime) ---------------------------
if(TARGET pwb_ui_wellseis_qgis)
    add_executable(ui_wellseis.qgis_smoke qgis_smoke_test.cpp)
    target_compile_features(ui_wellseis.qgis_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_wellseis.qgis_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_wellseis.qgis_smoke PRIVATE
        Pwb::UiWellseisQgis Pwb::Qgis Qt6::Widgets Qt6::Test)
    target_include_directories(ui_wellseis.qgis_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_wellseis.qgis_smoke COMMAND ui_wellseis.qgis_smoke)
    set_tests_properties(ui_wellseis.qgis_smoke PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 300)
endif()
