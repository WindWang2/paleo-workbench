# CONV-19 oracle reconciliation — one binary covering every frozen case group.
add_executable(ingest.parsers ingest_parsers_test.cpp)
target_compile_features(ingest.parsers PRIVATE cxx_std_20)
target_link_libraries(ingest.parsers PRIVATE Pwb::Ingest Pwb::Domain)
target_compile_definitions(ingest.parsers PRIVATE
    PWB_INGEST_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/../oracle/fixtures/ingest_oracle.json")
add_test(NAME ingest.parsers COMMAND ingest.parsers)
set_tests_properties(ingest.parsers PROPERTIES TIMEOUT 120)
