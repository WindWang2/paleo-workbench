# pwb::seismic_service — the native seismic volume service (Qt-free).
#
# Bridges libs/seismic_io (inspect / window reads / tile cache) into the
# frozen pwb::viz::ISeismicVolume contract consumed by libs/seismic_viewer,
# and carries the seismic<->project spatial context seam (BinGridGeometry +
# CRS id, JSON-codec only — no libs/project ABI change).
#
# pwb_visualization is linked PRIVATE on purpose: the service only implements
# the interface declared in its headers and must not drag Qt into the link
# interface of Qt-free consumers. Reuse the target when the consuming
# superproject already provides it.
if(NOT TARGET Pwb::Visualization)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../visualization visualization)
endif()

add_library(pwb_seismic_service STATIC
    src/tiled_volume.cpp
    src/volume_service.cpp)
add_library(Pwb::SeismicService ALIAS pwb_seismic_service)
target_include_directories(pwb_seismic_service PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_seismic_service PUBLIC cxx_std_20)
target_link_libraries(pwb_seismic_service
    PUBLIC Pwb::SeismicIo Pwb::Domain
    PRIVATE pwb_visualization)
if(MSVC)
    target_compile_options(pwb_seismic_service PRIVATE /W4)
else()
    target_compile_options(pwb_seismic_service PRIVATE -Wall -Wextra -Wpedantic)
endif()

option(PWB_SEISMIC_SERVICE_BUILD_TESTS "Build the seismic service tests" ON)
if(PWB_SEISMIC_SERVICE_BUILD_TESTS AND BUILD_TESTING)
    enable_testing()
    add_subdirectory(tests)
endif()
