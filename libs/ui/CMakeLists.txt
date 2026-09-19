add_library(pwb_ui STATIC
    src/tool_actions.cpp
)
add_library(Pwb::Ui ALIAS pwb_ui)
target_include_directories(pwb_ui PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui PUBLIC cxx_std_20)
target_link_libraries(pwb_ui PUBLIC Pwb::ToolPolicy Qt6::Widgets)

# BEGIN CONV-27
# Qt-native (QGIS-free) additions: stage readiness kernel + stage dock +
# layout persistence stay pure Qt so non-QGIS hosts can consume them.
# StageDock introduces this library's first Q_OBJECT (moc joins the build).
set_target_properties(pwb_ui PROPERTIES AUTOMOC ON)
# Headers are listed so AUTOMOC discovers the Q_OBJECT classes in this
# split include/ layout (angle includes alone do not associate them).
target_sources(pwb_ui PRIVATE
    src/stage_readiness.cpp
    src/stage_dock.cpp
    src/workbench_layout.cpp
    include/pwb/ui/stage_dock.hpp)

# QGIS-coupled workbench surface: layer tree panel, edit tool lifecycle,
# native layer properties, constraint panel. Only available where the QGIS
# SDK is (PWB_BUILD_PLATFORM); consumes the application session as the
# single edit/map authority.
if(TARGET Pwb::Qgis AND TARGET Pwb::Application)
    add_library(pwb_ui_workbench STATIC
        src/layer_tree_panel.cpp
        src/edit_tool_controller.cpp
        src/layer_properties.cpp
        src/constraint_panel.cpp
        include/pwb/ui/layer_tree_panel.hpp
        include/pwb/ui/edit_tool_controller.hpp
        include/pwb/ui/constraint_panel.hpp)
    add_library(Pwb::UiWorkbench ALIAS pwb_ui_workbench)
    set_target_properties(pwb_ui_workbench PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_workbench PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_workbench PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_workbench PUBLIC
        Pwb::Ui Pwb::Application Qt6::Widgets)
endif()
# END CONV-27
