# CONV-30 — job runtime tests. ctest names: job_runtime.* (Qt-free core,
# run headless) and job_qt.* (queued event bridge, offscreen QCoreApplication).

function(pwb_add_job_test name source)
    add_executable(job_runtime_${name} ${source})
    target_compile_features(job_runtime_${name} PRIVATE cxx_std_20)
    target_link_libraries(job_runtime_${name} PRIVATE Pwb::JobRuntime)
    target_include_directories(job_runtime_${name} PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME job_runtime.${name} COMMAND job_runtime_${name})
    set_tests_properties(job_runtime.${name} PROPERTIES TIMEOUT 300)
endfunction()

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

# Qt bridge (queued event loop; runs offscreen like the platform tests).
if(TARGET Pwb::JobQt)
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
