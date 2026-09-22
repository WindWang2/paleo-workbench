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
    src/sample_normalization.cpp
    # BEGIN CONV-03
    src/layer_products.cpp
    # END CONV-03
    # geoviz_plots.interpolation ports — 样条(Clough-Tocher cubic /
    # linear/nearest/rbf via scipy_grid) + 方向趋势(directional_trend)
    # kernels; Qt-free leaves consumed by the factor-prepare dispatcher.
    src/directional_trend.cpp
    src/scipy_grid.cpp
)
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

# BEGIN CONV-04
# Task 04 (feat/cpp-conv-04-ring-clip-repair): ring_ops — bounded
# clip_polygon_to_ring / clip_polyline_to_ring and the shapely-free subset of
# repair_invalid_geometry (closure, signed-area orient, single-crossing
# bowtie split), frozen against tools/oracle/generate_ring_ops_fixtures.py.
# Appended only: sources and tests above stay untouched.
if(PWB_BUILD_CONV_04)
    target_sources(pwb_mapping_kernel PRIVATE src/ring_ops.cpp)
    if(BUILD_TESTING)
        add_executable(mapping_kernel.ring_ops mapping_kernel_tests/ring_ops_test.cpp)
        target_compile_features(mapping_kernel.ring_ops PRIVATE cxx_std_20)
        target_link_libraries(mapping_kernel.ring_ops PRIVATE
            Pwb::MappingKernel Pwb::Domain)
        target_compile_definitions(mapping_kernel.ring_ops PRIVATE
            PWB_RING_OPS_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/mapping_kernel_tests/fixtures/ring_ops_oracle.json")
        add_test(NAME mapping_kernel.ring_ops COMMAND mapping_kernel.ring_ops)
        set_tests_properties(mapping_kernel.ring_ops PROPERTIES TIMEOUT 120)
    endif()
endif()
# END CONV-04
# BEGIN CONV-05
# constrained-IDW (Haiyou) surface kernel, frozen against the Python oracle
# (tools/oracle/generate_constrained_idw_fixtures.py).
if(PWB_BUILD_CONV_05)
    target_sources(pwb_mapping_kernel PRIVATE src/constrained_idw.cpp)
endif()
# END CONV-05
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
# BEGIN CONV-17 — task 17: geometry_units + crs_contract leaves (beside
# crs_policy; oracle mapping_kernel.crs_units). Appended only; the target
# above is untouched when PWB_BUILD_CONV_17 is OFF.
if(PWB_BUILD_CONV_17)
    target_sources(pwb_mapping_kernel PRIVATE
        src/geometry_units.cpp
        src/crs_contract.cpp)
endif()
# END CONV-17
# BEGIN CONV-18
# Task 18 — FactorGridResult JSON envelope codec (factor_grid_io.hpp/.cpp).
# New sources only; the ported numerical cores above stay untouched.
if(PWB_BUILD_CONV_18)
    target_sources(pwb_mapping_kernel PRIVATE src/factor_grid_io.cpp)
endif()
# END CONV-18
