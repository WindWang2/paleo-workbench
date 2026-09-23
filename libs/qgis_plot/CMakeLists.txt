# QGIS-PLOT — scientific 2D visualization convergence (docs/development/
# qgis-native-plot-convergence/). Single QgsPlotCanvas-based infrastructure:
# PwbPlotCanvas (navigation/coord-mapping/hover/export), PwbPlotItem (scene
# host for any Qgs2DPlot), QGIS-native tool adapters (x-axis zoom, identify,
# lasso), domain content plots (z-ramp scatter, column bands), and the
# PwbPlotPanel stock chrome. Replaces the generic pwb_viz_charts_qt widgets.

add_library(pwb_qgis_plot STATIC
    src/plot_item.cpp
    src/plot_canvas.cpp
    src/plot_tools.cpp
    src/plot_panel.cpp
    src/domain_plots.cpp
    src/numeric_formats.cpp
    include/pwb/qgis_plot/series_binding.hpp
    include/pwb/qgis_plot/plot_item.hpp
    include/pwb/qgis_plot/plot_canvas.hpp
    include/pwb/qgis_plot/plot_tools.hpp
    include/pwb/qgis_plot/plot_panel.hpp
    include/pwb/qgis_plot/domain_plots.hpp
    include/pwb/qgis_plot/numeric_formats.hpp
)
add_library(Pwb::QgisPlot ALIAS pwb_qgis_plot)
target_include_directories(pwb_qgis_plot PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_qgis_plot PUBLIC cxx_std_20)
target_link_libraries(pwb_qgis_plot PUBLIC
    PwbQgis::Sdk Qt6::Widgets Qt6::Svg Qt6::PrintSupport)
set_target_properties(pwb_qgis_plot PROPERTIES AUTOMOC ON)

if(BUILD_TESTING)
    add_subdirectory(qgis_plot_tests)
endif()
