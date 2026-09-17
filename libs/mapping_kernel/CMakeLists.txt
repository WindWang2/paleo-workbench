# CPP mapping_kernel — the contouring core ported from
# paleo_workbench/mapping/geological_pipeline (full-conversion plan M6).
# Qt-free, Python-free, numpy-free; frozen against the Python oracle.
add_library(pwb_mapping_kernel STATIC
    src/contouring.cpp)
add_library(Pwb::MappingKernel ALIAS pwb_mapping_kernel)
target_include_directories(pwb_mapping_kernel PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_mapping_kernel PUBLIC cxx_std_20)

if(BUILD_TESTING)
    add_subdirectory(mapping_kernel_tests)
endif()
