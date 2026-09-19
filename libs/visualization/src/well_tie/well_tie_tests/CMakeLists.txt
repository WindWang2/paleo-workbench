add_executable(viz_b.well_tie.oracle well_tie_oracle_test.cpp)
target_compile_features(viz_b.well_tie.oracle PRIVATE cxx_std_20)
target_link_libraries(viz_b.well_tie.oracle
    PRIVATE Pwb::VisualizationWellTie Pwb::Domain)
target_compile_definitions(viz_b.well_tie.oracle PRIVATE
    PWB_VIZ_B_WELL_TIE_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/viz_b_well_tie_oracle.json")
add_test(NAME viz_b.well_tie.oracle COMMAND viz_b.well_tie.oracle)
set_tests_properties(viz_b.well_tie.oracle PROPERTIES TIMEOUT 300)
