# Opt-in well-log host adapter over the real well-log-engine SDK. Added by
# libs/science_suite when PWB_SCIENCE_BUILD_VIEWER=ON (Qt 6.8+ and WLE from
# the pinned gitlink or a prebuilt install tree). Produces
# Pwb::VisualizationWellLog; consumers use the public header only:
#   #include <pwb/viz/well_log_host_widget.hpp>

add_library(pwb_visualization_well_log STATIC
    well_log_host_widget.cpp
)
add_library(Pwb::VisualizationWellLog ALIAS pwb_visualization_well_log)
set_target_properties(pwb_visualization_well_log PROPERTIES
    EXPORT_NAME VisualizationWellLog
    OUTPUT_NAME pwb-visualization-welllog
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_visualization_well_log PUBLIC cxx_std_20)
target_include_directories(pwb_visualization_well_log
    PUBLIC
        "${CMAKE_CURRENT_SOURCE_DIR}/../../include"
)
target_link_libraries(pwb_visualization_well_log
    PUBLIC
        Pwb::Visualization
        WellLog::QtWidgets
        Qt6::Widgets
    PRIVATE
        WellLog::IO # LasSourceAdapter (parse only; not exposed in headers)
)
if(MSVC)
    target_compile_options(pwb_visualization_well_log PRIVATE /utf-8 /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_visualization_well_log PRIVATE -Wall -Wextra -Wpedantic)
endif()

# Standalone consumption proof (v3-contracts.md §3): a program that links
# only the public header and the real adapter target — no test harness, no
# test-only paths. Built with the viewer, independently of BUILD_TESTING.
option(PWB_SCIENCE_VIEWER_EXAMPLE
    "Build the standalone Pwb::VisualizationWellLog consumer example" ON)
if(PWB_SCIENCE_VIEWER_EXAMPLE)
    add_executable(pwb-well-log-consumer examples/well_log_consume.cpp)
    target_compile_features(pwb-well-log-consumer PRIVATE cxx_std_20)
    target_link_libraries(pwb-well-log-consumer PRIVATE Pwb::VisualizationWellLog)
    if(MSVC)
        target_compile_options(pwb-well-log-consumer PRIVATE /utf-8 /W4 /permissive- /wd4251 /wd4275)
    else()
        target_compile_options(pwb-well-log-consumer PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endif()
