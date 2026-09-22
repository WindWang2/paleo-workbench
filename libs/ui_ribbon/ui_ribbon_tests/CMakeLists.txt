# UI-18 — ui_ribbon tests. ctest names: ui_ribbon.core_smoke (Qt-free
# registry/table/state-machine semantics, headless) + ui_ribbon.qt_smoke
# (offscreen RibbonBar: tabs, band switching, three-mode heights, the
# three collapse entries, compact overflow, QAT injection, keyboard
# traversal). Manual deterministic harness (same shape as
# libs/ui_stageflow/ui_stageflow_tests/ui_stageflow_test.hpp) — the local
# Qt install may lack the Test module.

add_executable(ui_ribbon_core_smoke core_smoke_test.cpp)
target_compile_features(ui_ribbon_core_smoke PRIVATE cxx_std_20)
target_link_libraries(ui_ribbon_core_smoke PRIVATE Pwb::UiRibbon)
target_include_directories(ui_ribbon_core_smoke PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_ribbon.core_smoke COMMAND ui_ribbon_core_smoke)
set_tests_properties(ui_ribbon.core_smoke PROPERTIES TIMEOUT 120)

# Qt smoke (offscreen): constructs the real RibbonBar over the real core
# table; the QGIS-free closure mirrors ui_widgets.modelview (icon factory
# + theme tokens + shortcut registry, no QGIS session).
if(TARGET pwb_ui_ribbon_qt)
    add_executable(ui_ribbon_qt_smoke qt_smoke_test.cpp)
    target_compile_features(ui_ribbon_qt_smoke PRIVATE cxx_std_20)
    # Pwb::UiShellQt carries the ShortcutRegistry header the test drives
    # directly (the library consumes it PRIVATE); the icon-factory /
    # theme-token includes arrive through Pwb::UiRibbonQt's own interface.
    target_link_libraries(ui_ribbon_qt_smoke PRIVATE
        Pwb::UiRibbonQt Pwb::UiShellQt Qt6::Widgets)
    target_include_directories(ui_ribbon_qt_smoke PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ui_ribbon.qt_smoke COMMAND ui_ribbon_qt_smoke)
    # The icon factory / theme tokens pull the QGIS vendor closure in
    # (Pwb::UiWidgets -> Pwb::PlatformServices -> Pwb::Qgis), and its
    # transitive dependencies (libodbc, ...) are not RPATH-reachable —
    # same runtime closure the platform/ui_widgets.qgis tests use.
    set_tests_properties(ui_ribbon.qt_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}")
endif()
