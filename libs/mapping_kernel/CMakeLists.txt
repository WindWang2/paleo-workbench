# CPP mapping_kernel — contouring + interpolator + polygonization + extract
# + crs_policy cores ported from paleo_workbench mapping/workflow leaves
# (full-conversion plan M6/M7). Qt-free, Python-free, numpy-free; frozen
# against the Python oracle. extract.hpp uses pwb::domain::Json.
add_library(pwb_mapping_kernel STATIC
    src/contouring.cpp
    src/interpolator.cpp
    src/polygonization.cpp
    src/extract.cpp
    src/crs_policy.cpp
    src/class_grid.cpp
    src/sample_normalization.cpp)
add_library(Pwb::MappingKernel ALIAS pwb_mapping_kernel)
target_include_directories(pwb_mapping_kernel PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_mapping_kernel PUBLIC cxx_std_20)
if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "pwb_mapping_kernel extract requires Pwb::Domain "
        "(configure with -DPWB_BUILD_DATA=ON)")
endif()
target_link_libraries(pwb_mapping_kernel PUBLIC Pwb::Domain)

if(BUILD_TESTING)
    add_subdirectory(mapping_kernel_tests)
endif()

# BEGIN CONV-17 — task 17: geometry_units + crs_contract leaves (beside
# crs_policy; oracle mapping_kernel.crs_units). Appended only; the target
# above is untouched when PWB_BUILD_CONV_17 is OFF.
if(PWB_BUILD_CONV_17)
    target_sources(pwb_mapping_kernel PRIVATE
        src/geometry_units.cpp
        src/crs_contract.cpp)
endif()
# END CONV-17
