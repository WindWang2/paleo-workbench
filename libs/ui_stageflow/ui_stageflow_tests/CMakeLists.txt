# V14-THREE-STAGE-UX — ui_stageflow tests. ctest names: ui_stageflow.* —
# Qt-free core semantics headless, Qt controller offscreen smoke.

add_executable(ui_stageflow.core core_test.cpp)
target_compile_features(ui_stageflow.core PRIVATE cxx_std_20)
target_link_libraries(ui_stageflow.core PRIVATE Pwb::UiStageflow)
target_include_directories(ui_stageflow.core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
add_test(NAME ui_stageflow.core COMMAND ui_stageflow.core)
set_tests_properties(ui_stageflow.core PROPERTIES TIMEOUT 120)

# Qt controller smoke (offscreen): seam-driven refresh/request, layout
# application, preference persistence through the QSettings sink binding.
if(TARGET pwb_ui_stageflow_qt)
    add_executable(ui_stageflow.qt_widgets_smoke qt_smoke_test.cpp)
    target_compile_features(ui_stageflow.qt_widgets_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_stageflow.qt_widgets_smoke PROPERTIES AUTOMOC ON)
    target_link_libraries(ui_stageflow.qt_widgets_smoke PRIVATE
        Pwb::UiStageflowQt Qt6::Widgets)
    add_test(NAME ui_stageflow.qt_widgets_smoke
             COMMAND ui_stageflow.qt_widgets_smoke)
    set_tests_properties(ui_stageflow.qt_widgets_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()
