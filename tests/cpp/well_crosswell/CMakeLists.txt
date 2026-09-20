# 05 — well/crosswell closure tests: production load seam (LAS + XML),
# viz_b real LAS path, real-dock lifecycle, and the 05→04 presenter
# consumption flow. Mounted from the root 05 block when the WLE bridge,
# the viz-B cores and the viz-e data-page closure all resolved.

if(NOT TARGET Pwb::UiWorkersWleLoad)
    message(FATAL_ERROR "tests/cpp/well_crosswell needs Pwb::UiWorkersWleLoad")
endif()
if(NOT TARGET Pwb::VisualizationCrossWell)
    message(FATAL_ERROR "tests/cpp/well_crosswell needs Pwb::VisualizationCrossWell")
endif()

set(PWB_WELL_FIXTURE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/fixtures")

# 1) Production load seam over real LAS/XML files (units, reverse depth,
#    missing curves, cancellation, honest nullopt).
add_executable(well.load_path well_load_path_test.cpp)
target_compile_features(well.load_path PRIVATE cxx_std_20)
target_link_libraries(well.load_path PRIVATE
    Pwb::UiWorkersWleLoad Pwb::Domain
    # WLE 头（welllog/core/document.hpp）不经 UiWorkersWleLoad 透传
    #（PRIVATE 链接）——直链（viz_a.wle_load 同款修法）。
    WellLog::IO)
target_compile_definitions(well.load_path PRIVATE
    PWB_WELL_FIXTURE_DIR="${PWB_WELL_FIXTURE_DIR}")
add_test(NAME well.load_path COMMAND well.load_path)
set_tests_properties(well.load_path PROPERTIES TIMEOUT 300)

# 2) viz_b real LAS path (converter: null-pair dropping, error
#    aggregation, honest empty coords).
add_executable(well.vizb_las_path well_vizb_las_path_test.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_b_well_source.cpp
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_b_well_source.hpp)
target_compile_features(well.vizb_las_path PRIVATE cxx_std_20)
set_target_properties(well.vizb_las_path PROPERTIES AUTOMOC ON)
target_include_directories(well.vizb_las_path PRIVATE
    ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform)
target_link_libraries(well.vizb_las_path PRIVATE
    Pwb::UiWorkersWleLoad Pwb::VisualizationCrossWell Pwb::Domain
    WellLog::IO  # WLE 头直链（不经 UiWorkersWleLoad 透传）
    Qt6::Core)
target_compile_definitions(well.vizb_las_path PRIVATE
    PWB_WELL_FIXTURE_DIR="${PWB_WELL_FIXTURE_DIR}")
add_test(NAME well.vizb_las_path COMMAND well.vizb_las_path)
set_tests_properties(well.vizb_las_path PROPERTIES TIMEOUT 300)

# 3) Real dock + real JobCenter lifecycle: destruction under in-flight
#    DTW, save/reopen pick reproducibility, cross-project isolation,
#    tie readout reproducibility.
if(TARGET Pwb::VisualizationCrossWellQt AND TARGET Pwb::VisualizationWellTieQt
   AND TARGET Pwb::UiWellseisQt AND TARGET Pwb::JobQt)
    add_executable(well.dock_lifecycle well_dock_lifecycle_test.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_b_cross_well_dock.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_b_well_source.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/job_center.cpp)
    target_compile_features(well.dock_lifecycle PRIVATE cxx_std_20)
    set_target_properties(well.dock_lifecycle PROPERTIES AUTOMOC ON)
    target_include_directories(well.dock_lifecycle PRIVATE
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform)
    target_link_libraries(well.dock_lifecycle PRIVATE
        Pwb::UiWorkersWleLoad Pwb::VisualizationCrossWellQt
        Pwb::VisualizationWellTieQt Pwb::UiWorkers Pwb::UiWellseisQt
        Pwb::Domain Pwb::JobQt WellLog::IO  # WLE 头直链
        Qt6::Widgets)
    target_compile_definitions(well.dock_lifecycle PRIVATE
        PWB_WELL_FIXTURE_DIR="${PWB_WELL_FIXTURE_DIR}"
        PWB_WITH_VIZ_B=1
        PWB_WITH_VIZ_B_LAS=1)
    add_test(NAME well.dock_lifecycle COMMAND well.dock_lifecycle)
    set_tests_properties(well.dock_lifecycle PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        TIMEOUT 300)
endif()

# 4) 05→04 consumption: real installers register real presenters, the
#    real data page previews real well/time-depth assets (needs the
#    viz-e data-page closure).
if(TARGET Pwb::VizChartsQt AND TARGET Pwb::UiPagesDataQt
   AND TARGET Pwb::UiPagesPreviewQt AND TARGET Pwb::MappingKernel)
    add_executable(well.presenter_flow well_presenter_flow_test.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/well_presenter_install.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/job_center.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_dat_preview.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_factor_preview.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_hosts.cpp
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform/viz_e_install.cpp)
    target_compile_features(well.presenter_flow PRIVATE cxx_std_20)
    set_target_properties(well.presenter_flow PROPERTIES AUTOMOC ON)
    target_include_directories(well.presenter_flow PRIVATE
        ${CMAKE_SOURCE_DIR}/apps/paleo_workbench_platform)
    target_link_libraries(well.presenter_flow PRIVATE
        Pwb::VizChartsQt Pwb::UiPagesDataQt Pwb::UiPagesPreviewQt
        Pwb::MappingKernel Pwb::UiWorkers Pwb::UiWorkersWleLoad
        Pwb::VisualizationCrossWell Pwb::JobQt Pwb::Domain WellLog::IO
        Qt6::Widgets)
    target_compile_definitions(well.presenter_flow PRIVATE
        PWB_WELL_FIXTURE_DIR="${PWB_WELL_FIXTURE_DIR}"
        PWB_WITH_CONV_30=1
        PWB_WELL_PRESENTERS_HAVE_WLE=1
        PWB_WELL_PRESENTERS_HAVE_TIE=1)
    add_test(NAME well.presenter_flow COMMAND well.presenter_flow)
    # 数据页链路带 QGIS 运行时依赖（QtSQL→odbc 等）——SDK/vendored 输出
    # 的 lib 目录进 LD_LIBRARY_PATH（只读复用）。
    set(PWELL_RT_LIBS "${PALEO_QGIS_SDK_DIR}/lib:${PALEO_QGIS_BUILD_DIR}:${PWB_QGIS_DEPS_PREFIX}/lib")
    set_tests_properties(well.presenter_flow PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;LD_LIBRARY_PATH=${PWELL_RT_LIBS}"
        TIMEOUT 300)
endif()
