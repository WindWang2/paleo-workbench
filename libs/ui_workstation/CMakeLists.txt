# UI-12 — workstation shell: Qt-free semantic cores (ui context, mode
# state, state language, tool surface, action help, explorer/inspector
# specs, task/agent projections, stage-action vocabulary) + Qt Widgets
# shells (app bar, activity rail, explorer, inspector, task center,
# process hub, agent panel, keybindings, workstation dock frame).
# Qt-free cores stay in pwb_ui_workstation; pwb_ui_workstation_qt is built
# only when Qt6::Widgets is available.

add_library(pwb_ui_workstation STATIC
    src/ui_context.cpp
    src/mode_state.cpp
    src/state_language.cpp
    src/tool_surface.cpp
    src/tool_help.cpp
    src/action_help.cpp
    src/explorer_spec.cpp
    src/inspector_spec.cpp
    src/task_projection.cpp
    src/agent_plan.cpp
    src/stage_actions.cpp
    src/keybinding_intent.cpp
    src/log_buffer.cpp
)
add_library(Pwb::UiWorkstation ALIAS pwb_ui_workstation)
target_include_directories(pwb_ui_workstation PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_workstation PUBLIC cxx_std_20)
# Qt-free cores. ToolPolicy is the canonical tool-availability authority;
# Domain supplies Json for style dicts; UiShell supplies the preset/dock
# vocabulary the core projection helpers consume.
target_link_libraries(pwb_ui_workstation PUBLIC
    Pwb::ToolPolicy Pwb::UiShell)
if(TARGET Pwb::Domain)
    target_link_libraries(pwb_ui_workstation PUBLIC Pwb::Domain)
endif()
if(TARGET Pwb::UiWidgetsCore)
    target_link_libraries(pwb_ui_workstation PUBLIC Pwb::UiWidgetsCore)
endif()
if(TARGET Pwb::Cartography)
    target_link_libraries(pwb_ui_workstation PUBLIC Pwb::Cartography)
endif()
if(TARGET Pwb::JobRuntime)
    target_link_libraries(pwb_ui_workstation PUBLIC Pwb::JobRuntime)
endif()

# Qt Widgets shells (UI-12). Every Q_OBJECT header is listed as a source
# so AUTOMOC discovers the classes in this split include/ layout.
if(TARGET Qt6::Widgets)
    add_library(pwb_ui_workstation_qt STATIC
        src/ui_context_qt.cpp
        src/mode_state_qt.cpp
        src/app_bar.cpp
        src/activity_rail.cpp
        src/explorer_panel.cpp
        src/inspector_panel.cpp
        src/task_center.cpp
        src/process_hub.cpp
        src/agent_panel.cpp
        src/keybinding_manager.cpp
        src/workflow_panel.cpp
        src/workstation_frame.cpp
        include/pwb/ui_workstation/ui_context_qt.hpp
        include/pwb/ui_workstation/mode_state_qt.hpp
        include/pwb/ui_workstation/app_bar.hpp
        include/pwb/ui_workstation/activity_rail.hpp
        include/pwb/ui_workstation/explorer_panel.hpp
        include/pwb/ui_workstation/inspector_panel.hpp
        include/pwb/ui_workstation/task_center.hpp
        include/pwb/ui_workstation/process_hub.hpp
        include/pwb/ui_workstation/agent_panel.hpp
        include/pwb/ui_workstation/keybinding_manager.hpp
        include/pwb/ui_workstation/workflow_panel.hpp
        include/pwb/ui_workstation/workstation_frame.hpp
    )
    add_library(Pwb::UiWorkstationQt ALIAS pwb_ui_workstation_qt)
    set_target_properties(pwb_ui_workstation_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_workstation_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_workstation_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_workstation_qt
        PUBLIC Pwb::UiWorkstation Pwb::UiShellQt Pwb::UiWidgets
               Qt6::Widgets
        PRIVATE Qt6::Gui)
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_workstation_tests)
endif()
