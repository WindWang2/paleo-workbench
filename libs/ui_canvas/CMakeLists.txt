# UI-15 — root-canvas slice: Qt-free cores + Qt Widgets surfaces + the
# QGIS-backed snapshot render backend / symbology bridge
# (paleo_workbench/ui/{unified_map_canvas,map_layer_properties,
# map_symbology_bridge,map_export_worker,preview_settings_dialog}).
#
# Three targets, same split as ui_widgets/ui_map:
#   pwb_ui_canvas_core — Qt-free semantic cores (backend contract/helpers,
#       layer scene, layer tree, properties payload, symbology request/
#       result, export spec, snapshot encoder) plus the authoritative
#       LayerRegistry TU vendored from native/layer_model_core (single
#       authority, no pybind).
#   pwb_ui_canvas      — Qt Widgets shells (UnifiedMapCanvas,
#       NativeMapCanvas + raster controller, NativeLayerTree, properties
#       dialog, export worker, preview dialog).
#   pwb_ui_canvas_qgis — the QGIS-coupled surfaces (snapshot codec,
#       QgisSnapshotRenderBackend, symbology bridge), built only where the
#       vendored QGIS SDK was admitted (Pwb::Qgis exists); the bridge TUs
#       are vendored in like CONV-29's layout_spec_exec.cpp — the same
#       single-authority sources the pybind module compiles.

add_library(pwb_ui_canvas_core STATIC
    src/map_render_backend.cpp
    src/vector_lod.cpp
    src/layer_scene.cpp
    src/layer_tree_core.cpp
    src/layer_properties_core.cpp
    src/symbology_core.cpp
    src/export_core.cpp
    src/snapshot_encoder.cpp
    # The LayerRegistry/MapLayer authority — the same TU the pybind
    # extension compiles (no pybind in this TU; STL only).
    ${CMAKE_SOURCE_DIR}/native/layer_model_core/src/layer_model.cpp
)
add_library(Pwb::UiCanvasCore ALIAS pwb_ui_canvas_core)
target_include_directories(pwb_ui_canvas_core PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
# layer_scene.hpp / layer_tree_core.hpp include "layer_model.hpp" — the
# registry header lives with its source under native/.
target_include_directories(pwb_ui_canvas_core SYSTEM PUBLIC
    $<BUILD_INTERFACE:${CMAKE_SOURCE_DIR}/native/layer_model_core/src>)
target_compile_features(pwb_ui_canvas_core PUBLIC cxx_std_20)
target_link_libraries(pwb_ui_canvas_core
    PUBLIC Pwb::Domain Pwb::UiMap Pwb::Cartography)

# Qt Widgets shells: every Q_OBJECT header is listed as a source so
# AUTOMOC discovers the classes in this split include/ layout.
if(TARGET Qt6::Widgets AND TARGET Pwb::UiWidgets
   AND TARGET Pwb::UiPagesPreviewQt AND TARGET Pwb::JobQt)
    add_library(pwb_ui_canvas STATIC
        src/qt/fallback_map_backend.cpp
        src/qt/unified_map_canvas.cpp
        src/qt/map_layer_properties.cpp
        src/qt/map_export_worker.cpp
        src/qt/preview_settings_dialog.cpp
        include/pwb/ui_canvas/qt/fallback_map_backend.hpp
        include/pwb/ui_canvas/qt/unified_map_canvas.hpp
        include/pwb/ui_canvas/qt/map_layer_properties.hpp
        include/pwb/ui_canvas/qt/map_export_worker.hpp
        include/pwb/ui_canvas/qt/preview_settings_dialog.hpp
        include/pwb/ui_canvas/qt/qt_meta.hpp
    )
    add_library(Pwb::UiCanvas ALIAS pwb_ui_canvas)
    set_target_properties(pwb_ui_canvas PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_canvas PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_canvas PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_canvas
        PUBLIC Pwb::UiCanvasCore Pwb::UiWidgets Pwb::UiPagesPreviewQt
               Pwb::JobQt Qt6::Widgets Qt6::Svg Qt6::PrintSupport)

    # QGIS-coupled surfaces: snapshot codec + snapshot render backend +
    # symbology bridge. Only where the vendored SDK was admitted; the
    # bridge implementation TUs are vendored in (single-authority reuse —
    # the same sources the pybind module compiles).
    if(TARGET Pwb::Qgis)
        add_library(pwb_ui_canvas_qgis STATIC
            src/qgis/snapshot_codec.cpp
            src/qgis/qgis_snapshot_backend.cpp
            src/qgis/qgis_symbology_bridge.cpp
            ${CMAKE_SOURCE_DIR}/native/qgis_render_bridge/src/qgis_render_bridge.cpp
            ${CMAKE_SOURCE_DIR}/native/qgis_render_bridge/src/style_codec.cpp
            ${CMAKE_SOURCE_DIR}/native/qgis_render_bridge/src/gui_service.cpp
            include/pwb/ui_canvas/qgis/snapshot_codec.hpp
            include/pwb/ui_canvas/qgis/qgis_snapshot_backend.hpp
            include/pwb/ui_canvas/qgis/qgis_symbology_bridge.hpp
        )
        add_library(Pwb::UiCanvasQgis ALIAS pwb_ui_canvas_qgis)
        set_target_properties(pwb_ui_canvas_qgis PROPERTIES AUTOMOC ON)
        target_include_directories(pwb_ui_canvas_qgis PUBLIC
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
        # The bridge TUs include "qgis_render_bridge.hpp" /
        # "style_codec.hpp" / "gui_service.hpp" unqualified and my qgis
        # sources include them too — expose the bridge src dir.
        target_include_directories(pwb_ui_canvas_qgis SYSTEM PUBLIC
            $<BUILD_INTERFACE:${CMAKE_SOURCE_DIR}/native/qgis_render_bridge/src>)
        target_compile_features(pwb_ui_canvas_qgis PUBLIC cxx_std_20)
        target_link_libraries(pwb_ui_canvas_qgis
            PUBLIC Pwb::UiCanvasCore Pwb::Qgis Qt6::Widgets Qt6::Xml
                   Qt6::Svg Qt6::PrintSupport)
        # Vendored prefix path baked at build time (same contract as
        # pwb_qgis — the backend initializes QGIS off the SDK prefix).
        target_compile_definitions(pwb_ui_canvas_qgis PRIVATE
            PALEO_QGIS_PREFIX_PATH="${PALEO_QGIS_SDK_DIR}")
    endif()
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_canvas_tests)
endif()
