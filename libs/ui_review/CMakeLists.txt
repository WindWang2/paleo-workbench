# UI-11 — qt-review-gov slice: Qt-free semantic cores + thin Qt Widgets
# shells for the review/governance cluster (review export page, governance
# metadata, catalog health audit, lineage explorer, impact preview,
# version workbench, ingest plan, relink, AI-check advisor, QC issue
# table, workflow contract panel, composite prototype).
#
# Layering (repo convention — ui_map/ui_wellseis split):
#   pwb_ui_review        Qt-free cores (catalog API seam, lineage expand,
#                        impact markdown, advisor html, QC issue rows,
#                        contract lines, ingest columns, relink/audit/
#                        version summaries, review flow texts, composite
#                        layer mutations)
#   pwb_ui_review_qt     Qt Widgets shells; every service call stays
#                        behind an injected seam (ICatalogApi /
#                        IReviewActions / IngestDialogHooks /
#                        ReadinessFn) — never reimplemented here.
#   pwb_ui_review_qgis   [NON-PRODUCTION] the composite prototype needs
#                        the real QGIS DisplayMapCanvas; only where the
#                        SDK is admitted.
#
# task_panel_base.py / prediction_evidence_panel.py /
# prediction_task_panel.py are NOT ported here — UI-09 already owns them
# under pwb::ui_wellseis::qt (Pwb::UiWellseisQt); hosts reuse those
# widgets directly.
#
# Hard requirements (fail-closed at configure, like libs/ui_wellseis):
#   Pwb::Domain             ordered JSON + Result/DataError + stage vocab
#   Pwb::Catalog            audit/impact/models/sources read models
#   Pwb::Data               ingest plan/execute contracts (item editing)
#   Pwb::WorkflowContracts  contract registry + readiness report
#   Pwb::UiDataCore         QC rule-result derivation + stage/size formats
#                         (UI-03 shared helpers — no second copy here)

foreach(_required Pwb::Domain Pwb::Catalog Pwb::Data Pwb::WorkflowContracts
                  Pwb::UiDataCore)
    if(NOT TARGET ${_required})
        message(FATAL_ERROR
            "libs/ui_review requires ${_required} — the root UI-11 "
            "block pulls it in under PWB_BUILD_PLATFORM; standalone "
            "configures must enable it explicitly")
    endif()
endforeach()

add_library(pwb_ui_review STATIC
    src/advisor_html.cpp
    src/audit_summary.cpp
    src/compare_core.cpp
    src/composite_layers.cpp
    src/contract_lines.cpp
    src/impact_markdown.cpp
    src/ingest_columns.cpp
    src/lineage_expand.cpp
    src/qc_issue_rows.cpp
    src/relink_summary.cpp
    src/review_core.cpp
    src/version_view.cpp
)
add_library(Pwb::UiReview ALIAS pwb_ui_review)
target_include_directories(pwb_ui_review PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_features(pwb_ui_review PUBLIC cxx_std_20)
# PUBLIC: headers expose catalog models/audit/impact/sources (catalog_api),
# ingest plan/exec contracts (ingest_columns), workflow contract +
# readiness types (contract_lines), and domain Json/Result.
# PRIVATE: qc_issue_rows / lineage_expand reuse ui_data_core's
# derive_rule_result + stage_label/format_size — header-inline helpers,
# never part of this library's own surface.
target_link_libraries(pwb_ui_review
    PUBLIC Pwb::Domain Pwb::Catalog Pwb::Data Pwb::WorkflowContracts
    PRIVATE Pwb::UiDataCore)

if(TARGET Qt6::Widgets)
    foreach(_required Pwb::UiWidgets Pwb::UiShellQt Pwb::UiPagesDataQt
                      Pwb::UiDataCore Pwb::QgisProcessing)
        if(NOT TARGET ${_required})
            message(FATAL_ERROR
                "libs/ui_review qt shells require ${_required} — enable "
                "the platform UI block (PWB_BUILD_PLATFORM) so it is "
                "configured first")
        endif()
    endforeach()

    add_library(pwb_ui_review_qt STATIC
        src/qt/ai_check_advisor_dialog.cpp
        src/qt/catalog_health_dialog.cpp
        src/qt/governance_dialog.cpp
        src/qt/impact_preview_dialog.cpp
        src/qt/ingest_plan_dialog.cpp
        src/qt/lineage_explorer_dialog.cpp
        src/qt/qc_issue_table.cpp
        src/qt/relink_dialog.cpp
        src/qt/result_summary_panel.cpp
        src/qt/review_export_page.cpp
        src/qt/version_workbench_dialog.cpp
        src/qt/workflow_contract_panel.cpp
        # Q_OBJECT headers listed so AUTOMOC discovers them in this split
        # include/ layout.
        include/pwb/ui_review/qt/ai_check_advisor_dialog.hpp
        include/pwb/ui_review/qt/catalog_health_dialog.hpp
        include/pwb/ui_review/qt/governance_dialog.hpp
        include/pwb/ui_review/qt/impact_preview_dialog.hpp
        include/pwb/ui_review/qt/ingest_plan_dialog.hpp
        include/pwb/ui_review/qt/lineage_explorer_dialog.hpp
        include/pwb/ui_review/qt/qc_issue_table.hpp
        include/pwb/ui_review/qt/relink_dialog.hpp
        include/pwb/ui_review/qt/result_summary_panel.hpp
        include/pwb/ui_review/qt/review_export_page.hpp
        include/pwb/ui_review/qt/version_workbench_dialog.hpp
        include/pwb/ui_review/qt/workflow_contract_panel.hpp
    )
    add_library(Pwb::UiReviewQt ALIAS pwb_ui_review_qt)
    set_target_properties(pwb_ui_review_qt PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_review_qt PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_review_qt PUBLIC cxx_std_20)
    # PUBLIC: headers expose ui_widgets (PwbDialog base, ObjectTableModel*
    # accessors), ui_pages_data::qt::ActionHeader* and
    # ui_shell::FloatController*/LayoutPersistence* return types.
    target_link_libraries(pwb_ui_review_qt
        PUBLIC Pwb::UiReview Pwb::UiWidgets Pwb::UiShellQt
               Pwb::UiPagesDataQt Qt6::Widgets
        PRIVATE Pwb::UiDataCore Pwb::QgisProcessing Qt6::Gui)
endif()

# [NON-PRODUCTION] workstation_composite_prototype.py — the three-layout
# design exploration. Its canvas is the real QGIS DisplayMapCanvas, so it
# only builds where the bridge is admitted (repo convention: a dedicated
# _qgis target, never pulled into the Qt-Widgets shells).
if(TARGET Pwb::UiMapQgis AND TARGET pwb_ui_review_qt)
    add_library(pwb_ui_review_qgis STATIC
        src/qt/composite_prototype.cpp
        include/pwb/ui_review/qt/composite_prototype.hpp
    )
    add_library(Pwb::UiReviewQgis ALIAS pwb_ui_review_qgis)
    set_target_properties(pwb_ui_review_qgis PROPERTIES AUTOMOC ON)
    target_include_directories(pwb_ui_review_qgis PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
    target_compile_features(pwb_ui_review_qgis PUBLIC cxx_std_20)
    target_link_libraries(pwb_ui_review_qgis
        PUBLIC Pwb::UiReviewQt Pwb::UiMapQgis Qt6::Widgets
        PRIVATE Qt6::Gui)
endif()

if(BUILD_TESTING)
    add_subdirectory(ui_review_tests)
endif()
