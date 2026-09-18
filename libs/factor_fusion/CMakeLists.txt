# CONV-24 — factor_fusion + factor_units pure kernel (Qt-free, Python-free).
add_library(pwb_factor_fusion STATIC
    src/factor_units.cpp
    src/fusion.cpp
)
add_library(Pwb::FactorFusion ALIAS pwb_factor_fusion)

target_include_directories(pwb_factor_fusion
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_compile_features(pwb_factor_fusion PUBLIC cxx_std_20)
# Json (ordered) + Sha256 via Pwb::Domain; python_repr_double via
# Pwb::FactorHost — both public because public headers expose them.
target_link_libraries(pwb_factor_fusion PUBLIC Pwb::Domain Pwb::FactorHost)

add_subdirectory(factor_fusion_tests)
