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

add_executable(providers.service service_test.cpp)
target_compile_features(providers.service PRIVATE cxx_std_20)
target_link_libraries(providers.service PRIVATE Pwb::Providers Pwb::Domain)
add_test(NAME providers.service COMMAND providers.service)
set_tests_properties(providers.service PROPERTIES TIMEOUT 120)

# CPP-CLOSE-10 — dynamic plugin boundary: failure matrix (missing module /
# bad ABI / missing host capability / bad descriptor) plus the refcounted
# unload lifecycle (running task completes, new executions fail fast,
# deferred finalize at last lease release). The four module variants come
# from one source with VARIANT defines; they link only the authoring glue
# (Pwb::PluginGlue + Domain headers) — the ABI they exercise is pure C, and
# the mapping-kernel archives stay out of the .so link (PIC requirements).
set(PWB_PLUGIN_TEST_DIR ${CMAKE_CURRENT_BINARY_DIR})
foreach(variant OK BADABI BADDESC MISSING_CAP)
    add_library(pwb_test_plugin_${variant} MODULE plugins/test_plugin_module.cpp)
    target_compile_features(pwb_test_plugin_${variant} PRIVATE cxx_std_20)
    target_compile_definitions(pwb_test_plugin_${variant} PRIVATE
        PWB_TEST_PLUGIN_${variant})
    target_link_libraries(pwb_test_plugin_${variant} PRIVATE Pwb::PluginGlue)
    set_target_properties(pwb_test_plugin_${variant} PROPERTIES
        PREFIX ""
        OUTPUT_NAME "pwb_test_plugin_${variant}"
        LIBRARY_OUTPUT_DIRECTORY "${PWB_PLUGIN_TEST_DIR}"
        SUFFIX ".so"
    )
endforeach()

add_executable(providers.plugins plugin_test.cpp)
target_compile_features(providers.plugins PRIVATE cxx_std_20)
target_link_libraries(providers.plugins PRIVATE Pwb::Providers Pwb::Domain)
target_compile_definitions(providers.plugins PRIVATE
    PWB_PLUGIN_OK="${PWB_PLUGIN_TEST_DIR}/pwb_test_plugin_OK.so"
    PWB_PLUGIN_BADABI="${PWB_PLUGIN_TEST_DIR}/pwb_test_plugin_BADABI.so"
    PWB_PLUGIN_BADDESC="${PWB_PLUGIN_TEST_DIR}/pwb_test_plugin_BADDESC.so"
    PWB_PLUGIN_MISSING_CAP="${PWB_PLUGIN_TEST_DIR}/pwb_test_plugin_MISSING_CAP.so"
)
add_test(NAME providers.plugins COMMAND providers.plugins)
set_tests_properties(providers.plugins PROPERTIES TIMEOUT 120)
