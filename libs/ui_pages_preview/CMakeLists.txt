# UI-07 — preview pages cluster: Qt-free semantic cores
# (preview_settings, preview_table, json_tree_spec, pdf_zoom, image_zoom,
# media_time, lazy_tabs_state, seismic_slice_spec, url_filter,
# summary_chips) and the Qt Widgets shells in pwb_ui_pages_preview_qt
# (built only when Qt6::Widgets is available).

add_library(pwb_ui_pages_preview STATIC
    src/preview_settings.cpp
    src/preview_table.cpp
    src/json_tree_spec.cpp
    src/pdf_zoom.cpp
    src/image_zoom.cpp
    src/media_time.cpp
    src/lazy_tabs_state.cpp
    src/seismic_slice_spec.cpp
    src/summary_chips.cpp
    src/url_filter.cpp
)
add_library(Pwb::UiPagesPreview ALIAS pwb_ui_pages_preview)
target_include_directories(pwb_ui_pages_preview PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_pages_preview PUBLIC cxx_std_20)
# domain::Json + Sha256 back the settings mapping/fingerprint.
if(NOT TARGET Pwb::Domain)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../domain
                     ${CMAKE_CURRENT_BINARY_DIR}/domain)
endif()
target_link_libraries(pwb_ui_pages_preview PUBLIC Pwb::Domain)

# Qt Widgets shells (UI-07): table/text/rich_text/message/json_tree/image/
# pdf/media/web_document/seismic_slice/summary_table/geotiff preview
# widgets, preview settings panel + QSettings store, lazy visualization
# tabs. Qt6::Pdf/PdfWidgets, Qt6::Multimedia(MultimediaWidgets) and
# Qt6::WebEngineWidgets are each optional — a missing backend compiles the
# same degraded path Python reaches on import failure (PWB_*_HAVE_*).
if(TARGET Qt6::Widgets)
    find_package(Qt6 QUIET COMPONENTS Pdf PdfWidgets)
    find_package(Qt6 QUIET COMPONENTS Multimedia MultimediaWidgets)
    find_package(Qt6 QUIET COMPONENTS WebEngineWidgets)

    # ISeismicVolume + map_slice_to_indexed8 for the seismic slice widget.
    # Reuse the target when the consuming superproject already provides it.
    if(NOT TARGET Pwb::Visualization)
        add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../visualization
                         ${CMAKE_CURRENT_BINARY_DIR}/visualization)
    endif()

    add_library(pwb_ui_pages_preview_qt STATIC
        src/qt/table_preview_model.cpp
        src/qt/table_preview_widget.cpp
        src/qt/text_preview_widget.cpp
        src/qt/rich_text_preview_widget.cpp
        src/qt/message_preview_widget.cpp
        src/qt/json_tree_preview_widget.cpp
        src/qt/image_preview_widget.cpp
        src/qt/pdf_preview_widget.cpp
        src/qt/media_preview_widget.cpp
        src/qt/web_document_preview_widget.cpp
        src/qt/seismic_slice_preview_widget.cpp
        src/qt/summary_table_preview_widget.cpp
        src/qt/geotiff_preview_widget.cpp
        src/qt/preview_settings_store.cpp
        src/qt/preview_settings_panel.cpp
        src/qt/lazy_visualization_tabs.cpp
        # Q_OBJECT headers must be listed as sources — AUTOMOC does not
        # scan the separate include/ tree on its own.
        include/pwb/ui_pages_preview/qt/table_preview_model.hpp
        include/pwb/ui_pages_preview/qt/table_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/text_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/rich_text_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/message_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/json_tree_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/image_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/pdf_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/media_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/web_document_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/seismic_slice_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/summary_table_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/geotiff_preview_widget.hpp
        include/pwb/ui_pages_preview/qt/preview_settings_store.hpp
        include/pwb/ui_pages_preview/qt/preview_settings_panel.hpp
        include/pwb/ui_pages_preview/qt/lazy_visualization_tabs.hpp
    )
    add_library(Pwb::UiPagesPreviewQt ALIAS pwb_ui_pages_preview_qt)
    set_target_properties(pwb_ui_pages_preview_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_pages_preview_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_pages_preview_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_pages_preview_qt
        PUBLIC Pwb::UiPagesPreview Pwb::UiShellQt Pwb::PlatformServices
               Pwb::Visualization Qt6::Widgets
        PRIVATE Qt6::Gui)

    if(TARGET Qt6::Pdf)
        target_link_libraries(pwb_ui_pages_preview_qt PRIVATE Qt6::Pdf)
        target_compile_definitions(pwb_ui_pages_preview_qt
            PRIVATE PWB_UI_PAGES_PREVIEW_HAVE_PDF=1)
    endif()
    if(TARGET Qt6::PdfWidgets)
        target_link_libraries(pwb_ui_pages_preview_qt PRIVATE Qt6::PdfWidgets)
        target_compile_definitions(pwb_ui_pages_preview_qt
            PRIVATE PWB_UI_PAGES_PREVIEW_HAVE_PDFWIDGETS=1)
    endif()
    if(TARGET Qt6::Multimedia)
        target_link_libraries(pwb_ui_pages_preview_qt PRIVATE Qt6::Multimedia)
        target_compile_definitions(pwb_ui_pages_preview_qt
            PRIVATE PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIA=1)
    endif()
    if(TARGET Qt6::MultimediaWidgets)
        target_link_libraries(pwb_ui_pages_preview_qt
            PRIVATE Qt6::MultimediaWidgets)
        target_compile_definitions(pwb_ui_pages_preview_qt
            PRIVATE PWB_UI_PAGES_PREVIEW_HAVE_MULTIMEDIAWIDGETS=1)
    endif()
    if(TARGET Qt6::WebEngineWidgets)
        target_link_libraries(pwb_ui_pages_preview_qt
            PRIVATE Qt6::WebEngineWidgets)
        target_compile_definitions(pwb_ui_pages_preview_qt
            PRIVATE PWB_UI_PAGES_PREVIEW_HAVE_WEBENGINE=1)
    endif()
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_pages_preview_tests)
endif()

# BEGIN VIZ-D
# VIZ-D — D 线增量源（只追加，不改上方既有内容）：
#   * well_head_scatter_core / formation_tops_preview —— Qt-free 核心，
#     进 pwb_ui_pages_preview。经 Pwb::Ingest 复用冻结的 Python 兼容
#     原语（py_strip / py_parse_float / UTF-8 码点）与
#     parse_well_tops_text；formation_tops_preview.hpp 公开包含
#     <pwb/ingest/well_parsers.hpp>，故为 PUBLIC 链接。
#   * seismic_preview_presenter —— A3 异步地震预览 presenter，仅进 Qt 壳
#     目标；切片调度复用 seismic_viewer 的 SliceController（根构建里
#     libs/seismic_viewer 先于本目录加入，别名已存在；独立配置时拉入
#     同级目录并关闭其自带测试以避开冻结 fixture 门）。
if(NOT TARGET Pwb::Ingest)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../ingest
                     ${CMAKE_CURRENT_BINARY_DIR}/viz_d_ingest)
endif()
target_sources(pwb_ui_pages_preview PRIVATE
    src/well_head_scatter_core.cpp
    src/formation_tops_preview.cpp
)
target_link_libraries(pwb_ui_pages_preview PUBLIC Pwb::Ingest)

if(TARGET Qt6::Widgets AND TARGET pwb_ui_pages_preview_qt)
    target_sources(pwb_ui_pages_preview_qt PRIVATE
        src/qt/seismic_preview_presenter.cpp
        # 无 Q_OBJECT；列出以与上方壳目标的头文件罗列惯例一致。
        include/pwb/ui_pages_preview/qt/seismic_preview_presenter.hpp
    )
    if(NOT TARGET Pwb::SeismicViewer)
        set(PWB_SEISMIC_VIEWER_BUILD_TESTS OFF) # 被消费时不注册其自带测试
        # seismic_viewer 私有链接 pwb_seismic_attributes（crossplot 核复用
        # 冻结核），此处先补属性库，避免普通目标名落空。
        if(NOT TARGET pwb_seismic_attributes)
            set(PWB_SEISMIC_ATTRIBUTES_BUILD_TESTS OFF)
            add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../seismic_attributes
                             ${CMAKE_CURRENT_BINARY_DIR}/viz_d_seismic_attributes)
        endif()
        add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../seismic_viewer
                         ${CMAKE_CURRENT_BINARY_DIR}/viz_d_seismic_viewer)
    endif()
    # presenter 头文件公开引用 SliceController/VolumeIdentity；编译期为
    # PRIVATE（按 VIZ-D 契约，消费方按需自行链 Pwb::SeismicViewer）。
    target_link_libraries(pwb_ui_pages_preview_qt PRIVATE Pwb::SeismicViewer)
endif()
# END VIZ-D
