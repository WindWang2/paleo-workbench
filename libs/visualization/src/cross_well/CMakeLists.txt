# VIZ-B — cross-well correlation cores (line B exclusive).
#
# Layering (repo convention — ui_wellseis split):
#   pwb_visualization_cross_well       Qt-free: tops/picks models,
#                                      auto-section planner, seismic tie
#                                      tables, section geometry, formation
#                                      preview geometry
#   pwb_visualization_cross_well_qt    Qt Widgets half: section canvas,
#                                      formation tops preview widget,
#                                      publication report export
#                                      (only where Qt6::Widgets resolved)
#
# Requires Pwb::Domain (ordered JSON for the picks codec).

if(NOT TARGET Pwb::Domain)
    message(FATAL_ERROR
        "libs/visualization/src/cross_well requires Pwb::Domain — the root "
        "VIZ-B block pulls it in; standalone configures must add "
        "libs/domain first")
endif()

set(VIZ_B_CROSS_WELL_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

add_library(pwb_visualization_cross_well STATIC
    auto_section_planner.cpp
    formation_preview.cpp
    picks_model.cpp
    section_geometry.cpp
    seismic_tie.cpp
    tops_model.cpp
)
add_library(Pwb::VisualizationCrossWell ALIAS pwb_visualization_cross_well)
set_target_properties(pwb_visualization_cross_well PROPERTIES
    OUTPUT_NAME pwb-visualization-cross-well
    POSITION_INDEPENDENT_CODE ON
)
target_compile_features(pwb_visualization_cross_well PUBLIC cxx_std_20)
target_include_directories(pwb_visualization_cross_well PUBLIC
    $<BUILD_INTERFACE:${VIZ_B_CROSS_WELL_SOURCE_DIR}/../../include>)
target_link_libraries(pwb_visualization_cross_well PUBLIC
    Pwb::Domain
    # The well-tie numeric kernels (WellTieCalibration) back the seismic
    # tie tables; the Qt-free cross-well core links the sibling Qt-free
    # well-tie target rather than reimplementing np.interp semantics.
    # The root VIZ-B block adds libs/visualization/src/well_tie first.
    Pwb::VisualizationWellTie)
if(MSVC)
    target_compile_options(pwb_visualization_cross_well PRIVATE
        /utf-8 /W4 /permissive- /wd4251 /wd4275)
else()
    target_compile_options(pwb_visualization_cross_well PRIVATE
        -Wall -Wextra -Wpedantic)
endif()

if(TARGET Qt6::Widgets)
    # REQUIRED: the Qt half unconditionally includes
    # QSvgGenerator/QPrinter (compile-time deps, not
    # runtime-optional).
    find_package(Qt6 6.8 REQUIRED COMPONENTS Svg PrintSupport)
    add_library(pwb_visualization_cross_well_qt STATIC
        qt/formation_tops_preview.cpp
        qt/report_export.cpp
        qt/section_canvas.cpp
        # Q_OBJECT headers listed so AUTOMOC discovers them.
        ${VIZ_B_CROSS_WELL_SOURCE_DIR}/../../include/pwb/viz/cross_well/qt/formation_tops_preview.hpp
        ${VIZ_B_CROSS_WELL_SOURCE_DIR}/../../include/pwb/viz/cross_well/qt/report_export.hpp
        ${VIZ_B_CROSS_WELL_SOURCE_DIR}/../../include/pwb/viz/cross_well/qt/section_canvas.hpp
    )
    add_library(Pwb::VisualizationCrossWellQt ALIAS
        pwb_visualization_cross_well_qt)
    set_target_properties(pwb_visualization_cross_well_qt PROPERTIES
        AUTOMOC ON
        OUTPUT_NAME pwb-visualization-cross-well-qt
        POSITION_INDEPENDENT_CODE ON
    )
    target_compile_features(pwb_visualization_cross_well_qt PUBLIC cxx_std_20)
    target_include_directories(pwb_visualization_cross_well_qt PUBLIC
        $<BUILD_INTERFACE:${VIZ_B_CROSS_WELL_SOURCE_DIR}/../../include>)
    target_link_libraries(pwb_visualization_cross_well_qt
        PUBLIC Pwb::VisualizationCrossWell Qt6::Widgets
        PRIVATE Qt6::Gui)
    if(TARGET Qt6::Svg)
        target_link_libraries(pwb_visualization_cross_well_qt PRIVATE Qt6::Svg)
    endif()
    if(TARGET Qt6::PrintSupport)
        target_link_libraries(pwb_visualization_cross_well_qt
            PRIVATE Qt6::PrintSupport)
    endif()
    if(MSVC)
        target_compile_options(pwb_visualization_cross_well_qt PRIVATE
            /utf-8 /W4 /permissive- /wd4251 /wd4275)
    else()
        target_compile_options(pwb_visualization_cross_well_qt PRIVATE
            -Wall -Wextra -Wpedantic)
    endif()
endif()

if(BUILD_TESTING)
    add_subdirectory(cross_well_tests)
    # Line-B integration suite + standalone real-engine example: needs
    # the UI-04 worker closure (the real DTW kernel — never a double).
    if(TARGET Pwb::VisualizationCrossWellQt AND TARGET Pwb::UiWorkers)
        add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../../../tests/cpp/viz_b
                        ${CMAKE_CURRENT_BINARY_DIR}/viz_b_tests)
    endif()
endif()
