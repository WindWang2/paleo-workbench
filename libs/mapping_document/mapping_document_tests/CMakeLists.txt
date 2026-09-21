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

# CONV-27d — bridge edit domain: native edit session controller, session
# set, gesture manager, legacy-document render snapshot adapter.
add_executable(mapping_document.bridge_session map_document_bridge_session_test.cpp)
target_compile_features(mapping_document.bridge_session PRIVATE cxx_std_20)
target_link_libraries(mapping_document.bridge_session PRIVATE
    Pwb::MappingDocument Pwb::Domain)
target_compile_definitions(mapping_document.bridge_session PRIVATE
    PWB_MAPPING_DOCUMENT_BRIDGE_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/map_document_bridge_oracle.json")
add_test(NAME mapping_document.bridge_session COMMAND mapping_document.bridge_session)
set_tests_properties(mapping_document.bridge_session PROPERTIES TIMEOUT 120)

# V14-COMPILATION-PUBLISH — composer template library / SVG renderer /
# physical-size export, frozen against the Python composer oracle.
add_executable(mapping_document.composer_oracle composer_oracle_test.cpp)
target_compile_features(mapping_document.composer_oracle PRIVATE cxx_std_20)
target_link_libraries(mapping_document.composer_oracle PRIVATE
    Pwb::MappingDocument Pwb::Domain)
target_compile_definitions(mapping_document.composer_oracle PRIVATE
    PWB_COMPOSER_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/composer_oracle.json")
add_test(NAME mapping_document.composer_oracle COMMAND mapping_document.composer_oracle)
set_tests_properties(mapping_document.composer_oracle PROPERTIES TIMEOUT 120)

# V14-COMPILATION-PUBLISH — composer scale/performance structural
# assertions (linear element/legend scaling, deterministic ids, pixel
# budget, unsupported-format refusal).
add_executable(mapping_document.composer_scale composer_scale_test.cpp)
target_compile_features(mapping_document.composer_scale PRIVATE cxx_std_20)
target_link_libraries(mapping_document.composer_scale PRIVATE
    Pwb::MappingDocument Pwb::Domain Pwb::LayoutExport)
add_test(NAME mapping_document.composer_scale COMMAND mapping_document.composer_scale)
set_tests_properties(mapping_document.composer_scale PROPERTIES TIMEOUT 120)
