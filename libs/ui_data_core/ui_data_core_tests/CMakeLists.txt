add_executable(ui_data_core.smoke smoke_test.cpp)
target_compile_features(ui_data_core.smoke PRIVATE cxx_std_20)
target_link_libraries(ui_data_core.smoke PRIVATE Pwb::UiDataCore)
add_test(NAME ui_data_core.smoke COMMAND ui_data_core.smoke)
set_tests_properties(ui_data_core.smoke PROPERTIES TIMEOUT 120)

# BEGIN VIZ-E (#1382/#1383): catalog overview ownership + variant guards.
add_executable(ui_data_core.asset_view_guard asset_view_guard_test.cpp)
target_compile_features(ui_data_core.asset_view_guard PRIVATE cxx_std_20)
target_link_libraries(ui_data_core.asset_view_guard PRIVATE Pwb::UiDataCore)
add_test(NAME ui_data_core.asset_view_guard COMMAND ui_data_core.asset_view_guard)
set_tests_properties(ui_data_core.asset_view_guard PROPERTIES TIMEOUT 120)
# END VIZ-E

# CONV-35 — geojson_layers parity (frozen oracle replay).
add_executable(ui_data_core.facies_groups facies_groups_test.cpp)
target_compile_features(ui_data_core.facies_groups PRIVATE cxx_std_20)
target_link_libraries(ui_data_core.facies_groups PRIVATE Pwb::UiDataCore)
target_compile_definitions(ui_data_core.facies_groups PRIVATE
    PWB_FACIES_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/facies_groups_oracle.json")
add_test(NAME ui_data_core.facies_groups COMMAND ui_data_core.facies_groups)
set_tests_properties(ui_data_core.facies_groups PROPERTIES TIMEOUT 120)

# CONV-36 — scanner + import_service parity (frozen oracle replay).
add_executable(ui_data_core.import_oracle import_oracle_test.cpp)
target_compile_features(ui_data_core.import_oracle PRIVATE cxx_std_20)
target_link_libraries(ui_data_core.import_oracle PRIVATE Pwb::UiDataCore)
target_compile_definitions(ui_data_core.import_oracle PRIVATE
    PWB_IMPORT_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/import_oracle.json")
add_test(NAME ui_data_core.import_oracle COMMAND ui_data_core.import_oracle)
set_tests_properties(ui_data_core.import_oracle PROPERTIES TIMEOUT 120)

# CONV-36 — export_service + data_asset_registry parity (frozen oracle).
add_executable(ui_data_core.export_oracle export_oracle_test.cpp)
target_compile_features(ui_data_core.export_oracle PRIVATE cxx_std_20)
target_link_libraries(ui_data_core.export_oracle PRIVATE Pwb::UiDataCore)
target_compile_definitions(ui_data_core.export_oracle PRIVATE
    PWB_EXPORT_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/export_oracle.json")
# The test reads produced workbooks through the in-module OOXML reader.
target_include_directories(ui_data_core.export_oracle PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../../interchange/src)
add_test(NAME ui_data_core.export_oracle COMMAND ui_data_core.export_oracle)
set_tests_properties(ui_data_core.export_oracle PROPERTIES TIMEOUT 120)
