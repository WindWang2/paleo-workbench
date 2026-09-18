add_executable(mapping_kernel.contouring contouring_test.cpp)
target_compile_features(mapping_kernel.contouring PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.contouring PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.contouring PRIVATE
    PWB_MAPPING_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/contouring_oracle.json")
add_test(NAME mapping_kernel.contouring COMMAND mapping_kernel.contouring)
set_tests_properties(mapping_kernel.contouring PROPERTIES TIMEOUT 120)

add_executable(mapping_kernel.interpolator interpolator_test.cpp)
target_compile_features(mapping_kernel.interpolator PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.interpolator PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.interpolator PRIVATE
    PWB_INTERP_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/interpolator_oracle.json")
add_test(NAME mapping_kernel.interpolator COMMAND mapping_kernel.interpolator)
set_tests_properties(mapping_kernel.interpolator PROPERTIES TIMEOUT 120)

add_executable(mapping_kernel.polygonization polygonization_test.cpp)
target_compile_features(mapping_kernel.polygonization PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.polygonization PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.polygonization PRIVATE
    PWB_POLY_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/polygonization_oracle.json")
add_test(NAME mapping_kernel.polygonization COMMAND mapping_kernel.polygonization)
set_tests_properties(mapping_kernel.polygonization PROPERTIES TIMEOUT 120)

add_executable(mapping_kernel.extract extract_test.cpp)
target_compile_features(mapping_kernel.extract PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.extract PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.extract PRIVATE
    PWB_EXTRACT_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/extract_oracle.json")
add_test(NAME mapping_kernel.extract COMMAND mapping_kernel.extract)
set_tests_properties(mapping_kernel.extract PROPERTIES TIMEOUT 120)

add_executable(mapping_kernel.crs_policy crs_policy_test.cpp)
target_compile_features(mapping_kernel.crs_policy PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.crs_policy PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.crs_policy PRIVATE
    PWB_CRS_POLICY_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/crs_policy_oracle.json")
add_test(NAME mapping_kernel.crs_policy COMMAND mapping_kernel.crs_policy)
set_tests_properties(mapping_kernel.crs_policy PROPERTIES TIMEOUT 30)

add_executable(mapping_kernel.class_grid class_grid_test.cpp)
target_compile_features(mapping_kernel.class_grid PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.class_grid PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.class_grid PRIVATE
    PWB_CLASS_GRID_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/class_grid_oracle.json")
add_test(NAME mapping_kernel.class_grid COMMAND mapping_kernel.class_grid)
set_tests_properties(mapping_kernel.class_grid PROPERTIES TIMEOUT 120)

add_executable(mapping_kernel.grid_stats grid_stats_test.cpp)
target_compile_features(mapping_kernel.grid_stats PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.grid_stats PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.grid_stats PRIVATE
    PWB_GRID_STATS_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/grid_stats_oracle.json")
add_test(NAME mapping_kernel.grid_stats COMMAND mapping_kernel.grid_stats)
set_tests_properties(mapping_kernel.grid_stats PROPERTIES TIMEOUT 30)

add_executable(mapping_kernel.sample_norm sample_norm_test.cpp)
target_compile_features(mapping_kernel.sample_norm PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.sample_norm PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.sample_norm PRIVATE
    PWB_SAMPLE_NORM_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/sample_norm_oracle.json")
add_test(NAME mapping_kernel.sample_norm COMMAND mapping_kernel.sample_norm)
set_tests_properties(mapping_kernel.sample_norm PROPERTIES TIMEOUT 30)

# BEGIN CONV-03
add_executable(mapping_kernel.layer_products layer_products_test.cpp)
target_compile_features(mapping_kernel.layer_products PRIVATE cxx_std_20)
target_link_libraries(mapping_kernel.layer_products PRIVATE
    Pwb::MappingKernel Pwb::Domain)
target_compile_definitions(mapping_kernel.layer_products PRIVATE
    PWB_LAYER_PRODUCTS_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/layer_products_oracle.json")
add_test(NAME mapping_kernel.layer_products
         COMMAND mapping_kernel.layer_products)
set_tests_properties(mapping_kernel.layer_products PROPERTIES TIMEOUT 120)
# END CONV-03
