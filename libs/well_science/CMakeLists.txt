# CPP well_science — curve interpretation numeric kernels ported from
# paleo_workbench/workflow (curve_operations / well_science / the pure
# curve_interpretation leaves), full-conversion plan CONV-11 (M8 井曲线).
# Qt-free, QGIS-free, Python-free; frozen against the Python oracle
# (tools/oracle/generate_curve_ops_fixtures.py).
add_library(pwb_well_science STATIC
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
        message(STATUS
            "well_science tests need Pwb::Domain (JSON fixtures); "
            "configure with -DPWB_BUILD_DATA=ON to enable them")
    else()
        add_subdirectory(well_science_tests)
    endif()
endif()
