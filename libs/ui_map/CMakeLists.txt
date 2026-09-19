# UI-05 — qgs-map slice: Qt-free map/chrome core, Qt panels, and the
# QGIS-backed canvas/work-area/mapping-page shells.
#
# Layering (repo convention — ui_shell/ui split):
#   pwb_ui_map       Qt-free core (oracle-replayed against the Python page)
#   pwb_ui_map_qt    Qt Widgets shells that do NOT need QGIS (dock manager,
#                    layer tree, document/chrome panels, item reconcile,
#                    chrome painter)
#   pwb_ui_map_qgis  QGIS-backed surfaces (DisplayMapCanvas/MapSession host,
#                    MapCanvasPanel, WorkAreaMapWidget, constrained
#                    MappingPage) — only where the SDK is admitted.

add_library(pwb_ui_map STATIC
    src/map_chrome_core.cpp
)
add_library(Pwb::UiMap ALIAS pwb_ui_map)
target_include_directories(pwb_ui_map PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_map PUBLIC cxx_std_20)
target_link_libraries(pwb_ui_map PUBLIC Pwb::Domain)

if(TARGET Qt6::Widgets AND TARGET Pwb::UiShellQt)
    add_library(pwb_ui_map_qt STATIC
        src/item_reconcile.cpp
        src/map_chrome_painter.cpp
        src/map_dock_manager.cpp
        src/map_document_panel.cpp
        src/map_chrome_panel.cpp
        src/map_layer_tree.cpp
        # Q_OBJECT headers listed so AUTOMOC discovers them in this split
        # include/ layout.
        include/pwb/ui_map/map_dock_manager.hpp
        include/pwb/ui_map/map_document_panel.hpp
        include/pwb/ui_map/map_chrome_panel.hpp
        include/pwb/ui_map/map_layer_tree.hpp
    )
    add_library(Pwb::UiMapQt ALIAS pwb_ui_map_qt)
    set_target_properties(pwb_ui_map_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_map_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_map_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_map_qt
        PUBLIC Pwb::UiMap Pwb::UiShellQt Qt6::Widgets
        PRIVATE Qt6::Gui)
endif()

if(TARGET Pwb::Qgis AND TARGET pwb_ui_map_qt)
    add_library(pwb_ui_map_qgis STATIC
        src/display_map_canvas.cpp
        src/map_canvas_panel.cpp
        src/workarea_map_widget.cpp
        src/mapping_page.cpp
        include/pwb/ui_map/display_map_canvas.hpp
        include/pwb/ui_map/map_canvas_panel.hpp
        include/pwb/ui_map/workarea_map_widget.hpp
        include/pwb/ui_map/mapping_page.hpp
    )
    add_library(Pwb::UiMapQgis ALIAS pwb_ui_map_qgis)
    set_target_properties(pwb_ui_map_qgis PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_map_qgis PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_map_qgis PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_map_qgis
        PUBLIC Pwb::UiMapQt Pwb::Qgis Pwb::UiShellQt Qt6::Widgets
        PRIVATE Qt6::Gui)
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_map_tests)
endif()
