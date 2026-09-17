add_executable(factor_host.fingerprint fingerprint_test.cpp)
target_compile_features(factor_host.fingerprint PRIVATE cxx_std_20)
target_link_libraries(factor_host.fingerprint PRIVATE
    Pwb::FactorHost Pwb::Domain)
target_compile_definitions(factor_host.fingerprint PRIVATE
    PWB_FACTOR_HOST_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/factor_host_oracle.json")
add_test(NAME factor_host.fingerprint COMMAND factor_host.fingerprint)
set_tests_properties(factor_host.fingerprint PROPERTIES TIMEOUT 120)
