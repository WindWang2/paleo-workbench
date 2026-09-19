# UI-01 — ui_shell tests. ctest names: ui_shell.* (Qt-free, headless).

add_executable(ui_shell.oracle_replay oracle_replay_test.cpp)
target_compile_features(ui_shell.oracle_replay PRIVATE cxx_std_20)
target_link_libraries(ui_shell.oracle_replay PRIVATE
    Pwb::UiShell Pwb::ToolPolicy Pwb::Domain)
target_include_directories(ui_shell.oracle_replay PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(ui_shell.oracle_replay PRIVATE
    PWB_UI_SHELL_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/ui_shell_oracle.json")
add_test(NAME ui_shell.oracle_replay COMMAND ui_shell.oracle_replay)
set_tests_properties(ui_shell.oracle_replay PROPERTIES TIMEOUT 120)

# Qt widget smoke (offscreen): every ported widget constructs + responds.
if(TARGET pwb_ui_shell_qt)
    add_executable(ui_shell.qt_widgets_smoke qt_widgets_smoke_test.cpp)
    target_compile_features(ui_shell.qt_widgets_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_shell.qt_widgets_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_shell.qt_widgets_smoke PRIVATE
        Pwb::UiShellQt Qt6::Widgets)
    add_test(NAME ui_shell.qt_widgets_smoke
             COMMAND ui_shell.qt_widgets_smoke)
    set_tests_properties(ui_shell.qt_widgets_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()
