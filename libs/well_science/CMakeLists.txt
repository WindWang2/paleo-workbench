# CPP well_science — DTW well-log matcher kernel ported from
# paleo_workbench/viz/dtw_log_matcher.py (full-conversion plan M8, CONV-09).
# Qt-free, Python-free, numpy-free; frozen against the Python oracle.
# CPP well_science — curve interpretation numeric kernels ported from
# paleo_workbench/workflow (curve_operations / well_science / the pure
# curve_interpretation leaves), full-conversion plan CONV-11 (M8 井曲线).
# Qt-free, QGIS-free, Python-free; frozen against the Python oracle
# (tools/oracle/generate_curve_ops_fixtures.py).
add_library(pwb_well_science STATIC
    src/dtw.cpp
    src/curve_ops.cpp
    src/curve_expr.cpp
    src/depth_unit.cpp
    src/null_policy.cpp)
add_library(Pwb::WellScience ALIAS pwb_well_science)
target_include_directories(pwb_well_science PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_well_science PUBLIC cxx_std_20)

if(BUILD_TESTING)
    if(NOT TARGET Pwb::Domain)
        message(FATAL_ERROR
            "well_science tests need Pwb::Domain "
            "(configure with -DPWB_BUILD_DATA=ON)")
    endif()
    add_subdirectory(well_science_tests)
endif()
