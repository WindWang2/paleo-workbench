# viz_d.* test suite (CONV-VIZ V5, D-line): frozen-Python replay of the
# advanced seismic display cores (tools/oracle/generate_viz_d_*.py fixtures),
# Qt widget integration, and the xy_scatter/formation-tops preview presenters.
# Every CTest name starts with "viz_d.". Fail-closed: the fixtures and (for
# the widget group) the Qt Widgets SDK are configure-time requirements.

# The widget test links Qt6::Widgets directly and every test consumes it
# transitively through Pwb::SeismicViewer; in reduced configurations (e.g.
# PWB_BUILD_PLATFORM=OFF) no root-scope find_package has imported the Qt
# targets yet, so import them here.
find_package(Qt6 6.8 REQUIRED COMPONENTS Widgets)

function(pwb_viz_d_test target source)
    add_executable(${target} ${source})
    target_compile_features(${target} PRIVATE cxx_std_20)
    target_include_directories(${target} PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/../../../libs/data_suite/third_party  # nlohmann (vendored)
    )
    if(MSVC)
        target_compile_options(${target} PRIVATE /utf-8 /W4 /permissive- /wd4251 /wd4275)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
    target_link_libraries(${target} PRIVATE Pwb::SeismicViewer)
    add_test(NAME ${target} COMMAND ${target})
    set_tests_properties(${target} PROPERTIES
        TIMEOUT 300
        ENVIRONMENT
            "QT_QPA_PLATFORM=offscreen;VIZ_D_FIXTURES=${CMAKE_CURRENT_SOURCE_DIR}/fixtures"
    )
endfunction()

pwb_viz_d_test(viz_d.core viz_d_core_test.cpp)

# The widget group needs a real QApplication (offscreen platform).
pwb_viz_d_test(viz_d.widget viz_d_widget_test.cpp)
target_link_libraries(viz_d.widget PRIVATE Qt6::Widgets)

# The preview replay links the xy_scatter/formation-tops cores (PLATFORM
# family; honest skip when the ui_pages_preview slice is not configured).
if(TARGET Pwb::UiPagesPreview)
    pwb_viz_d_test(viz_d.preview viz_d_preview_test.cpp)
    target_link_libraries(viz_d.preview PRIVATE Pwb::UiPagesPreview Pwb::Ingest)
endif()
