# VIZ-E — geoviz_plots 绘制半 C++ 化（计划 V6 / docs/development/cpp-viz-e/）。
#
# Qt-free 核心（pwb_viz_charts）：axes 刻度（Heckbert nice numbers）、
# series/LTTB 降采样、colormaps（viridis/cnpc_strat/cnpc_fluid/thermal）、
# convex hull + point-in-polygon、marching squares 等值线/带填充、
# cross-well fence 网格、well QC 统计 — 全部按
# geo-viz-engine/packages/geoviz_plots（@0885195，行为冻结源）1:1 移植，
# oracle 见 tools/oracle/generate_viz_e_charts_fixtures.py。
#
# Qt 层（pwb_viz_charts_qt）：PlotWidget/CrossPlotWidget/ColorbarWidget/
# SurfaceWidget（QPainter 自绘，V6 选型决策见 scope-ledger）。

add_library(pwb_viz_charts STATIC
    src/axes.cpp
    src/colormaps.cpp
    src/convex_hull.cpp
    src/fence.cpp
    src/marching_squares.cpp
    src/series.cpp
    src/well_qc.cpp
)
add_library(Pwb::VizCharts ALIAS pwb_viz_charts)
target_include_directories(pwb_viz_charts PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_viz_charts PUBLIC cxx_std_20)

# Qt 层：4 个 QPainter widget（PlotWidget/CrossPlotWidget/ColorbarWidget/
# SurfaceWidget），行为冻结源 @0885195。
if(TARGET Qt6::Widgets)
    add_library(pwb_viz_charts_qt STATIC
        qt/src/colorbar_widget.cpp
        qt/src/cross_plot_widget.cpp
        qt/src/plot_widget.cpp
        qt/src/surface_widget.cpp
        qt/include/pwb/viz_charts/qt/colorbar_widget.hpp
        qt/include/pwb/viz_charts/qt/cross_plot_widget.hpp
        qt/include/pwb/viz_charts/qt/plot_widget.hpp
        qt/include/pwb/viz_charts/qt/series.hpp
        qt/include/pwb/viz_charts/qt/surface_widget.hpp
    )
    add_library(Pwb::VizChartsQt ALIAS pwb_viz_charts_qt)
    target_include_directories(pwb_viz_charts_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/qt/include>)
    target_compile_features(pwb_viz_charts_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_viz_charts_qt PUBLIC
        Pwb::VizCharts Qt6::Widgets Qt6::Svg Qt6::PrintSupport)
    set_target_properties(pwb_viz_charts_qt PROPERTIES AUTOMOC ON)
endif()

if(BUILD_TESTING)
    add_subdirectory(viz_charts_tests)
endif()
