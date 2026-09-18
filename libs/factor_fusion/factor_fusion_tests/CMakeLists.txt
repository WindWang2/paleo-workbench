add_executable(factor_fusion_contracts_test contracts_test.cpp)
target_link_libraries(factor_fusion_contracts_test PRIVATE Pwb::FactorFusion)
target_compile_features(factor_fusion_contracts_test PRIVATE cxx_std_20)

set(FACTOR_FUSION_FIXTURE
    ${CMAKE_CURRENT_SOURCE_DIR}/fixtures/factor_fusion_oracle.json)

add_test(NAME factor_fusion.contracts
         COMMAND factor_fusion_contracts_test ${FACTOR_FUSION_FIXTURE})
