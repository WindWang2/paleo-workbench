# UI-15 — ui_canvas tests. ctest names: ui_canvas.* (Qt-free core smoke +
# offscreen Qt widgets smoke + real-QGIS smoke). Same env protocol as
# libs/ui_map/ui_map_tests — offscreen Qt for widgets; the QGIS runtime
# closure on LD_LIBRARY_PATH/PATH for the vendored stack.

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

# --- core smoke (Qt-free) -------------------------------------------------
add_executable(ui_canvas.core_smoke core_smoke_test.cpp)
target_compile_features(ui_canvas.core_smoke PRIVATE cxx_std_20)
target_link_libraries(ui_canvas.core_smoke PRIVATE
    Pwb::UiCanvasCore Pwb::Domain)
target_include_directories(ui_canvas.core_smoke PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_canvas.core_smoke COMMAND ui_canvas.core_smoke)
set_tests_properties(ui_canvas.core_smoke PROPERTIES TIMEOUT 120)

# --- Qt widget smoke (offscreen, no QGIS) ----------------------------------
if(TARGET pwb_ui_canvas)
    add_executable(ui_canvas.fallback_backend fallback_backend_test.cpp)
    target_compile_features(ui_canvas.fallback_backend PRIVATE cxx_std_20)
    set_target_properties(ui_canvas.fallback_backend PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_canvas.fallback_backend PRIVATE
        Pwb::UiCanvas Qt6::Widgets Qt6::Test)
    target_include_directories(ui_canvas.fallback_backend PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_canvas.fallback_backend
             COMMAND ui_canvas.fallback_backend)
    set_tests_properties(ui_canvas.fallback_backend PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        # QGIS vendor runtime closure (Pwb::UiCanvas now reaches the task
        # bridge).
        ENVIRONMENT_MODIFICATION "LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}")

    add_executable(ui_canvas.qt_widgets_smoke qt_widgets_smoke_test.cpp)
    target_compile_features(ui_canvas.qt_widgets_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_canvas.qt_widgets_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_canvas.qt_widgets_smoke PRIVATE
        Pwb::UiCanvas Qt6::Widgets Qt6::Test)
    target_include_directories(ui_canvas.qt_widgets_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_canvas.qt_widgets_smoke
             COMMAND ui_canvas.qt_widgets_smoke)
    set_tests_properties(ui_canvas.qt_widgets_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        # QGIS vendor runtime closure — the task bridge reaches
        # QgsApplication::taskManager().
        ENVIRONMENT_MODIFICATION "LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}")
endif()

# --- QGIS-backed smoke (offscreen, real runtime) ---------------------------
if(TARGET pwb_ui_canvas_qgis)
    add_executable(ui_canvas.qgis_smoke qgis_smoke_test.cpp)
    target_compile_features(ui_canvas.qgis_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_canvas.qgis_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_canvas.qgis_smoke PRIVATE
        Pwb::UiCanvasQgis Pwb::Qgis Qt6::Widgets Qt6::Test)
    target_include_directories(ui_canvas.qgis_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_canvas.qgis_smoke COMMAND ui_canvas.qgis_smoke)
    set_tests_properties(ui_canvas.qgis_smoke PROPERTIES
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
        TIMEOUT 300)
endif()
