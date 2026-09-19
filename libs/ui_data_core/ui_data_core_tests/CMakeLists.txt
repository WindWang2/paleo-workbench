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
