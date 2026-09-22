# VIZ-B — well-tie numeric cores (line B exclusive). Qt-free: wavelet
# (ricker/ormsby), reflectivity/synthetic seismogram, time-depth
# calibration, auto-tie cross-correlation, sonic unit normalization and
# the legacy tie evaluator. The Qt half (tie canvas + report) lives in
# qt/ and only exists where Qt6::Widgets resolved (added by the parent
# cross_well CMakeLists to keep one entry point for the VIZ-B block).

add_library(pwb_visualization_well_tie STATIC
    auto_tie.cpp
    calibration.cpp
    log_tie.cpp
    sonic_units.cpp
    synthetic.cpp
    tie_evaluator.cpp
    wavelet.cpp
)
add_library(Pwb::VisualizationWellTie ALIAS pwb_visualization_well_tie)
set_target_properties(pwb_visualization_well_tie PROPERTIES
    OUTPUT_NAME pwb-visualization-well-tie
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_visualization_well_tie PUBLIC cxx_std_20)
target_include_directories(pwb_visualization_well_tie PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>)
if(MSVC)
    target_compile_options(pwb_visualization_well_tie PRIVATE
        /utf-8 /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_visualization_well_tie PRIVATE
        -Wall -Wextra -Wpedantic)
endif()

# Qt Widgets half: tie canvas (7-track layout) + report export. The
# cross_well CMakeLists adds this directory first (root VIZ-B block
# order), so the TARGET check below sees whether the platform block
# already resolved Qt6::Widgets.
if(TARGET Qt6::Widgets)
    # REQUIRED: the Qt half unconditionally includes
    # QSvgGenerator/QPrinter (compile-time deps, not
    # runtime-optional).
    find_package(Qt6 6.8 REQUIRED COMPONENTS Svg PrintSupport)
    add_library(pwb_visualization_well_tie_qt STATIC
        qt/report_export.cpp
        qt/tie_canvas.cpp
        ${CMAKE_CURRENT_SOURCE_DIR}/../../include/pwb/viz/well_tie/qt/report_export.hpp
        ${CMAKE_CURRENT_SOURCE_DIR}/../../include/pwb/viz/well_tie/qt/tie_canvas.hpp
    )
    add_library(Pwb::VisualizationWellTieQt ALIAS pwb_visualization_well_tie_qt)
    set_target_properties(pwb_visualization_well_tie_qt PROPERTIES
        AUTOMOC ON
        OUTPUT_NAME pwb-visualization-well-tie-qt
        POSITION_INDEPENDENT_CODE ON
    )
    target_compile_features(pwb_visualization_well_tie_qt PUBLIC cxx_std_20)
    target_include_directories(pwb_visualization_well_tie_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../../include>)
    target_link_libraries(pwb_visualization_well_tie_qt
        PUBLIC Pwb::VisualizationWellTie Qt6::Widgets
        PRIVATE Qt6::Gui)
    if(TARGET Qt6::Svg)
        target_link_libraries(pwb_visualization_well_tie_qt PRIVATE Qt6::Svg)
    endif()
    if(TARGET Qt6::PrintSupport)
        target_link_libraries(pwb_visualization_well_tie_qt
            PRIVATE Qt6::PrintSupport)
    endif()
    if(MSVC)
        target_compile_options(pwb_visualization_well_tie_qt PRIVATE
            /utf-8 /W4 /permissive- /wd4251 /wd4275)
    else()
        target_compile_options(pwb_visualization_well_tie_qt PRIVATE
            -Wall -Wextra -Wpedantic)
    endif()
endif()

if(BUILD_TESTING)
    add_subdirectory(well_tie_tests)
endif()
