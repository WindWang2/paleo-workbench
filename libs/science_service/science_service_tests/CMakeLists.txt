# CONV-28 science_service tests: typed services + adapters + E2E loop.
#
# science_service.suite      — typed services (factor/well/fusion/geomodel),
#                              resource guards, cancellation, fingerprint
#                              determinism, publisher directory contract.
# science_service.e2e        — acceptance loop: registry + TaskRuntime +
#                              InMemoryPayloadSource (catalog-like DTO) ->
#                              DirectoryEnvelopePublisher -> envelope files;
#                              failure + cancelled publication paths.
# science_service.oracle     — frozen Python service-oracle replay
#                              (tools/oracle/generate_science_service_fixtures.py)
#                              + comparator negative self-check.

add_executable(science_service_suite_test suite_test.cpp)
target_link_libraries(science_service_suite_test
    PRIVATE Pwb::ScienceService Pwb::Workflow Pwb::Domain)
target_compile_features(science_service_suite_test PRIVATE cxx_std_20)
add_test(NAME science_service.suite COMMAND science_service_suite_test)
set_tests_properties(science_service.suite PROPERTIES TIMEOUT 300)

add_executable(science_service_e2e_test e2e_test.cpp)
target_link_libraries(science_service_e2e_test
    PRIVATE Pwb::ScienceService Pwb::Workflow Pwb::Domain)
target_compile_features(science_service_e2e_test PRIVATE cxx_std_20)
add_test(NAME science_service.e2e COMMAND science_service_e2e_test)
set_tests_properties(science_service.e2e PROPERTIES TIMEOUT 300)

add_executable(science_service_oracle_test oracle_test.cpp)
target_link_libraries(science_service_oracle_test
    PRIVATE Pwb::ScienceService Pwb::Workflow Pwb::Domain)
target_compile_features(science_service_oracle_test PRIVATE cxx_std_20)
target_compile_definitions(science_service_oracle_test PRIVATE
    PWB_SCIENCE_SERVICE_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/science_service_oracle.json")
add_test(NAME science_service.oracle COMMAND science_service_oracle_test)
set_tests_properties(science_service.oracle PROPERTIES TIMEOUT 300)
