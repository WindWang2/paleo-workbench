# UI-13 — ui_composite tests. ctest names: ui_composite.* —
# Qt-free core semantics headless; Qt widget shells get offscreen smoke
# tests and the QGIS adapters get bridge smoke tests as those targets
# land.

add_executable(ui_composite.core core_test.cpp)
target_compile_features(ui_composite.core PRIVATE cxx_std_20)
target_link_libraries(ui_composite.core PRIVATE Pwb::UiComposite)
target_include_directories(ui_composite.core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_composite.core COMMAND ui_composite.core)
set_tests_properties(ui_composite.core PROPERTIES TIMEOUT 120)

# Qt widget smoke (offscreen): every ported widget constructs +
# responds; the document shell hosts an injected canvas.
if(TARGET pwb_ui_composite_qt)
    add_executable(ui_composite.qt_widgets_smoke
        qt_widgets_smoke_test.cpp)
    target_compile_features(ui_composite.qt_widgets_smoke
        PRIVATE cxx_std_20)
    set_target_properties(ui_composite.qt_widgets_smoke
        PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_composite.qt_widgets_smoke PRIVATE
        Pwb::UiCompositeQt Qt6::Widgets)
    target_include_directories(ui_composite.qt_widgets_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    if(TARGET Pwb::UiControllersQt)
        target_compile_definitions(ui_composite.qt_widgets_smoke
            PRIVATE PWB_HAVE_LINKED_WORKSPACE=1)
    endif()
    add_test(NAME ui_composite.qt_widgets_smoke
             COMMAND ui_composite.qt_widgets_smoke)
    set_tests_properties(ui_composite.qt_widgets_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        # Transitive link reaches the vendored QGIS runtime (via
        # UiShellQt); prepend so vendored deps resolve.
        ENVIRONMENT_MODIFICATION
        "LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}")
endif()

# QGIS adapter smoke — real QgsGeometry + QgisCanvasShim, same runtime
# closure as libs/ui_widgets' qgis test (vendor lib + Qt lib on
# PATH/LD_LIBRARY_PATH, PROJ/GDAL data pinned, offscreen).
if(TARGET pwb_ui_composite_qgis)
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
    set(PWB_UIC_GDAL_ENV "")
    if(PWB_GDAL_DATA)
        set(PWB_UIC_GDAL_ENV ";GDAL_DATA=${PWB_GDAL_DATA}")
    endif()

    add_executable(ui_composite.qgis_smoke qgis_smoke_test.cpp)
    target_compile_features(ui_composite.qgis_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_composite.qgis_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_composite.qgis_smoke PRIVATE
        Pwb::UiCompositeQgis Qt6::Widgets)
    target_include_directories(ui_composite.qgis_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_composite.qgis_smoke COMMAND ui_composite.qgis_smoke)
    set_tests_properties(ui_composite.qgis_smoke PROPERTIES
        TIMEOUT 300
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_UIC_GDAL_ENV}")
endif()
