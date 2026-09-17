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

# BEGIN CONV-10
# representative_facies + point-to-surface descriptors (conv swarm #10):
# the M6 leaf over the existing class-grid/polygonize kernels. Appended as
# an opt-in source so the pre-CONV-10 kernel source list is unchanged when
# the option is OFF.
option(PWB_BUILD_CONV_10
    "Build the CONV-10 representative_facies leaf into mapping_kernel" OFF)
if(PWB_BUILD_CONV_10)
    target_sources(pwb_mapping_kernel PRIVATE src/representative_facies.cpp)
endif()
# END CONV-10
