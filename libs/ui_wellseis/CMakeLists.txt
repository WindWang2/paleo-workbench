# UI-09 — qt-well-seismic slice: Qt-free semantic cores, thin Qt Widgets
# shells, and the QGIS well-map surface for the well/seismic page cluster
# (well detail/table/map, well-log canvas + track settings, seismic
# attribute/context/control/view/task panels, prediction pages,
# correlation link editor, cross-well export, joint page, 3D geomodel).
#
# Layering (repo convention — ui_map/ui_shell split):
#   pwb_ui_wellseis       Qt-free cores (cursor gates, task/resource state,
#                         output labels, correlation rows, diagnostics,
#                         well-map/table/detail models, joint state,
#                         export options, host-collected slices)
#   pwb_ui_wellseis_qt    Qt Widgets shells + injected engine seams
#                         (well-log / seismic / 3D engines stay behind
#                         QWidget* factories — never reimplemented here)
#   pwb_ui_wellseis_qgis  QGIS-backed IWellMapSurface (MapSession +
#                         QgsMapCanvas); only where the SDK is admitted.
#
# Hard requirements (fail-closed at configure, like libs/ui_workers):
#   Pwb::Domain     ordered JSON conventions (slices/payloads)
#   Pwb::UiWorkers  ResourceSlice + worker input contracts reused by the
#                   page shells (no parallel implementations)
#   Pwb::WellScience  depth-unit vocabulary used by cursor_gates

foreach(_required Pwb::Domain Pwb::UiWorkers Pwb::WellScience)
    if(NOT TARGET ${_required})
        message(FATAL_ERROR
            "libs/ui_wellseis requires ${_required} — the root UI-09 "
            "block pulls it in under PWB_BUILD_PLATFORM; standalone "
            "configures must enable it explicitly")
    endif()
endforeach()

add_library(pwb_ui_wellseis STATIC
    src/correlation.cpp
    src/cursor_gates.cpp
    src/export_options.cpp
    src/joint_state.cpp
    src/output_labels.cpp
    src/page_state.cpp
    src/redact.cpp
    src/resource_sources.cpp
    src/run_diagnostic.cpp
    src/seismic_attributes.cpp
    src/task_state.cpp
    src/well_detail.cpp
    src/well_map.cpp
    src/well_table_format.cpp
)
add_library(Pwb::UiWellseis ALIAS pwb_ui_wellseis)
target_include_directories(pwb_ui_wellseis PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_wellseis PUBLIC cxx_std_20)
# PUBLIC: headers expose pwb::domain::Json (slices), ResourceSlice
# (resource_sources) and DepthUnitInfo (cursor_gates).
target_link_libraries(pwb_ui_wellseis PUBLIC
    Pwb::Domain Pwb::UiWorkers Pwb::WellScience)

if(TARGET Qt6::Widgets)
    add_library(pwb_ui_wellseis_qt STATIC
        src/qt/correlation_link_editor.cpp
        src/qt/cross_well_export_dialog.cpp
        src/qt/geological_modeling_3d_page.cpp
        src/qt/object_table_model.cpp
        src/qt/prediction_evidence_panel.cpp
        src/qt/project_well_map_page.cpp
        src/qt/seismic_attribute_panel.cpp
        src/qt/seismic_context_toolbar.cpp
        src/qt/seismic_control_panel.cpp
        src/qt/seismic_prediction_page.cpp
        src/qt/seismic_view_panel.cpp
        src/qt/task_panel_base.cpp
        src/qt/well_detail_panel.cpp
        src/qt/well_log_canvas_panel.cpp
        src/qt/well_log_prediction_page.cpp
        src/qt/well_log_track_settings.cpp
        src/qt/well_map_canvas.cpp
        src/qt/well_map_panel.cpp
        src/qt/well_seismic_joint_page.cpp
        src/qt/well_table_panel.cpp
        # Q_OBJECT headers listed so AUTOMOC discovers them in this split
        # include/ layout.
        include/pwb/ui_wellseis/qt/correlation_link_editor.hpp
        include/pwb/ui_wellseis/qt/cross_well_export_dialog.hpp
        include/pwb/ui_wellseis/qt/engine_seams.hpp
        include/pwb/ui_wellseis/qt/geological_modeling_3d_page.hpp
        include/pwb/ui_wellseis/qt/object_table_model.hpp
        include/pwb/ui_wellseis/qt/prediction_evidence_panel.hpp
        include/pwb/ui_wellseis/qt/project_well_map_page.hpp
        include/pwb/ui_wellseis/qt/seismic_attribute_panel.hpp
        include/pwb/ui_wellseis/qt/seismic_context_toolbar.hpp
        include/pwb/ui_wellseis/qt/seismic_control_panel.hpp
        include/pwb/ui_wellseis/qt/seismic_prediction_page.hpp
        include/pwb/ui_wellseis/qt/seismic_view_panel.hpp
        include/pwb/ui_wellseis/qt/task_panel_base.hpp
        include/pwb/ui_wellseis/qt/well_detail_panel.hpp
        include/pwb/ui_wellseis/qt/well_log_canvas_panel.hpp
        include/pwb/ui_wellseis/qt/well_log_prediction_page.hpp
        include/pwb/ui_wellseis/qt/well_log_track_settings.hpp
        include/pwb/ui_wellseis/qt/well_map_canvas.hpp
        include/pwb/ui_wellseis/qt/well_map_panel.hpp
        include/pwb/ui_wellseis/qt/well_seismic_joint_page.hpp
        include/pwb/ui_wellseis/qt/well_table_panel.hpp
    )
    add_library(Pwb::UiWellseisQt ALIAS pwb_ui_wellseis_qt)
    set_target_properties(pwb_ui_wellseis_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_wellseis_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_wellseis_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_wellseis_qt
        PUBLIC Pwb::UiWellseis Qt6::Widgets
        PRIVATE Qt6::Gui)

    # The track-settings dialog binds the Qt-free WellLogTrackLayout model.
    # The TU normally ships inside Pwb::VisualizationWellLog (the opt-in
    # WLE adapter, PWB_SCIENCE_BUILD_VIEWER=ON). When the viewer track is
    # off, compile the same TU here — the CONV-29 single-authority
    # pattern (layout_spec_exec is compiled into two targets the same
    # way). Never both: two copies in one link would duplicate symbols.
    if(TARGET Pwb::VisualizationWellLog)
        target_link_libraries(pwb_ui_wellseis_qt
            PUBLIC Pwb::VisualizationWellLog)
    else()
        target_sources(pwb_ui_wellseis_qt PRIVATE
            ${CMAKE_SOURCE_DIR}/libs/visualization/src/well_log/well_log_track_layout.cpp)
        # PUBLIC: well_log_track_settings.hpp exposes
        # <pwb/viz/well_log_track_layout.hpp> to consumers.
        target_include_directories(pwb_ui_wellseis_qt PUBLIC
            $<BUILD_INTERFACE:${CMAKE_SOURCE_DIR}/libs/visualization/include>)
    endif()
endif()

if(TARGET Pwb::Qgis AND TARGET pwb_ui_wellseis_qt)
    add_library(pwb_ui_wellseis_qgis STATIC
        src/qgis/well_map_qgis_surface.cpp
        include/pwb/ui_wellseis/qgis/well_map_qgis_surface.hpp
    )
    add_library(Pwb::UiWellseisQgis ALIAS pwb_ui_wellseis_qgis)
    set_target_properties(pwb_ui_wellseis_qgis PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_wellseis_qgis PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_wellseis_qgis PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_wellseis_qgis
        PUBLIC Pwb::UiWellseisQt Pwb::Qgis Qt6::Widgets
        PRIVATE Qt6::Gui)
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_wellseis_tests)
endif()
