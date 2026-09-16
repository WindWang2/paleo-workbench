# pwb::visualization core: seismic data-source contract, in-memory reference
# backend, slice color mapping, SelectionEventV1. Qt-free.
#
# The well-log host adapter (Pwb::VisualizationWellLog) is opt-in and lives in
# src/well_log; it is only added when PWB_SCIENCE_VIEWER_TESTS=ON pulls in the
# well-log-engine SDK (see libs/science_suite/CMakeLists.txt).

add_library(pwb_visualization STATIC
    src/seismic_volume.cpp
)
add_library(Pwb::Visualization ALIAS pwb_visualization)
set_target_properties(pwb_visualization PROPERTIES
    EXPORT_NAME Visualization
    OUTPUT_NAME pwb-visualization
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_visualization PUBLIC cxx_std_20)
target_include_directories(pwb_visualization
    PUBLIC
        "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
        "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>"
)
if(MSVC)
    target_compile_options(pwb_visualization PRIVATE /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_visualization PRIVATE -Wall -Wextra -Wpedantic)
endif()
