# UI-07 — ui_pages_preview tests. ctest names: ui_pages_preview.* —
# oracle replay is Qt-free/headless; the widget smoke runs offscreen.

add_executable(ui_pages_preview.oracle_replay oracle_replay_test.cpp)
target_compile_features(ui_pages_preview.oracle_replay PRIVATE cxx_std_20)
target_include_directories(ui_pages_preview.oracle_replay PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ui_pages_preview.oracle_replay PRIVATE
    Pwb::UiPagesPreview Pwb::Domain)
target_compile_definitions(ui_pages_preview.oracle_replay PRIVATE
    PWB_UI_PAGES_PREVIEW_ORACLE="${CMAKE_CURRENT_SOURCE_DIR}/fixtures/ui_pages_preview_oracle.json")
add_test(NAME ui_pages_preview.oracle_replay
         COMMAND ui_pages_preview.oracle_replay)
set_tests_properties(ui_pages_preview.oracle_replay PROPERTIES TIMEOUT 120)

# Qt widget smoke (offscreen): every ported widget constructs + responds.
if(TARGET pwb_ui_pages_preview_qt)
    add_executable(ui_pages_preview.qt_widgets_smoke qt_widgets_smoke_test.cpp)
    target_compile_features(ui_pages_preview.qt_widgets_smoke PRIVATE cxx_std_20)
    set_target_properties(ui_pages_preview.qt_widgets_smoke PROPERTIES
        AUTOMOC ON)
    target_link_libraries(ui_pages_preview.qt_widgets_smoke PRIVATE
        Pwb::UiPagesPreviewQt Pwb::Visualization Qt6::Widgets Qt6::Gui)
    add_test(NAME ui_pages_preview.qt_widgets_smoke
             COMMAND ui_pages_preview.qt_widgets_smoke)
    set_tests_properties(ui_pages_preview.qt_widgets_smoke PROPERTIES
        TIMEOUT 180
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen;QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox --disable-gpu --single-process")
endif()
