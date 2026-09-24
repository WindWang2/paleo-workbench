# QGIS-PLOT — offscreen smoke + interaction tests for the QgsPlotCanvas
# infrastructure (construction, series binding, coordinate mapping, pan/zoom
# via real QGIS plot tools, hover/identify, multi-track linking, export,
# lifecycle).

add_executable(qgis_plot.smoke qgis_plot_smoke_test.cpp)
target_compile_features(qgis_plot.smoke PRIVATE cxx_std_20)
set_target_properties(qgis_plot.smoke PROPERTIES AUTOMOC ON)
target_link_libraries(qgis_plot.smoke PRIVATE Pwb::QgisPlot)
add_test(NAME qgis_plot.smoke COMMAND qgis_plot.smoke)
set_tests_properties(qgis_plot.smoke PROPERTIES
    TIMEOUT 180
    ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}")
