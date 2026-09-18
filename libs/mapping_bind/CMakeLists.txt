# CONV-20: optional pybind11 facade `pwb_mapping_kernel` over the Qt-free
# mapping_kernel cores (Pwb::MappingKernel). pybind11 v3.1.0 headers (BSD-3)
# are vendored at _vendor/pybind11 — see _vendor/pybind11/README.md. Only
# dicts/lists/scalars cross the bridge (CPP_EXTENSION.md boundary rules); the
# module output lands in the build tree and is consumed via PYTHONPATH — a
# built .so must never be committed into the source tree.
if(NOT TARGET Pwb::MappingKernel)
    message(FATAL_ERROR
        "PWB_BUILD_CONV_20 requires PWB_BUILD_MAPPING_KERNEL=ON "
        "(the pybind facade wraps the mapping_kernel cores)")
endif()

find_package(Python3 REQUIRED COMPONENTS Interpreter Development.Module)

set(PYBIND11_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/_vendor/pybind11/include"
    CACHE PATH "pybind11 headers (vendored for CONV-20)")
if(NOT EXISTS "${PYBIND11_INCLUDE_DIR}/pybind11/pybind11.h")
    message(FATAL_ERROR
        "pybind11 headers not found at ${PYBIND11_INCLUDE_DIR} "
        "(vendored under libs/mapping_bind/_vendor/pybind11/include)")
endif()

# Module __version__ metadata, parsed from the package version (pyproject).
set(_conv20_pyproject "${CMAKE_CURRENT_SOURCE_DIR}/../../pyproject.toml")
set(PWB_MAPPING_BIND_VERSION "0.0.0-dev")
if(EXISTS "${_conv20_pyproject}")
    file(STRINGS "${_conv20_pyproject}" _conv20_ver_line
        REGEX "^version[ ]=" LIMIT_COUNT 1)
    if(_conv20_ver_line MATCHES "version[ ]=[ ]\"([^\"]+)\"")
        set(PWB_MAPPING_BIND_VERSION "${CMAKE_MATCH_1}")
    endif()
endif()

# The static kernel was created without PIC; linking it into a MODULE .so
# requires PIC objects. Build-system-only change: no kernel source is touched
# (decisions D15).
set_property(TARGET pwb_mapping_kernel
    PROPERTY POSITION_INDEPENDENT_CODE ON)

# CMake target `mapping_bind_module`; the Python module name comes from
# PYBIND11_MODULE(pwb_mapping_kernel, ...) via OUTPUT_NAME.
Python3_add_library(mapping_bind_module MODULE WITH_SOABI
    src/mapping_bind.cpp)
set_target_properties(mapping_bind_module PROPERTIES
    OUTPUT_NAME pwb_mapping_kernel)
target_include_directories(mapping_bind_module PRIVATE "${PYBIND11_INCLUDE_DIR}")
target_compile_features(mapping_bind_module PRIVATE cxx_std_20)
target_compile_definitions(mapping_bind_module PRIVATE
    PWB_MAPPING_BIND_VERSION="${PWB_MAPPING_BIND_VERSION}")
target_link_libraries(mapping_bind_module PRIVATE Pwb::MappingKernel)

if(BUILD_TESTING)
    add_subdirectory(mapping_bind_tests)
endif()
