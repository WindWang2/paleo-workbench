# VIZ-E — viz_charts tests.
#   * viz_charts.oracle_replay — replays the frozen Python oracle
#     (tools/oracle/generate_viz_e_charts_fixtures.py) against the ported
#     kernels; the negative self-check case proves the comparator fails on
#     tampered data.

add_executable(viz_charts.oracle_replay oracle_replay_test.cpp)
target_compile_features(viz_charts.oracle_replay PRIVATE cxx_std_20)
target_link_libraries(viz_charts.oracle_replay PRIVATE Pwb::VizCharts Pwb::Domain)
target_compile_definitions(viz_charts.oracle_replay PRIVATE
    PWB_VIZ_E_CHARTS_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/viz_e_charts_oracle.json")
add_test(NAME viz_charts.oracle_replay COMMAND viz_charts.oracle_replay)
set_tests_properties(viz_charts.oracle_replay PROPERTIES TIMEOUT 120)

# Qt widget smoke (offscreen): the four ported QPainter widgets construct,
# render, export and tear down under QT_QPA_PLATFORM=offscreen.
if(TARGET Pwb::VizChartsQt)
    add_executable(viz_charts.qt_widgets_smoke qt_widgets_smoke_test.cpp)
    target_compile_features(viz_charts.qt_widgets_smoke PRIVATE cxx_std_20)
    set_target_properties(viz_charts.qt_widgets_smoke PROPERTIES
        AUTOMOC ON)
    target_link_libraries(viz_charts.qt_widgets_smoke PRIVATE
        Pwb::VizChartsQt Pwb::Domain)
    add_test(NAME viz_charts.qt_widgets_smoke
             COMMAND viz_charts.qt_widgets_smoke)
    set_tests_properties(viz_charts.qt_widgets_smoke PROPERTIES
        TIMEOUT 180
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()
