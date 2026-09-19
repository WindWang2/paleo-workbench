# UI-08 — qt-mapedit slice: the map-edit page cluster ported to native
# C++/Qt Widgets. Orchestrates the existing ui_data_core edit stack
# (commands / drafts / snapping / topology) and ui_data_qt graphics items
# instead of duplicating them.
#
# Sources (Python parity surfaces):
#   Qt-free helpers        map_edit_api, feature_query_index,
#                          document_features
#   Scene/view/toolbar     map_edit_scene, map_edit_view, map_edit_toolbar
#   Panels                 map_attribute_table, map_topology_issue_panel,
#                          map_reference_panel, boundary_panel,
#                          map_workbench_bottom
#   Factor/inspector       factor_preview_grid, map_factor_shelf,
#                          inspector_panel (+ tag/table widget seams,
#                          map_icons)

if(TARGET Qt6::Widgets AND TARGET Pwb::UiDataQt)
    add_library(pwb_ui_pages_mapedit STATIC
        src/map_edit_api.cpp
        src/feature_query_index.cpp
        src/document_features.cpp
        src/map_icons.cpp
        src/table_preview_widget.cpp
        src/tag_widgets.cpp
        src/map_edit_scene.cpp
        src/map_edit_view.cpp
        src/map_edit_toolbar.cpp
        src/map_attribute_table.cpp
        src/map_topology_issue_panel.cpp
        src/map_reference_panel.cpp
        src/boundary_panel.cpp
        src/map_workbench_bottom.cpp
        src/factor_preview_grid.cpp
        src/map_factor_shelf.cpp
        src/inspector_panel.cpp
        # Q_OBJECT headers listed so AUTOMOC discovers them in this
        # split include/ layout.
        include/pwb/ui_pages_mapedit/table_preview_widget.hpp
        include/pwb/ui_pages_mapedit/tag_widgets.hpp
        include/pwb/ui_pages_mapedit/map_edit_scene.hpp
        include/pwb/ui_pages_mapedit/map_edit_view.hpp
        include/pwb/ui_pages_mapedit/map_edit_toolbar.hpp
        include/pwb/ui_pages_mapedit/map_attribute_table.hpp
        include/pwb/ui_pages_mapedit/map_topology_issue_panel.hpp
        include/pwb/ui_pages_mapedit/map_reference_panel.hpp
        include/pwb/ui_pages_mapedit/boundary_panel.hpp
        include/pwb/ui_pages_mapedit/map_workbench_bottom.hpp
        include/pwb/ui_pages_mapedit/factor_preview_grid.hpp
        include/pwb/ui_pages_mapedit/map_factor_shelf.hpp
        include/pwb/ui_pages_mapedit/inspector_panel.hpp
    )
    add_library(Pwb::UiPagesMapedit ALIAS pwb_ui_pages_mapedit)
    set_target_properties(pwb_ui_pages_mapedit PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_pages_mapedit PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_pages_mapedit PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_pages_mapedit
        PUBLIC Pwb::UiDataCore Pwb::UiDataQt Pwb::UiWidgets
               Pwb::UiShellQt Pwb::Catalog Qt6::Widgets
        PRIVATE Qt6::Gui)
endif()

if(BUILD_TESTING AND TARGET pwb_ui_pages_mapedit)
    add_subdirectory(ui_pages_mapedit_tests)
endif()
