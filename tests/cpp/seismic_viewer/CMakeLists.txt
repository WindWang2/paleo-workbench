# seismic_viewer.* test suite (names follow the shared protocol: every CTest
# name starts with "seismic_viewer."). Mandatory group — fail-closed at
# configure time (see libs/seismic_viewer/CMakeLists.txt): fixtures or the Qt
# Widgets SDK missing is a configure error, never a skipped test.

function(pwb_seismic_viewer_test target source)
    add_executable(${target} ${source})
    target_compile_features(${target} PRIVATE cxx_std_20)
    target_include_directories(${target} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    if(MSVC)
        target_compile_options(${target} PRIVATE /utf-8 /W4 /permissive- /wd4251 /wd4275)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    target_link_libraries(${target} PRIVATE Pwb::SeismicViewer)
    add_test(NAME ${target} COMMAND ${target})
    set_tests_properties(${target} PROPERTIES
        TIMEOUT 240
        ENVIRONMENT
            "QT_QPA_PLATFORM=offscreen;PWB_SEISMIC_VIEWER_SCIENCE_FIXTURES=${PWB_SEISMIC_VIEWER_SCIENCE_FIXTURES};PWB_SEISMIC_VIEWER_FIXTURES=${CMAKE_CURRENT_SOURCE_DIR}/fixtures;PWB_SEISMIC_VIEWER_ARTIFACT_DIR=${CMAKE_CURRENT_BINARY_DIR}"
    )
endfunction()

pwb_seismic_viewer_test(seismic_viewer.contracts contracts_test.cpp)
pwb_seismic_viewer_test(seismic_viewer.controller controller_test.cpp)
pwb_seismic_viewer_test(seismic_viewer.render render_test.cpp)

# The widget group needs a real QApplication (offscreen platform).
pwb_seismic_viewer_test(seismic_viewer.widget widget_test.cpp)
target_link_libraries(seismic_viewer.widget PRIVATE Qt6::Widgets)

# Performance report: measured p50/p95 + coalescing proof on a fixed volume.
pwb_seismic_viewer_test(seismic_viewer.performance performance_test.cpp)
set_tests_properties(seismic_viewer.performance PROPERTIES TIMEOUT 300)
