add_executable(mapping_document.roundtrip map_document_roundtrip_test.cpp)
target_compile_features(mapping_document.roundtrip PRIVATE cxx_std_20)
target_link_libraries(mapping_document.roundtrip PRIVATE
    Pwb::MappingDocument Pwb::Domain)
target_compile_definitions(mapping_document.roundtrip PRIVATE
    PWB_MAPPING_DOCUMENT_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/map_document_oracle.json")
add_test(NAME mapping_document.roundtrip COMMAND mapping_document.roundtrip)
set_tests_properties(mapping_document.roundtrip PROPERTIES TIMEOUT 60)

# CONV-27 — edit-session / snapshot / document-IO behavior layer.
add_executable(mapping_document.edit_session map_document_edit_session_test.cpp)
target_compile_features(mapping_document.edit_session PRIVATE cxx_std_20)
target_link_libraries(mapping_document.edit_session PRIVATE
    Pwb::MappingDocument Pwb::Domain)
target_compile_definitions(mapping_document.edit_session PRIVATE
    PWB_MAPPING_DOCUMENT_EDIT_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/map_document_edit_oracle.json")
add_test(NAME mapping_document.edit_session COMMAND mapping_document.edit_session)
set_tests_properties(mapping_document.edit_session PROPERTIES TIMEOUT 120)
