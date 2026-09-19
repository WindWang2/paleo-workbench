# UI-04 — core page-worker ports (pwb::ui_workers): Qt-free, Python-free
# C++ cores of the seven PySide6 worker modules in
# paleo_workbench/ui/pages (contour draft, correlation load, DTW
# propagation, factor prepare, geological modeling x4, integrity,
# well-log load) plus the pure kernels they orchestrate (viz resolve,
# geomodel primitives, stratal math, synthetic points).
#
# Every worker is a callable over host-collected input slices; scheduling,
# cooperative cancellation, progress and teardown ride the CONV-30 job
# runtime (Pwb::JobRuntime). Engine-owned pieces (contourpy extraction,
# DTW correlate, LAS/XML parse, .dat horizon parsing, PCG64 demo noise)
# stay behind injected seams — never substituted with different
# algorithms. Frozen against tools/oracle/generate_ui_workers_fixtures.py.

foreach(_required Pwb::JobRuntime Pwb::Domain Pwb::GeoModel)
    if(NOT TARGET ${_required})
        message(FATAL_ERROR
            "libs/ui_workers requires ${_required} — under "
            "PWB_BUILD_PLATFORM the implication table turns on "
            "PWB_BUILD_DATA + PWB_BUILD_CONV_22; standalone configures "
            "must enable them explicitly")
    endif()
endforeach()
# The geomodel worker ports bind the CONV-22 contract layer (advisor /
# export / DomainObject) — the base CONV-12 target alone is not enough.
if(NOT PWB_BUILD_CONV_22)
    message(FATAL_ERROR
        "libs/ui_workers requires PWB_BUILD_CONV_22=ON for the "
        "geomodel advisor/export contract cores")
endif()

add_library(pwb_ui_workers STATIC
    src/worker_common.cpp
    src/viz_resolve.cpp
    src/contour_draft.cpp
    src/correlation_load.cpp
    src/dtw_propagation.cpp
    src/factor_prepare.cpp
    src/synthetic_points.cpp
    src/integrity.cpp
    src/well_log_load.cpp
    src/geomodel_primitives.cpp
    src/stratal.cpp
    src/geological_modeling.cpp)
add_library(Pwb::UiWorkers ALIAS pwb_ui_workers)
target_include_directories(pwb_ui_workers PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_workers PUBLIC cxx_std_20)
# PUBLIC: the headers expose pwb::job::JobSpec/JobContext and
# pwb::domain::Json / pwb::geomodel::DomainObject types.
target_link_libraries(pwb_ui_workers PUBLIC
    Pwb::JobRuntime Pwb::Domain Pwb::GeoModel)

# BEGIN VIZ-A: production WLE load for the well_log seam. Only when the SDK
# participates in the build (science_suite adds well-log-engine before this
# directory); otherwise the seam keeps reporting the engine as unavailable.
if(TARGET WellLog::IO)
    add_library(pwb_ui_workers_wle_load STATIC
        src/wle_load.cpp)
    add_library(Pwb::UiWorkersWleLoad ALIAS pwb_ui_workers_wle_load)
    target_include_directories(pwb_ui_workers_wle_load PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_workers_wle_load PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_workers_wle_load
        PUBLIC Pwb::UiWorkers
        PRIVATE WellLog::IO)
endif()
# END VIZ-A

if(BUILD_TESTING)
    add_subdirectory(ui_workers_tests)
endif()
