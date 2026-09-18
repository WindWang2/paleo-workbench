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
)
set_target_properties(pwb-platform PROPERTIES AUTOMOC ON)
target_include_directories(pwb-platform PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_features(pwb-platform PRIVATE cxx_std_20)
target_link_libraries(pwb-platform PRIVATE Pwb::Application Pwb::Ui)

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
endif()

# D seismic viewer dock + E attribute kernels: the context is the composition
# root (E's contract: the host registers; no static auto-registration).
if(TARGET Pwb::SeismicViewer)
    target_link_libraries(pwb-platform PRIVATE Pwb::SeismicViewer)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_SEISMIC_VIEWER=1)
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

# BEGIN CONV-01
# Swarm task 01: the 地质因子图 action compiles into the app when the slice
# is built (libs/application carries the runner + kernel link).
if(PWB_BUILD_CONV_01)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_CONV_01=1)
endif()
# END CONV-01
# BEGIN native-product closure
# Minimal DAG workflow engine (CONV-07) in the product link closure: the
# self-check battery drives a 4-node diamond through it, proving the
# workflow capability is alive in the product binary.
if(PWB_BUILD_CONV_07)
    target_link_libraries(pwb-platform PRIVATE Pwb::WorkflowEngine)
    target_compile_definitions(pwb-platform PRIVATE PWB_WITH_WORKFLOW_ENGINE=1)
endif()
# END native-product closure
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
