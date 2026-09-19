add_executable(viz_b.cross_well.oracle cross_well_oracle_test.cpp)
target_compile_features(viz_b.cross_well.oracle PRIVATE cxx_std_20)
target_link_libraries(viz_b.cross_well.oracle
    PRIVATE Pwb::VisualizationCrossWell Pwb::VisualizationWellTie Pwb::Domain)
target_compile_definitions(viz_b.cross_well.oracle PRIVATE
    PWB_VIZ_B_CROSS_WELL_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/viz_b_cross_well_oracle.json")
add_test(NAME viz_b.cross_well.oracle COMMAND viz_b.cross_well.oracle)
set_tests_properties(viz_b.cross_well.oracle PROPERTIES TIMEOUT 300)

if(TARGET Pwb::VisualizationCrossWellQt)
    find_package(Qt6 6.8 QUIET COMPONENTS Test)
    if(TARGET Qt6::Test)
        add_executable(viz_b.cross_well.qt_smoke qt_smoke_test.cpp)
        target_compile_features(viz_b.cross_well.qt_smoke PRIVATE cxx_std_20)
        set_target_properties(viz_b.cross_well.qt_smoke PROPERTIES AUTOMOC ON)
        target_link_libraries(viz_b.cross_well.qt_smoke PRIVATE
            Pwb::VisualizationCrossWellQt Qt6::Widgets Qt6::Test)
        target_compile_definitions(viz_b.cross_well.qt_smoke PRIVATE
            PWB_VIZ_B_CROSS_WELL_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/viz_b_cross_well_oracle.json")
        add_test(NAME viz_b.cross_well.qt_smoke COMMAND viz_b.cross_well.qt_smoke)
        set_tests_properties(viz_b.cross_well.qt_smoke PROPERTIES
            ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
            TIMEOUT 300)
    endif()
endif()
