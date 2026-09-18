add_executable(layout_export.spec_builder layout_export_oracle_test.cpp)
target_compile_features(layout_export.spec_builder PRIVATE cxx_std_20)
target_link_libraries(layout_export.spec_builder PRIVATE
    Pwb::LayoutExport Pwb::MappingDocument Pwb::Domain)
target_compile_definitions(layout_export.spec_builder PRIVATE
    PWB_LAYOUT_EXPORT_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/layout_export_oracle.json")
add_test(NAME layout_export.spec_builder COMMAND layout_export.spec_builder)
set_tests_properties(layout_export.spec_builder PROPERTIES TIMEOUT 60)
