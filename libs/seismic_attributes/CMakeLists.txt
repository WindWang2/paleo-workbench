# pwb::seismic_attributes — ten production seismic attribute kernels (the
# four single-trace E-line kernels plus the S-line volume-structural family:
# sweetness, relative_impedance, dip_il, dip_xl, dip_azimuth, curvature_mean)
# on the frozen pwb::science SDK. Qt-free, Python-free, QGIS-free.
#
# Standalone entry (E-line):
#   cmake -S libs/seismic_attributes -B build/cpp-seismic-attributes -G Ninja
# A-line consumption: add_subdirectory(libs/seismic_attributes) — reuses an
# existing Pwb::Science target when the root build already provides it.
#
# FFT dependency: vendored src/detail/pocketfft_hdronly.h
# (mreineck/pocketfft cpp@c90e55b3, BSD-3, SHA256 recorded in
# docs/development/cpp-seismic-attributes/v3-contracts.md §5). Nothing is
# fetched at configure or build time.
#
# Heavy builds/tests must share the migration resource gate (single heavy
# slot, >= 8 GiB free memory, 2 jobs — scripts/cpp-migration/
# Invoke-ResourceGate.ps1; on this Linux verification host the equivalent
# flock gate over .bare/cpp-migration-heavy.lock is used).

cmake_minimum_required(VERSION 3.24)

project(PaleoSeismicAttributes VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Same-checkout fallback: reuse the host's Pwb::Science when present (root
# build), otherwise bring in libs/algorithms from this checkout. The SDK
# sources are never copied.
if(NOT TARGET Pwb::Science)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../algorithms algorithms)
endif()

add_library(pwb_seismic_attributes STATIC
    src/attributes.cpp
    src/volume_attributes.cpp
)
add_library(Pwb::SeismicAttributes ALIAS pwb_seismic_attributes)
set_target_properties(pwb_seismic_attributes PROPERTIES
    EXPORT_NAME SeismicAttributes
    OUTPUT_NAME pwb-seismic-attributes
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_seismic_attributes PUBLIC cxx_std_20)
target_include_directories(pwb_seismic_attributes
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
target_link_libraries(pwb_seismic_attributes PUBLIC Pwb::Science)
if(MSVC)
    target_compile_options(pwb_seismic_attributes PRIVATE /utf-8 /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_seismic_attributes PRIVATE -Wall -Wextra -Wpedantic)
endif()

option(PWB_SEISMIC_ATTRIBUTES_BUILD_TESTS "Build the seismic attribute test suite" ON)
if(PWB_SEISMIC_ATTRIBUTES_BUILD_TESTS)
    # The runtime test exercises the real TaskRuntime (Pwb::Workflow).
    if(NOT TARGET Pwb::Workflow)
        add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../workflow workflow)
    endif()
    enable_testing()
    add_subdirectory(
        ${CMAKE_CURRENT_SOURCE_DIR}/../../tests/cpp/seismic_attributes
        seismic_attributes_tests)
endif()
