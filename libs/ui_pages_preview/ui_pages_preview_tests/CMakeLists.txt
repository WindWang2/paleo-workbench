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

# BEGIN VIZ-D
# VIZ-D — D 线新增测试（只追加）。注意：本目录先于库 CMakeLists 尾部的
# VIZ-D 块处理，Pwb::Ingest 可能尚未创建 —— 与库块同样的守卫拉入（独立
# 二进制目录，二者只有一个会真正 add）。presenter 冒烟仅在 Qt 壳目标与
# seismic_viewer 都已存在时注册（根构建 PWB_BUILD_SEISMIC_VIEWER=ON 路径；
# 独立配置缺 viewer 时静默跳过，不引入其 fixture 门）。
if(NOT TARGET Pwb::Ingest)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../ingest
                     ${CMAKE_CURRENT_BINARY_DIR}/viz_d_ingest)
endif()
add_executable(ui_pages_preview.viz_d_cores viz_d_cores_test.cpp)
target_compile_features(ui_pages_preview.viz_d_cores PRIVATE cxx_std_20)
target_include_directories(ui_pages_preview.viz_d_cores PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(ui_pages_preview.viz_d_cores PRIVATE
    Pwb::UiPagesPreview Pwb::Ingest)
add_test(NAME ui_pages_preview.viz_d_cores
         COMMAND ui_pages_preview.viz_d_cores)
set_tests_properties(ui_pages_preview.viz_d_cores PROPERTIES TIMEOUT 120)

if(TARGET pwb_ui_pages_preview_qt AND TARGET Pwb::SeismicViewer)
    add_executable(ui_pages_preview.viz_d_presenter_smoke
                   viz_d_presenter_smoke_test.cpp)
    target_compile_features(ui_pages_preview.viz_d_presenter_smoke PRIVATE
        cxx_std_20)
    target_link_libraries(ui_pages_preview.viz_d_presenter_smoke PRIVATE
        Pwb::UiPagesPreviewQt Pwb::SeismicViewer Pwb::Visualization
        Qt6::Widgets Qt6::Gui)
    add_test(NAME ui_pages_preview.viz_d_presenter_smoke
             COMMAND ui_pages_preview.viz_d_presenter_smoke)
    set_tests_properties(ui_pages_preview.viz_d_presenter_smoke PROPERTIES
        TIMEOUT 120
        ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
endif()
# END VIZ-D
