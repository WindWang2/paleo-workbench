# UI-04 — ui_workers oracle + behavior tests.
#   * ui_workers.oracle — replays the frozen Python oracle cases
#     (tools/oracle/generate_ui_workers_fixtures.py) against the ported
#     kernels and worker run() bodies; a negative self-check case proves
#     the harness fails when expected behavior is altered.
#   * ui_workers.lifecycle — multithreaded job-runtime lifecycle:
#     cancellation checkpoints, cancelling-once semantics, late-result
#     discard, partial-result-on-cancel, progress ordering.

add_executable(ui_workers.oracle ui_workers_oracle_test.cpp)
target_compile_features(ui_workers.oracle PRIVATE cxx_std_20)
target_link_libraries(ui_workers.oracle PRIVATE Pwb::UiWorkers Pwb::Domain)
target_compile_definitions(ui_workers.oracle PRIVATE
    PWB_UI_WORKERS_FIXTURE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/ui_workers_oracle.json")
add_test(NAME ui_workers.oracle COMMAND ui_workers.oracle)
set_tests_properties(ui_workers.oracle PROPERTIES TIMEOUT 180)

add_executable(ui_workers.lifecycle ui_workers_lifecycle_test.cpp)
target_compile_features(ui_workers.lifecycle PRIVATE cxx_std_20)
target_link_libraries(ui_workers.lifecycle PRIVATE Pwb::UiWorkers Pwb::Domain)
add_test(NAME ui_workers.lifecycle COMMAND ui_workers.lifecycle)
set_tests_properties(ui_workers.lifecycle PROPERTIES TIMEOUT 180)
