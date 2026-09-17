add_executable(interchange.preflight preflight_test.cpp)
target_compile_features(interchange.preflight PRIVATE cxx_std_20)
target_link_libraries(interchange.preflight PRIVATE
    Pwb::Interchange Pwb::Domain)
target_compile_definitions(interchange.preflight PRIVATE
    PWB_INTERCHANGE_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/interchange_oracle.json")
add_test(NAME interchange.preflight COMMAND interchange.preflight)
set_tests_properties(interchange.preflight PROPERTIES TIMEOUT 120)
