# CONV-08 factor_host — interpolation fingerprint / evaluation / plan data
# structures ported from paleo_workbench workflow leaves. Qt-free,
# Python-free, numpy-free; frozen against
# tools/oracle/generate_factor_host_fixtures.py.
add_library(pwb_factor_host STATIC
    src/canonical_json.cpp
    src/fingerprint.cpp
    src/evaluation.cpp
    src/plan.cpp
    src/interop.cpp
    src/semantics.cpp)
add_library(Pwb::FactorHost ALIAS pwb_factor_host)
target_include_directories(pwb_factor_host PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_factor_host PUBLIC cxx_std_20)
if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "pwb_factor_host requires Pwb::Domain "
        "(configure with -DPWB_BUILD_DATA=ON)")
endif()
target_link_libraries(pwb_factor_host PUBLIC Pwb::Domain)

if(BUILD_TESTING)
    add_subdirectory(factor_host_tests)
endif()
