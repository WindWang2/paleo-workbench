# Composition-root layout (native-product closure):
#   main.cpp        — thin entry: -> Bootstrap::run
#   bootstrap.cpp   — lifecycle: log chain, QgsApplication/QgisRuntime,
#                     mode dispatch (--self-check/--capabilities/
#                     --diagnostics/interactive), exception gate
#   app_context.cpp — service layer: session + attribute runner + store
#   diagnostics.cpp — product log/error chain + environment probes
#   self_check.cpp  — the self-check battery
#   main_window.cpp — the UI shell (consumes AppContext)
add_executable(pwb-platform
    main.cpp
    bootstrap.cpp
    app_context.cpp
    diagnostics.cpp
    self_check.cpp
    main_window.cpp
    job_center.hpp
    job_center.cpp
)
set_target_properties(pwb-platform PROPERTIES AUTOMOC ON)
target_include_directories(pwb-platform PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(pwb-platform PRIVATE cxx_std_20)
# CONV-PS platform services: theme QSS, settings persistence,
# diagnostics probe, session policy, resource lookup.
target_link_libraries(pwb-platform PRIVATE Pwb::Application Pwb::Ui
    Pwb::PlatformServices)

# Compile-time capability table (generated for every platform build by
# cmake/PwbNativeProduct.cmake; printed by `pwb-platform --capabilities`).
pwb_native_product_generate_capabilities()
target_include_directories(pwb-platform PRIVATE ${PWB_GENERATED_INCLUDE_DIR})

# Runtime closure: QGIS vendor bin + Qt bin (single ABI, no PATH guessing at
# dev time; the deployed package carries its own layout instead).
set_target_properties(pwb-platform PROPERTIES
    BUILD_RPATH "${PALEO_QGIS_RUNTIME}"
    VS_DEBUGGER_ENVIRONMENT "PATH=${PWB_QT_RUNTIME};${PALEO_QGIS_RUNTIME};$ENV{PATH}")

# Dev-time self-check fixture root (deployed packages carry their own).
target_compile_definitions(pwb-platform PRIVATE
    PWB_SOURCE_DIR="${CMAKE_SOURCE_DIR}")

# WLE dock: consume C's viewer adapter (the only WLE build) when present.
if(TARGET Pwb::VisualizationWellLog)
    target_link_libraries(pwb-platform PRIVATE Pwb::VisualizationWellLog)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_WELL_LOG=1)
    # Native track settings panel (layout/template/export) over the host.
    target_sources(pwb-platform PRIVATE well_log_track_panel.cpp)
endif()

# D seismic viewer dock + E attribute kernels: the context is the composition
# root (E's contract: the host registers; no static auto-registration).
if(TARGET Pwb::SeismicViewer)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicViewer)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_SEISMIC_VIEWER=1)
    # BEGIN VIZ-D — advanced seismic display install (menu affordances).
    target_sources(pwb-platform PRIVATE viz_d_seismic_install.cpp)
    # END VIZ-D
endif()
if(TARGET Pwb::SeismicAttributes AND TARGET Pwb::Data
        AND TARGET Pwb::Science AND TARGET Pwb::Workflow)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicAttributes)
    target_compile_definitions(pwb-platform PRIVATE
        PWB_WITH_SEISMIC_ATTRIBUTES=1)
endif()
# Real SEG-Y import (M3): reader + B publication path.
if(TARGET Pwb::SeismicIo AND TARGET Pwb::Data)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicIo)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_SEISMIC_IO=1)
endif()
# S line: native tiled volume service — open catalog volumes without a
# full-volume copy (SeismicVolumeService over the tile cache).
if(TARGET Pwb::SeismicService AND TARGET Pwb::Data)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicService)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_SEISMIC_SERVICE=1)
endif()

# BEGIN CLOSURE-SEISMIC (07) — product binding: ui_wellseis prediction page
# <-> real seismic viewer + volume service + E-line attribute kernels.
if(TARGET Pwb::SeismicViewer AND TARGET Pwb::SeismicService
        AND TARGET Pwb::SeismicAttributes AND TARGET Pwb::UiWellseisQt)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicService
                                               Pwb::SeismicAttributes)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CLOSURE_SEISMIC=1)
    target_sources(pwb-platform PRIVATE closure_seismic_install.cpp)
endif()
# END CLOSURE-SEISMIC

# BEGIN CONV-01
# Swarm task 01: the 地质因子图 action compiles into the app when the slice
# is built (libs/application carries the runner + kernel link).
if(PWB_BUILD_CONV_01)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CONV_01=1)
endif()
# END CONV-01
# BEGIN cpp-close-01 — catalog/project lifecycle closure (line 01)
# The CONCRETE catalog service adapter (closure_catalog_service) + its
# production runtime installer (closure_catalog_install) bound over the
# CONV-31b deep core. Composition-root wiring into MainWindow/AppContext
# stays with line 12; this block only ships the files + link closure.
# The option is declared here (NOT in PwbFeatures.cmake) so line 01 never
# touches the shared feature gate; 12 can hoist it verbatim later.
option(PWB_BUILD_CATALOG_CLOSURE
    "Line-01 catalog/project closure adapter inside pwb-platform" ON)
# NOTE: the target_sources/link/define for this slice moved to the root
# CMakeLists late block — Pwb::UiControllers is created AFTER this
# directory is processed, so a TARGET probe here can never fire.
# END cpp-close-01
# BEGIN PWB-V14-DATA-LINEAGE (P4 product wiring)
# closure_data_workspace — nav-tree population from the live project
# document, the WellDetailPanel producer (ui_wellseis), lineage/impact
# read helpers and the two-phase ingest (toolbar 计划导入). Compiled into
# the app when the data closure AND the data pages are present.
# ui_wellseis ordering: this directory is processed BEFORE the root UI-09
# block adds libs/ui_wellseis, so Pwb::UiWellseisQt cannot be probed yet.
# The guard mirrors UI-09's own gate (Pwb::UiWorkers exists iff CONV_22 +
# GeoModel + Domain + JobRuntime — all resolved before this directory),
# and the link uses the PLAIN target name pwb_ui_wellseis_qt: CMake
# resolves target names in target_link_libraries at generate time, so
# the later add_subdirectory satisfies it.
set(PWB_V14_WELLSEIS OFF)
if(TARGET Pwb::UiWellseisQt)
    set(PWB_V14_WELLSEIS ON)
elseif(PWB_BUILD_CONV_22 AND TARGET Pwb::GeoModel
       AND TARGET Pwb::Domain AND TARGET Pwb::JobRuntime
       AND TARGET Qt6::Widgets)
    set(PWB_V14_WELLSEIS ON)
endif()
if(TARGET Pwb::Data AND TARGET Pwb::UiPagesDataQt AND PWB_V14_WELLSEIS)
    target_sources(pwb-platform PRIVATE
        closure_data_workspace.cpp
        closure_data_workspace.hpp)
    target_link_libraries(pwb-platform PRIVATE
        Pwb::Data Pwb::UiPagesDataQt Pwb::UiWellseis pwb_ui_wellseis_qt)
    target_compile_definitions(pwb-platform PRIVATE
        PWB_WITH_V14_DATA_LINEAGE=1)
endif()
# END PWB-V14-DATA-LINEAGE
# BEGIN native-product closure
# Minimal DAG workflow engine (CONV-07) in the product link closure: the
# self-check battery drives a 4-node diamond through it, proving the
# workflow capability is alive in the product binary.
if(PWB_BUILD_CONV_07)
    target_link_libraries(pwb-platform PRIVATE Pwb::WorkflowEngine)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_WORKFLOW_ENGINE=1)
endif()
# END native-product closure
# BEGIN CONV-30
# CONV-30 async job runtime: the app hosts the bounded scheduler + Qt
# bridge (job_center.*) and the migrated surfaces (SEG-Y import, attribute
# supervision, factor-map compute) submit through it. Fail-closed: an ON
# option without the JobQt target is a configure error.
if(PWB_BUILD_CONV_30)
    if(NOT TARGET Pwb::JobQt)
        message(FATAL_ERROR "PWB_BUILD_CONV_30=ON requires Pwb::JobQt (libs/job_runtime)")
    endif()
    target_link_libraries(pwb-platform PRIVATE Pwb::JobQt)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CONV_30=1)
endif()
# END CONV-30
# BEGIN CONV-16
# conv-16 factor statistics HUD: the dock reads pwb::mapping::GridStatistics
# (FactorGrid.statistics), so the mapping kernel joins the link closure only
# when this cluster is enabled. The interpolation flow calls
# MainWindow::showFactorStatistics once factor results land in the app.
if(PWB_BUILD_CONV_16)
    if(NOT TARGET Pwb::MappingKernel)
        message(FATAL_ERROR "PWB_BUILD_CONV_16=ON requires PWB_BUILD_MAPPING_KERNEL=ON")
    endif()
    target_sources(pwb-platform PRIVATE factor_stats_dock.cpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::MappingKernel)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CONV_16=1)
endif()
# END CONV-16
# BEGIN CONV-27
# Qt6/QGIS workbench closure: stage dock + layer tree panel + edit tools +
# constraint panel + layout persistence (libs/ui Pwb::UiWorkbench).
if(PWB_BUILD_CONV_27)
    if(NOT TARGET Pwb::UiWorkbench)
        message(FATAL_ERROR "PWB_BUILD_CONV_27=ON requires the platform build (PWB_BUILD_PLATFORM=ON)")
    endif()
    target_link_libraries(pwb-platform PRIVATE Pwb::UiWorkbench)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CONV_27=1)
endif()
# END CONV-27

# BEGIN PWB-PACKAGING
# Opt-in diagnostic helper (separate executable, NOT linked into pwb-platform).
# Built only when the app's UI/Application Qt-linked libs exist, mirroring the
# platform target's own guard. It reports the install tree it expects and is
# used by the native packaging skeleton (cmake/PwbInstall.cmake).
# Gated on PWB_ENABLE_PACKAGING as well: without it the configured build graph
# must be identical to main, and an extra executable target is a graph change.
if(PWB_ENABLE_PACKAGING AND (TARGET Pwb::Ui OR TARGET Pwb::Application))
    include(GNUInstallDirs)
    add_executable(pwb-diagnose diag_main.cpp)
    set_target_properties(pwb-diagnose PROPERTIES AUTOMOC ON)
    target_compile_features(pwb-diagnose PRIVATE cxx_std_20)
    target_include_directories(pwb-diagnose PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    if(TARGET Pwb::Ui)
        target_link_libraries(pwb-diagnose PRIVATE Pwb::Ui)
    else()
        target_link_libraries(pwb-diagnose PRIVATE Pwb::Application)
    endif()
    target_compile_definitions(pwb-diagnose PRIVATE
        PWB_HAS_QT
        PWB_VERSION="${PROJECT_VERSION}"
        PWB_INSTALL_PREFIX="${CMAKE_INSTALL_PREFIX}"
        PWB_RESOURCE_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_DATADIR}/paleo-workbench/resources"
        PWB_TEMPLATE_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_DATADIR}/paleo-workbench/templates"
        PWB_ICON_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_DATADIR}/paleo-workbench/icons"
        PWB_SCHEMA_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_DATADIR}/paleo-workbench/schema"
        PWB_BIN_DIR="${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}")
    if(DEFINED PALEO_QGIS_RUNTIME)
        target_compile_definitions(pwb-diagnose PRIVATE
            PWB_QGIS_RUNTIME_DIR="${PALEO_QGIS_RUNTIME}")
    endif()
    if(DEFINED PWB_QT_RUNTIME)
        target_compile_definitions(pwb-diagnose PRIVATE
            PWB_QT_RUNTIME_DIR="${PWB_QT_RUNTIME}")
    endif()
endif()
# END PWB-PACKAGING

# BEGIN V14-COMPILATION-PUBLISH
# The composition install's colour-ramp seam resolves through the
# cartography authority (composer PALETTE_ALIASES → get_color_ramp).
if(TARGET Pwb::Cartography)
    target_link_libraries(pwb-platform PRIVATE Pwb::Cartography)
endif()
# The QC provenance registrar rides the workflow provenance rail when the
# closure_workflow slice is in the build; otherwise the seam stays unbound
# and the QC report keeps its honest provenance_registered=false marker.
if(TARGET Pwb::ClosureWorkflow)
    target_sources(pwb-platform PRIVATE closure_review_install.cpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::ClosureWorkflow)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CLOSURE_WORKFLOW=1)
endif()
# END V14-COMPILATION-PUBLISH

# BEGIN CONV-29
# Composition/Layout/Export C++ closure: the export dialog routes through
# CompositionLayoutService (kernel spec + shared executor + parity).
# Service and kernel join the link closure via Pwb::Qgis (CONV-29 gated in
# libs/qgis).
if(PWB_BUILD_CONV_29)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CONV_29=1)
endif()
# END CONV-29

# BEGIN CONV-PROVIDERS
# Native capability-provider runtime: the composition root consumes
# pwb::providers::ProviderService (registry + capability query + guarded
# run) exactly like the AlgorithmRunner seam. Linked only when
# PWB_BUILD_PROVIDERS is on, so the app stays buildable without the SDK.
if(TARGET Pwb::Providers)
    target_link_libraries(pwb-platform PRIVATE Pwb::Providers)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_PROVIDERS=1)
endif()
# END CONV-PROVIDERS

# BEGIN VIZ-B
# Cross-well correlation & well-tie dock (line B): the wiring moved to the
# root VIZ-B block — apps/ is processed before the cross_well/well_tie/
# ui_workers/ui_wellseis slices, so a TARGET gate here could never fire.
# END VIZ-B

# BEGIN 05 — viz_b real LAS path: joins the dock when the VIZ-A WLE load
# bridge participates in this configure. Without it the dock keeps the
# honest "LAS 解析内核未接入" path (fail-closed, never a fake load).
if(TARGET Pwb::UiWorkersWleLoad AND TARGET Pwb::IngestLasWle)
    target_sources(pwb-platform PRIVATE viz_b_well_source.cpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::UiWorkersWleLoad)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_VIZ_B_LAS=1)
endif()
# END 05

# BEGIN CONV-GEO3D
# Native 3D geomodel viewer dock (Qt6 viewport + workspace controller, no
# Python). Joins the link closure only when the PWB_BUILD_GEO3D_VIZ slice
# built Pwb::Geo3DViz.
if(TARGET Pwb::Geo3DViz)
    target_sources(pwb-platform PRIVATE geo3d_dock.cpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::Geo3DViz)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_GEO3D_VIZ=1)
endif()
# END CONV-GEO3D

# BEGIN VIZ-C
# Joint well-seismic 3D (plan V4): the WellSeismicScene core lives in
# Pwb::Geo3DViz (joint/ subtree); these are the platform bridges — the
# tiled-volume adapter + mesh builders, the 2D time map and the REAL
# #1394 JointHostController host. The host needs the ui_wellseis seam
# types; both slices degrade out independently (fail-closed configure,
# never a fake host).
if(TARGET Pwb::Geo3DViz AND TARGET Pwb::SeismicService)
    target_sources(pwb-platform PRIVATE
        viz_c_joint_volume.cpp
        viz_c_time_map.cpp
        closure_joint3d_install.cpp)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicService)
    # viz_c_joint_host.cpp + PWB_WITH_UI_WELLSEIS are wired from the root
    # VIZ-C block: libs/ui_wellseis joins the build AFTER this app
    # subdirectory, so a target-existence check here would silently skip
    # the host (never a fake seam).
endif()
# END VIZ-C
