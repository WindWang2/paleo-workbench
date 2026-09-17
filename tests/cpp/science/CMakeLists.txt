# Science test suite (added from libs/science_suite AFTER the viewer adapter
# block). Names follow the shared protocol: every CTest name starts with
# "science.". The Qt-free group below is mandatory — missing fixtures or
# build deps fail the build, they never degrade into skipped tests. The
# viewer group is registered when PWB_SCIENCE_VIEWER_TESTS=ON; the adapter
# target must exist by then (science_suite fail-closes on it), so a missing
# target here is an error, never a silent skip.

function(pwb_science_test target source)
    add_executable(${target} ${source})
    target_compile_features(${target} PRIVATE cxx_std_20)
    target_include_directories(${target} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /permissive- /wd4251 /wd4275)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    add_test(NAME ${target} COMMAND ${target})
    # ctest runs from the build dir; point fixture loading at the source tree.
    set_tests_properties(${target} PROPERTIES TIMEOUT 300
        ENVIRONMENT "PWB_SCIENCE_FIXTURE_ROOT=${CMAKE_CURRENT_SOURCE_DIR}/fixtures")
endfunction()

pwb_science_test(science.contracts contracts_test.cpp)
target_link_libraries(science.contracts PRIVATE Pwb::Science)

pwb_science_test(science.algorithms.coherence_c3_oracle coherence_c3_oracle_test.cpp)
target_link_libraries(science.algorithms.coherence_c3_oracle PRIVATE Pwb::Science)

pwb_science_test(science.workflow.task_runtime task_runtime_test.cpp)
target_link_libraries(science.workflow.task_runtime PRIVATE Pwb::Workflow)

pwb_science_test(science.seismic.slice seismic_slice_test.cpp)
target_link_libraries(science.seismic.slice PRIVATE Pwb::Visualization)

# Opt-in real-viewer group: registered when science_suite enabled
# PWB_SCIENCE_VIEWER_TESTS and the WLE-backed adapter target was already
# created (libs/science_suite adds tests AFTER the viewer block and
# fail-closes on a missing target). The test needs no fixtures beyond the
# shared real LAS file and uses only the public adapter header.
if(PWB_SCIENCE_VIEWER_TESTS)
    if(NOT TARGET Pwb::VisualizationWellLog)
        message(FATAL_ERROR
            "PWB_SCIENCE_VIEWER_TESTS=ON but Pwb::VisualizationWellLog is "
            "missing — tests must be added after the viewer adapter")
    endif()
    add_executable(science.viewer.well_log viewer/well_log_viewer_test.cpp)
    target_compile_features(science.viewer.well_log PRIVATE cxx_std_20)
    target_include_directories(science.viewer.well_log PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
    )
    if(MSVC)
        target_compile_options(science.viewer.well_log PRIVATE /utf-8 /W4 /permissive- /wd4251 /wd4275)
    else()
        target_compile_options(science.viewer.well_log PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    target_link_libraries(science.viewer.well_log PRIVATE
        Pwb::VisualizationWellLog
        Qt6::Widgets
    )
    add_test(NAME science.viewer.well_log
        COMMAND science.viewer.well_log
                "${CMAKE_CURRENT_SOURCE_DIR}/../../fixtures/realdata/A1.Las")
    set_tests_properties(science.viewer.well_log PROPERTIES TIMEOUT 300)
endif()
