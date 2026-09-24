# CONV-30 — job runtime, split in three Qt-free layers plus a Qt bridge
# (Wave D: the JobScheduler can exit GUI products while the vocabulary and
# governance stay shared). The layers are Qt-free so tests run headless
# without an event loop; include paths are identical across all targets —
# consumers keep <pwb/job_runtime/...> unchanged.
#
#   pwb_job_contracts   — the job vocabulary: state machine, cancellation
#                         token, JobContext/JobHandle/JobCell, JobSpec, the
#                         AdmissionLease protocol (thread_join_guard.hpp is
#                         header-only and lives in this layer too). Zero
#                         dependencies.
#   pwb_job_governance  — categories, budgets, memory pressure, the
#                         resource governor and the governance glue, on top
#                         of the contracts.
#   pwb_job_runtime     — the bounded scheduler itself (optional; see
#                         PWB_BUILD_JOB_SCHEDULER below).
#   pwb_job_qt          — the Qt queued event bridge wrapping the scheduler.

add_library(pwb_job_contracts STATIC
    src/job_contract.cpp
)
add_library(Pwb::JobContracts ALIAS pwb_job_contracts)
target_include_directories(pwb_job_contracts PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_job_contracts PUBLIC cxx_std_20)
# Deliberately kernel-clean: no Pwb::Domain / Qt dependency in the
# contracts — usable from any host, headless included.

add_library(pwb_job_governance STATIC
    src/job_categories.cpp
    src/resource_budget.cpp
    src/memory_pressure.cpp
    src/resource_governor.cpp
    src/governance.cpp
)
add_library(Pwb::JobGovernance ALIAS pwb_job_governance)
target_include_directories(pwb_job_governance PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_job_governance PUBLIC cxx_std_20)
target_link_libraries(pwb_job_governance PUBLIC Pwb::JobContracts)

# Wave D: GUI products may take contracts/governance alone; the scheduler
# (and the Qt bridge that wraps it) is opt-out so those products drop the
# worker-thread machinery entirely.
option(PWB_BUILD_JOB_SCHEDULER
    "Build the bounded job scheduler + Qt bridge (libs/job_runtime); OFF keeps only the contracts/governance layers" ON)

if(PWB_BUILD_JOB_SCHEDULER)
    add_library(pwb_job_runtime STATIC
        src/job_scheduler.cpp
    )
    add_library(Pwb::JobRuntime ALIAS pwb_job_runtime)
    target_include_directories(pwb_job_runtime PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_job_runtime PUBLIC cxx_std_20)
    # Deliberately kernel-clean: no Pwb::Domain / Qt dependency in the core —
    # the runtime is usable from any host (tests run headless without Qt).
    # Contracts arrive transitively through Pwb::JobGovernance.
    target_link_libraries(pwb_job_runtime PUBLIC Pwb::JobGovernance)

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
endif()

if(BUILD_TESTING)
    add_subdirectory(job_runtime_tests)
endif()
