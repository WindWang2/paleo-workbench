add_executable(prediction.tiled_stub tiled_stub_test.cpp)
target_compile_features(prediction.tiled_stub PRIVATE cxx_std_20)
target_link_libraries(prediction.tiled_stub PRIVATE
    Pwb::Prediction Pwb::Domain)
# Bit-exact FP parity with the Python oracle: never contract a*b+c into FMA.
if(NOT MSVC)
    target_compile_options(prediction.tiled_stub PRIVATE -ffp-contract=off)
endif()
target_compile_definitions(prediction.tiled_stub PRIVATE
    PWB_TILED_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/tiled_stub_oracle.json")
add_test(NAME prediction.tiled_stub COMMAND prediction.tiled_stub)
set_tests_properties(prediction.tiled_stub PROPERTIES TIMEOUT 120)

# BEGIN CONV-21 — contract-core oracle test (same fixture protocol as the
# tiled stub: every frozen case replays through the C++ port).
if(PWB_BUILD_CONV_21)
    add_executable(prediction.contracts contracts_test.cpp)
    target_compile_features(prediction.contracts PRIVATE cxx_std_20)
    target_link_libraries(prediction.contracts PRIVATE
        Pwb::Prediction Pwb::Domain)
    if(NOT MSVC)
        target_compile_options(prediction.contracts PRIVATE -ffp-contract=off)
    endif()
    target_compile_definitions(prediction.contracts PRIVATE
        PWB_CONTRACTS_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/prediction_contract_oracle.json")
    add_test(NAME prediction.contracts COMMAND prediction.contracts)
    set_tests_properties(prediction.contracts PROPERTIES TIMEOUT 120)
endif()
# END CONV-21
