# UI-18 — Ribbon 五工作区 chrome (libs/ui_ribbon), M1 of
# docs/development/ribbon-five-workspaces/00-plan.md (D3): a Qt-free core
# (five-workspace registry, data-driven command group table, three-mode
# state machine, host-injected disabled-reason channel) plus the
# RibbonBar Qt Widgets shell. Not wired into the app shell yet — the
# integration lands in the later milestones (ribbon_install.cpp).
#
# Gating mirrors UI-14: no per-slice option. The core target joins every
# configuration that resolved the stage vocabulary it maps onto
# (Pwb::ToolPolicy); the _qt target additionally needs Qt6::Widgets plus
# the shell slices it binds (shortcut registry from ui_shell_qt, icon
# factory from ui_widgets, theme tokens from platform_services).

foreach(_required Pwb::ToolPolicy)
    if(NOT TARGET ${_required})
        message(FATAL_ERROR
            "libs/ui_ribbon requires ${_required} — it is only added to "
            "configurations that already resolved it")
    endif()
endforeach()

add_library(pwb_ui_ribbon STATIC
    src/ribbon_spec.cpp
    src/ribbon_state.cpp
)
add_library(Pwb::UiRibbon ALIAS pwb_ui_ribbon)
target_include_directories(pwb_ui_ribbon PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_ribbon PUBLIC cxx_std_20)
# PUBLIC: the workspace registry maps the middle three workspaces onto the
# tool_policy stage vocabulary (MappingStage + stage_label).
target_link_libraries(pwb_ui_ribbon PUBLIC Pwb::ToolPolicy)

# Qt Widgets shell (UI-18): RibbonBar over QTabBar + QStackedWidget +
# QToolButton groups + in-group overflow menus, QAT bound to host-injected
# QActions, Ctrl+F1 through the host ShortcutRegistry, icons through the
# ui_widgets icon factory, light tokens from platform_services.
if(TARGET Qt6::Widgets AND TARGET Pwb::UiShellQt AND TARGET Pwb::UiWidgets
   AND TARGET Pwb::PlatformServices)
    add_library(pwb_ui_ribbon_qt STATIC
        src/qt/ribbon_bar.cpp
        # Q_OBJECT header listed as a source so AUTOMOC discovers the
        # class in this split include/ layout (repo hard convention).
        include/pwb/ui_ribbon/qt/ribbon_bar.hpp
    )
    add_library(Pwb::UiRibbonQt ALIAS pwb_ui_ribbon_qt)
    set_target_properties(pwb_ui_ribbon_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_ribbon_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_ribbon_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_ribbon_qt
        PUBLIC Pwb::UiRibbon Qt6::Widgets
        PRIVATE Pwb::UiShellQt Pwb::UiWidgets Pwb::PlatformServices)
else()
    message(STATUS
        "UI-18: pwb_ui_ribbon_qt skipped — needs Qt6::Widgets + "
        "Pwb::UiShellQt + Pwb::UiWidgets + Pwb::PlatformServices")
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_ribbon_tests)
endif()
