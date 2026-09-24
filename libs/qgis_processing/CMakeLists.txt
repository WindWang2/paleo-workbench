# Paleo QGIS Processing convergence (docs/development/
# qgis-native-processing-convergence/07-target-architecture.md).
#
# Pwb::QgisProcessing owns: the Paleo Processing provider (algorithm
# discovery/parameter schema authority), the unified runner, and the
# QgsTaskManager bridge (function tasks, admission gate, GUI owners, task
# center projection). Kernels stay in their Qt-free libraries; this target
# only adapts.

add_library(pwb_qgis_processing STATIC
    src/paleo_algorithm.cpp
    src/grid_io.cpp
    src/provider.cpp
    src/runner.cpp
    src/task_bridge.cpp
    src/task_source.cpp
    src/job_compat.cpp
    src/algorithms/interpolation.cpp
    src/algorithms/mapping.cpp
    src/algorithms/factor.cpp
    src/algorithms/seismic.cpp
    src/algorithms/well.cpp
    src/algorithms/cartography.cpp
    src/algorithms/project.cpp
    # AUTOMOC: Q_OBJECT headers included by these TUs.
    include/pwb/qgis_processing/runner.hpp
    include/pwb/qgis_processing/task_bridge.hpp
    include/pwb/qgis_processing/task_source.hpp
)
add_library(Pwb::QgisProcessing ALIAS pwb_qgis_processing)
target_include_directories(pwb_qgis_processing PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_qgis_processing PUBLIC cxx_std_20)
target_link_libraries(pwb_qgis_processing PUBLIC
    PwbQgis::Sdk
    # Contracts (JobCancelled/JobSpec vocabulary in the public job_compat
    # header) + governance (job_categories / resource_governor used by the
    # task bridge) — deliberately NOT the optional scheduler target, so
    # PWB_BUILD_JOB_SCHEDULER=OFF configurations link.
    Pwb::JobContracts
    Pwb::JobGovernance)
target_link_libraries(pwb_qgis_processing PRIVATE
    Pwb::MappingKernel
    Pwb::FactorFusion
    Pwb::Science
    Pwb::Domain
    # Seismic/well/cartography/project adapter slices.
    Pwb::SeismicAttributes
    Pwb::WellScience
    Pwb::Cartography
    Pwb::Catalog
    Pwb::Interchange
    Pwb::UiPagesPreview)
set_target_properties(pwb_qgis_processing PROPERTIES AUTOMOC ON)

if(BUILD_TESTING)
    add_subdirectory(qgis_processing_tests)
endif()
