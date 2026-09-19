# UI-13 — workstation-composite: Qt-free semantic cores for the composite
# editor (vector layers + edit sessions, topology service/checker, merge
# plans, CRS gate, snapping service/spatial index, map-tool state
# machines, stage vocabulary/profiles, attribute schema, layer
# decorations, capture/geological specs, QGIS layer schema helpers,
# templates, map snapshots/overlays, CompositeEditController).
# Qt-free cores stay in pwb_ui_composite; widget shells land in
# pwb_ui_composite_qt (Qt6::Widgets-gated) and QGIS adapters in
# pwb_ui_composite_qgis as their sources arrive.

add_library(pwb_ui_composite STATIC
    src/attribute_schema.cpp
    src/capture_spec.cpp
    src/composite_controller.cpp
    src/crs_gate.cpp
    src/geological_layer_spec.cpp
    src/geometry.cpp
    src/layer_decorations.cpp
    src/layer_groups.cpp
    src/map_interaction.cpp
    src/map_snapshot.cpp
    src/map_styles.cpp
    src/map_tools.cpp
    src/merge_plan.cpp
    src/qgis_layer_schema.cpp
    src/roles.cpp
    src/snapping_profiles.cpp
    src/stage_profiles.cpp
    src/stage_vocabulary.cpp
    src/templates.cpp
    src/topology_checker.cpp
    src/topology_service.cpp
    src/vector_layer.cpp
)
add_library(Pwb::UiComposite ALIAS pwb_ui_composite)
target_include_directories(pwb_ui_composite PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_composite PUBLIC cxx_std_20)
# Qt-free cores. Domain supplies Json/sha256; ToolPolicy is the canonical
# tool-availability/stage authority; UiDataCore supplies map-edit
# geometry/command vocabulary; UiWorkstation supplies state-language
# projections the stage panels reuse.
target_link_libraries(pwb_ui_composite PUBLIC
    Pwb::Domain Pwb::ToolPolicy Pwb::UiDataCore Pwb::UiWorkstation)

# Qt Widgets shells (UI-13). Every Q_OBJECT header is listed as a source
# so AUTOMOC discovers the classes in this split include/ layout. The
# shells adapt the Qt-free core + existing widget libraries — they grow
# no second gate/decoration/taxonomy authority.
if(TARGET Qt6::Widgets)
    add_library(pwb_ui_composite_qt STATIC
        src/composite_attribute_table.cpp
        src/composite_controller_qt.cpp
        src/composite_document.cpp
        src/composite_panels.cpp
        src/facies_selector.cpp
        src/layer_manager_panel.cpp
        src/mapping_stage_bar.cpp
        src/mapping_stage_panel.cpp
        src/merge_features_dialog.cpp
        src/tool_page_dialog.cpp
        src/topology_checker_panel.cpp
        include/pwb/ui_composite/composite_attribute_table.hpp
        include/pwb/ui_composite/composite_controller_qt.hpp
        include/pwb/ui_composite/composite_document.hpp
        include/pwb/ui_composite/composite_panels.hpp
        include/pwb/ui_composite/facies_selector.hpp
        include/pwb/ui_composite/layer_manager_panel.hpp
        include/pwb/ui_composite/mapping_stage_bar.hpp
        include/pwb/ui_composite/mapping_stage_panel.hpp
        include/pwb/ui_composite/merge_features_dialog.hpp
        include/pwb/ui_composite/tool_page_dialog.hpp
        include/pwb/ui_composite/topology_checker_panel.hpp
    )
    add_library(Pwb::UiCompositeQt ALIAS pwb_ui_composite_qt)
    set_target_properties(pwb_ui_composite_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_composite_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_composite_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_composite_qt PUBLIC
        Pwb::UiComposite Pwb::Ui Pwb::UiShellQt Pwb::UiWidgets
        Qt6::Widgets
        PRIVATE Qt6::Gui)
    # linked_workspace binds the view-coordination controller (UI-14 Qt
    # shell; CONV_30-gated). Without it the panel drops out honestly —
    # the rest of the composite shells have no such dependency.
    if(TARGET Pwb::UiControllersQt)
        target_sources(pwb_ui_composite_qt PRIVATE
            src/linked_workspace.cpp
            include/pwb/ui_composite/linked_workspace.hpp)
        target_link_libraries(pwb_ui_composite_qt PUBLIC
            Pwb::UiControllersQt)
    else()
        message(STATUS
            "UI-13: linked_workspace panel skipped — needs "
            "Pwb::UiControllersQt (PWB_BUILD_CONV_30)")
    endif()
endif()

# QGIS adapters (UI-13): QgsGeometry-backed ICompositeGeometryOps +
# topology validator seams + the QgisCanvasShim↔controller canvas
# binding. The bridge geometry_service TU is compiled into this target
# (same reuse idiom as CONV-29 layout_spec_exec in pwb_qgis) — it is the
# vendored QgsGeometry kernel the Python geometry_service facade calls.
if(TARGET Pwb::Qgis AND TARGET Pwb::UiWidgetsQgis AND
   TARGET pwb_ui_composite_qt)
    add_library(pwb_ui_composite_qgis STATIC
        src/qgis/qgis_geometry.cpp
        src/qgis/composite_qgis_canvas.cpp
        ${CMAKE_SOURCE_DIR}/native/qgis_render_bridge/src/geometry_service.cpp
        include/pwb/ui_composite/qgis/qgis_geometry.hpp
        include/pwb/ui_composite/qgis/composite_qgis_canvas.hpp
    )
    add_library(Pwb::UiCompositeQgis ALIAS pwb_ui_composite_qgis)
    set_target_properties(pwb_ui_composite_qgis PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_composite_qgis PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_include_directories(pwb_ui_composite_qgis SYSTEM PRIVATE
        ${CMAKE_SOURCE_DIR}/native/qgis_render_bridge/src)
    target_compile_features(pwb_ui_composite_qgis PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_composite_qgis PUBLIC
        Pwb::UiCompositeQt Pwb::UiWidgetsQgis Pwb::Qgis Qt6::Widgets)
endif()

if(BUILD_TESTING)
    add_subdirectory(composite_tests)
endif()
