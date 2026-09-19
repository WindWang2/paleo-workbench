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
