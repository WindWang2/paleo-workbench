add_executable(well_science.curve_ops curve_ops_test.cpp)
target_compile_features(well_science.curve_ops PRIVATE cxx_std_20)
target_link_libraries(well_science.curve_ops PRIVATE
    Pwb::WellScience Pwb::Domain)
target_compile_definitions(well_science.curve_ops PRIVATE
    PWB_CURVE_OPS_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/curve_ops_oracle.json")
add_test(NAME well_science.curve_ops COMMAND well_science.curve_ops)
set_tests_properties(well_science.curve_ops PROPERTIES TIMEOUT 120)
