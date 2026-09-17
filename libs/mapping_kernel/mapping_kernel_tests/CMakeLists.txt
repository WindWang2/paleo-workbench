add_executable(mapping_kernel.contouring contouring_test.cpp)
target_compile_features(mapping_kernel.contouring PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.contouring PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.contouring PRIVATE
    PWB_MAPPING_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/contouring_oracle.json")
add_test(NAME mapping_kernel.contouring COMMAND mapping_kernel.contouring)
set_tests_properties(mapping_kernel.contouring PROPERTIES TIMEOUT 120)
