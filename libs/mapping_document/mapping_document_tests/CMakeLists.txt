add_executable(mapping_document.roundtrip map_document_roundtrip_test.cpp)
target_compile_features(mapping_document.roundtrip PRIVATE cxx_std_20)
target_link_libraries(mapping_document.roundtrip PRIVATE
    Pwb::MappingDocument Pwb::Domain)
target_compile_definitions(mapping_document.roundtrip PRIVATE
    PWB_MAPPING_DOCUMENT_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/map_document_oracle.json")
add_test(NAME mapping_document.roundtrip COMMAND mapping_document.roundtrip)
set_tests_properties(mapping_document.roundtrip PROPERTIES TIMEOUT 60)
