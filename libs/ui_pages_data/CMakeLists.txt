# UI-06 — data/home page library: Qt-free semantic cores (navigation tree
# model, filter chips, asset context menu, module map, QC summary, wizard,
# overview, readiness, activity, preview dispatch, pdf zoom, tag parsing,
# page helpers, shared vocabulary). The Qt Widgets shells live in
# pwb_ui_pages_data_qt (built only when Qt6::Widgets is available).

# pwb::domain::Json (dict-shaped Python state seam) lives in libs/domain,
# which only enters the build via PWB_BUILD_DATA → libs/data_suite. Pull it
# in standalone here when the consuming superproject has not (geo3d_viz
# precedent) so a platform-only configure still builds this library.
if(NOT TARGET Pwb::Domain)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../domain
                     ${CMAKE_CURRENT_BINARY_DIR}/domain)
endif()

add_library(pwb_ui_pages_data STATIC
    src/activity.cpp
    src/chips.cpp
    src/context_menu.cpp
    src/home_model.cpp
    src/module_map.cpp
    src/nav_tree_model.cpp
    src/onboarding_report.cpp
    src/overview.cpp
    src/page_model.cpp
    src/pdf_zoom.cpp
    src/preparation_model.cpp
    src/preview_dispatch.cpp
    src/qc_summary.cpp
    src/readiness.cpp
    src/table_model.cpp
    src/tag_text.cpp
    src/vocab.cpp
    src/wizard_model.cpp
)
add_library(Pwb::UiPagesData ALIAS pwb_ui_pages_data)
target_include_directories(pwb_ui_pages_data PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_pages_data PUBLIC cxx_std_20)
# Qt-free cores; Pwb::Domain supplies the Json seam used by dict-shaped
# Python state (dashboard_state, report dicts, saved-filter payloads).
target_link_libraries(pwb_ui_pages_data PUBLIC Pwb::Domain)

# Qt Widgets shells (UI-06): navigation tree, filter chips bar, data
# toolbar, module relationship canvas, cards, action header, overview
# panel, hub switcher, asset context menu, reader panel, workspace shell,
# table widgets, wizard dialog, tag widgets, page composites.
if(TARGET Qt6::Widgets)
    # PDF preview needs Qt6::Pdf (data_detail_panel); optional component —
    # the panel degrades to a metadata-only widget without it, matching the
    # Python panel's own no-document path.
    find_package(Qt6 6.8 QUIET COMPONENTS Pdf PdfWidgets)

    add_library(pwb_ui_pages_data_qt STATIC
        src/qt/cards.cpp
        src/qt/action_header.cpp
        src/qt/project_overview_panel.cpp
        src/qt/hub_page.cpp
        src/qt/module_map_widget.cpp
        src/qt/navigation_tree_widget.cpp
        src/qt/filter_chips_bar.cpp
        src/qt/data_toolbar.cpp
        src/qt/asset_context_menu.cpp
        src/qt/resource_table.cpp
        src/qt/data_asset_table.cpp
        src/qt/data_reader_panel.cpp
        src/qt/pdf_preview_panel.cpp
        src/qt/data_detail_panel.cpp
        src/qt/data_workspace.cpp
        src/qt/tag_widgets.cpp
        src/qt/new_project_wizard.cpp
        src/qt/home_page.cpp
        # preparation_page.cpp / data_page.cpp deferred — the two largest
        # page composites (377 / 3154 Python lines), see ledgers/ui-06-findings.md.
        # NOTE: preparation_page.hpp is intentionally NOT listed below —
        # its Q_OBJECT moc output embeds a default-ctor thunk for
        # PreparationPage(QWidget* = nullptr), which is unbindable while
        # the .cpp is deferred and breaks every consumer that pulls the
        # mocs_compilation TU (found by ui_review.qt_widgets_smoke).
        # Re-add the header when preparation_page.cpp lands.
        # Q_OBJECT headers must be listed as sources — AUTOMOC does not
        # scan the separate include/ tree on its own.
        include/pwb/ui_pages_data/qt/cards.hpp
        include/pwb/ui_pages_data/qt/action_header.hpp
        include/pwb/ui_pages_data/qt/project_overview_panel.hpp
        include/pwb/ui_pages_data/qt/hub_page.hpp
        include/pwb/ui_pages_data/qt/module_map_widget.hpp
        include/pwb/ui_pages_data/qt/navigation_tree_widget.hpp
        include/pwb/ui_pages_data/qt/filter_chips_bar.hpp
        include/pwb/ui_pages_data/qt/data_toolbar.hpp
        include/pwb/ui_pages_data/qt/asset_context_menu.hpp
        include/pwb/ui_pages_data/qt/resource_table.hpp
        include/pwb/ui_pages_data/qt/data_asset_table.hpp
        include/pwb/ui_pages_data/qt/data_reader_panel.hpp
        include/pwb/ui_pages_data/qt/pdf_preview_panel.hpp
        include/pwb/ui_pages_data/qt/data_detail_panel.hpp
        include/pwb/ui_pages_data/qt/data_workspace.hpp
        include/pwb/ui_pages_data/qt/tag_widgets.hpp
        include/pwb/ui_pages_data/qt/new_project_wizard.hpp
        include/pwb/ui_pages_data/qt/home_page.hpp
    )
    add_library(Pwb::UiPagesDataQt ALIAS pwb_ui_pages_data_qt)
    set_target_properties(pwb_ui_pages_data_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_pages_data_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_pages_data_qt PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_pages_data_qt
        PUBLIC Pwb::UiPagesData Pwb::UiShellQt Qt6::Widgets
        PRIVATE Qt6::Gui)
    if(TARGET Qt6::Pdf)
        target_link_libraries(pwb_ui_pages_data_qt PRIVATE Qt6::Pdf)
        target_compile_definitions(pwb_ui_pages_data_qt PRIVATE PWB_HAVE_QT_PDF=1)
    endif()
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_pages_data_tests)
endif()
