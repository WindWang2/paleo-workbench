# CONV-30 — job runtime tests. ctest names: job_runtime.* (Qt-free core,
# run headless) and job_qt.* (queued event bridge, offscreen QCoreApplication).
#
# Wave D split: the contracts and governance tests always build; the
# scheduler tests (and the Qt bridge) follow PWB_BUILD_JOB_SCHEDULER so an
# OFF configure still runs everything that does not need the scheduler.

function(pwb_add_job_test name source)
    add_executable(job_runtime_${name} ${source})
    target_compile_features(job_runtime_${name} PRIVATE cxx_std_20)
    target_link_libraries(job_runtime_${name} PRIVATE Pwb::JobRuntime)
    target_include_directories(job_runtime_${name} PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME job_runtime.${name} COMMAND job_runtime_${name})
    set_tests_properties(job_runtime.${name} PROPERTIES TIMEOUT 300)
endfunction()

# Contracts layer (always built).
add_executable(job_runtime.thread_join_guard thread_join_guard_test.cpp)
target_compile_features(job_runtime.thread_join_guard PRIVATE cxx_std_20)
target_link_libraries(job_runtime.thread_join_guard PRIVATE Pwb::JobContracts)
target_include_directories(job_runtime.thread_join_guard PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME job_runtime.thread_join_guard COMMAND job_runtime.thread_join_guard)
set_tests_properties(job_runtime.thread_join_guard PROPERTIES TIMEOUT 300)

# Governance layer (always built; needs the domain JSON closure only).
add_executable(job_runtime.governor_oracle governor_oracle_test.cpp)
target_compile_features(job_runtime.governor_oracle PRIVATE cxx_std_20)
target_link_libraries(job_runtime.governor_oracle PRIVATE
    Pwb::JobGovernance Pwb::Domain)
target_include_directories(job_runtime.governor_oracle PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(job_runtime.governor_oracle PRIVATE
    PWB_GOVERNOR_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/governor_oracle.json")
add_test(NAME job_runtime.governor_oracle COMMAND job_runtime.governor_oracle)
set_tests_properties(job_runtime.governor_oracle PROPERTIES TIMEOUT 120)

# Scheduler layer (optional; the policy oracle replays the frozen ladder
# through the domain JSON conventions (Pwb::Domain), same implication
# shape as CONV-18/23).
if(PWB_BUILD_JOB_SCHEDULER)
    pwb_add_job_test(lifecycle lifecycle_test.cpp)
    pwb_add_job_test(cancel cancel_test.cpp)
    pwb_add_job_test(dedupe dedupe_exception_test.cpp)
    pwb_add_job_test(shutdown shutdown_admission_test.cpp)

    add_executable(job_runtime.policy_oracle policy_oracle_test.cpp)
    target_compile_features(job_runtime.policy_oracle PRIVATE cxx_std_20)
    target_link_libraries(job_runtime.policy_oracle PRIVATE
        Pwb::JobRuntime Pwb::Domain)
    target_include_directories(job_runtime.policy_oracle PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    target_compile_definitions(job_runtime.policy_oracle PRIVATE
        PWB_JOB_POLICY_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/job_policy_oracle.json")
    add_test(NAME job_runtime.policy_oracle COMMAND job_runtime.policy_oracle)
    set_tests_properties(job_runtime.policy_oracle PROPERTIES TIMEOUT 120)
endif()

# Qt bridge (queued event loop; runs offscreen like the platform tests).
if(PWB_BUILD_JOB_SCHEDULER AND TARGET Pwb::JobQt)
    add_executable(job_qt.bridge qt_bridge_test.cpp)
    target_compile_features(job_qt.bridge PRIVATE cxx_std_20)
    target_link_libraries(job_qt.bridge PRIVATE Pwb::JobQt)
    target_include_directories(job_qt.bridge PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    set_target_properties(job_qt.bridge PROPERTIES AUTOMOC ON)
    add_test(NAME job_qt.bridge COMMAND job_qt.bridge)
    set_tests_properties(job_qt.bridge PROPERTIES
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen"
        TIMEOUT 300)
endif()
