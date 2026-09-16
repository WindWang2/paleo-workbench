# Opt-in well-log host adapter over the real well-log-engine SDK. Only added
# by libs/science_suite when PWB_SCIENCE_VIEWER_TESTS=ON (which hard-requires
# Qt 6.8+ and the WLE submodule). Produces Pwb::VisualizationWellLog.

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
        "${CMAKE_CURRENT_SOURCE_DIR}/../include"
    PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}"
)
target_link_libraries(pwb_visualization_well_log
    PUBLIC
        Pwb::Visualization
        WellLog::QtWidgets
        Qt6::Widgets
)
if(MSVC)
    target_compile_options(pwb_visualization_well_log PRIVATE /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_visualization_well_log PRIVATE -Wall -Wextra -Wpedantic)
endif()
