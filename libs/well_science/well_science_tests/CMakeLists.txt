add_executable(well_science.dtw dtw_test.cpp)
target_compile_features(well_science.dtw PRIVATE cxx_std_20)
target_link_libraries(well_science.dtw PRIVATE
    Pwb::WellScience Pwb::Domain)
target_compile_definitions(well_science.dtw PRIVATE
    PWB_DTW_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/dtw_oracle.json")
add_test(NAME well_science.dtw COMMAND well_science.dtw)
set_tests_properties(well_science.dtw PROPERTIES TIMEOUT 300)
