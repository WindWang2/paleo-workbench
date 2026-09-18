# CONV-PROVIDERS — provider SDK tests: oracle conformance (frozen Python
# verdicts), descriptor/registry/schema/execution unit contracts, and the
# built-in providers (factor stats, map thumbnail) end-to-end.

add_executable(providers.oracle oracle_test.cpp)
target_compile_features(providers.oracle PRIVATE cxx_std_20)
target_link_libraries(providers.oracle PRIVATE Pwb::Providers Pwb::Domain)
target_compile_definitions(providers.oracle PRIVATE
    PWB_PROVIDERS_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/provider_oracle.json")
add_test(NAME providers.oracle COMMAND providers.oracle)
set_tests_properties(providers.oracle PROPERTIES TIMEOUT 120)

add_executable(providers.contracts contracts_test.cpp)
target_compile_features(providers.contracts PRIVATE cxx_std_20)
target_link_libraries(providers.contracts PRIVATE Pwb::Providers Pwb::Domain)
add_test(NAME providers.contracts COMMAND providers.contracts)
set_tests_properties(providers.contracts PROPERTIES TIMEOUT 120)

add_executable(providers.registry registry_test.cpp)
target_compile_features(providers.registry PRIVATE cxx_std_20)
target_link_libraries(providers.registry PRIVATE Pwb::Providers Pwb::Domain)
add_test(NAME providers.registry COMMAND providers.registry)
set_tests_properties(providers.registry PROPERTIES TIMEOUT 120)

add_executable(providers.schema schema_test.cpp)
target_compile_features(providers.schema PRIVATE cxx_std_20)
target_link_libraries(providers.schema PRIVATE Pwb::Providers Pwb::Domain)
add_test(NAME providers.schema COMMAND providers.schema)
set_tests_properties(providers.schema PROPERTIES TIMEOUT 120)

add_executable(providers.execution execution_test.cpp)
target_compile_features(providers.execution PRIVATE cxx_std_20)
target_link_libraries(providers.execution PRIVATE Pwb::Providers Pwb::Domain)
add_test(NAME providers.execution COMMAND providers.execution)
set_tests_properties(providers.execution PROPERTIES TIMEOUT 120)

add_executable(providers.builtins builtins_test.cpp)
target_compile_features(providers.builtins PRIVATE cxx_std_20)
target_link_libraries(providers.builtins PRIVATE Pwb::Providers Pwb::Domain)
add_test(NAME providers.builtins COMMAND providers.builtins)
set_tests_properties(providers.builtins PROPERTIES TIMEOUT 300)
