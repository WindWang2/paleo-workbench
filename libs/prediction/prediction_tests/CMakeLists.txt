add_executable(prediction.tiled_stub tiled_stub_test.cpp)
target_compile_features(prediction.tiled_stub PRIVATE cxx_std_20)
target_link_libraries(prediction.tiled_stub PRIVATE
    Pwb::Prediction Pwb::Domain)
target_compile_options(prediction.tiled_stub PRIVATE -ffp-contract=off)
target_compile_definitions(prediction.tiled_stub PRIVATE
    PWB_TILED_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/tiled_stub_oracle.json")
add_test(NAME prediction.tiled_stub COMMAND prediction.tiled_stub)
set_tests_properties(prediction.tiled_stub PROPERTIES TIMEOUT 300)
