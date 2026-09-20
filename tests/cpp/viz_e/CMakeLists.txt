# VIZ-E — P-A flow tests: the data-page assembly loop (asset selection →
# capability identify → load → real preview/chart → export) against the
# real VizEDataPage + JobCenter, plus the dat-parsing oracle replay frozen
# from geoviz previews/dat.py.
#
# CLOSURE-PREVIEW (task 04): the same harness now also drives the unified
# data page state machine — single asset-selection bus, parser-registry
# base preview (REAL ingest::build_preview through the closure adapter),
# cancellation, deletion/project-switch clears, presenter dispatch and
# export content validation.
#
# The test compiles the app-side viz_e + closure adapter sources directly
# (pwb-platform is an executable target and cannot be linked), mirroring
# how the platform harness builds main_window.cpp into its tests.

add_executable(viz_e.pa_flow pa_flow_test.cpp)
target_compile_features(viz_e.pa_flow PRIVATE cxx_std_20)
target_include_directories(viz_e.pa_flow PRIVATE
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform)
target_sources(viz_e.pa_flow PRIVATE
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/job_center.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_dat_preview.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_factor_preview.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_hosts.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_install.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/closure_preview_adapters.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_dat_preview.hpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_factor_preview.hpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_hosts.hpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_install.hpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/closure_preview_adapters.hpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/job_center.hpp)
target_link_libraries(viz_e.pa_flow PRIVATE
    Pwb::VizChartsQt Pwb::UiPagesDataQt Pwb::MappingKernel Pwb::UiWorkers
    Pwb::JobQt Pwb::Domain
    Pwb::UiDataCore Pwb::Ingest Pwb::Catalog Pwb::Data Pwb::Application
    Pwb::UiPagesPreview Pwb::UiPagesPreviewQt
    Qt6::Widgets)
set_target_properties(viz_e.pa_flow PROPERTIES AUTOMOC ON)
target_compile_definitions(viz_e.pa_flow PRIVATE
    PWB_WITH_CONV_30=1
    PWB_VIZ_E_TEST_FIXTURES="${CMAKE_CURRENT_SOURCE_DIR}/fixtures")
add_test(NAME viz_e.pa_flow COMMAND viz_e.pa_flow)
set_tests_properties(viz_e.pa_flow PROPERTIES
    ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${PALEO_QGIS_RUNTIME};PATH=path_list_prepend:${PWB_QT_RUNTIME};LD_LIBRARY_PATH=path_list_prepend:${PALEO_QGIS_RUNTIME}"
    ENVIRONMENT "QT_QPA_PLATFORM=offscreen;PROJ_LIB=${PWB_PROJ_DATA};PROJ_DATA=${PWB_PROJ_DATA}${PWB_GDAL_DATA_ENV}"
    TIMEOUT 300)
