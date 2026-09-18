# CONV-30 — job runtime: bounded scheduler core (Qt-free) + Qt queued
# event bridge. The core has no Qt dependency (tests run headless without
# an event loop); the bridge is a separate target so non-GUI hosts can
# take pwb_job_runtime alone.

add_library(pwb_job_runtime STATIC
    src/job_scheduler.cpp
    src/job_categories.cpp
)
add_library(Pwb::JobRuntime ALIAS pwb_job_runtime)
target_include_directories(pwb_job_runtime PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_job_runtime PUBLIC cxx_std_20)
# Deliberately kernel-clean: no Pwb::Domain / Qt dependency in the core —
# the runtime is usable from any host (tests run headless without Qt).

if(TARGET Qt6::Core)
    add_library(pwb_job_qt STATIC
        src/job_bridge.cpp
        # Q_OBJECT headers must be listed so AUTOMOC picks them up.
        include/pwb/job_runtime/qt/job_bridge.hpp
    )
    add_library(Pwb::JobQt ALIAS pwb_job_qt)
    target_include_directories(pwb_job_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_job_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_job_qt PUBLIC Pwb::JobRuntime Qt6::Core)
    set_target_properties(pwb_job_qt PROPERTIES AUTOMOC ON)
endif()

if(BUILD_TESTING)
    add_subdirectory(job_runtime_tests)
endif()
