# UI-01 — UI shell substrate: Qt-free data cores (dock registry, navigation,
# command registry, dock manager, layout presets, operation registry,
# deferred page bindings). The Qt Widgets shells live in pwb_ui_shell_qt
# (built only when Qt6::Widgets is available).

add_library(pwb_ui_shell STATIC
    src/dock_registry.cpp
    src/navigation.cpp
    src/command_registry.cpp
    src/dock_manager.cpp
    src/layout_presets.cpp
    src/operation_registry.cpp
    src/deferred_page_bindings.cpp
)
add_library(Pwb::UiShell ALIAS pwb_ui_shell)
target_include_directories(pwb_ui_shell PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_shell PUBLIC cxx_std_20)
# Qt-free cores; tool_policy supplies the stage/gate reason vocabulary that
# command evaluation and status chips consume.
target_link_libraries(pwb_ui_shell PUBLIC Pwb::ToolPolicy)

# Qt Widgets shells (UI-01): style registry, shortcut registry, dock resize
# helpers, floating panels + float controller, layout persistence, status
# bars, command palette, adaptive stack, page placeholder, CRS guidance,
# operation-registry Qt bridge. Qt-free cores stay in pwb_ui_shell.
if(TARGET Qt6::Widgets)
    add_library(pwb_ui_shell_qt STATIC
        src/style_registry.cpp
        src/shortcut_registry.cpp
        src/dock_resize.cpp
        src/floating_panel.cpp
        src/float_controller.cpp
        src/layout_persistence.cpp
        src/page_placeholder.cpp
        src/status_bar.cpp
        src/map_status_bar.cpp
        src/crs_guidance.cpp
        src/screen_inventory.cpp
        src/adaptive_page_stack.cpp
        src/command_palette.cpp
        src/operation_registry_qt.cpp
        # Q_OBJECT headers must be listed as sources — AUTOMOC does not
        # scan the separate include/ tree on its own.
        include/pwb/ui_shell/style_registry.hpp
        include/pwb/ui_shell/floating_panel.hpp
        include/pwb/ui_shell/float_controller.hpp
        include/pwb/ui_shell/page_placeholder.hpp
        include/pwb/ui_shell/status_bar.hpp
        include/pwb/ui_shell/map_status_bar.hpp
        include/pwb/ui_shell/crs_guidance.hpp
        include/pwb/ui_shell/adaptive_page_stack.hpp
        include/pwb/ui_shell/command_palette.hpp
        include/pwb/ui_shell/operation_registry_qt.hpp
    )
    add_library(Pwb::UiShellQt ALIAS pwb_ui_shell_qt)
    set_target_properties(pwb_ui_shell_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_shell_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_shell_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_shell_qt
        PUBLIC Pwb::UiShell Pwb::PlatformServices Qt6::Widgets
        PRIVATE Qt6::Gui)
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_shell_tests)
endif()
