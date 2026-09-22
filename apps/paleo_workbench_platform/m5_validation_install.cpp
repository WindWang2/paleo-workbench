#include "m5_validation_install.hpp"

#include <functional>
#include <utility>
#include <vector>

#include <QAction>
#include <QActionGroup>
#include <QComboBox>
#include <QDateTime>
#include <QFile>
#include <QPushButton>

#include "app_context.hpp"
#include "app_shell.hpp"
#include "comparison_view.hpp"
#include "m5_validation_install.hpp"
#include "review_disposition_panel.hpp"
#include "validation_workspace_page.hpp"

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_ribbon/qt/ribbon_bar.hpp>

#if defined(PWB_WITH_M5_CLOSURE_REVIEW)
#include <pwb/closure_review/review_disposition.hpp>
#include <pwb/ui_review/qc_issue_rows.hpp>
#endif

namespace pwb::app::m5_validation {

namespace {

using pwb::domain::Json;

std::vector<Json> document_section(const AppContext* context,
                                   const char* name) {
    std::vector<Json> entries;
    const auto store =
        context != nullptr ? context->projectStore() : nullptr;
    if (store == nullptr) {
        return entries;
    }
    const Json& root = store->document().root();
    const auto it = root.find(name);
    if (it != root.end() && it->is_array()) {
        for (const auto& entry : *it) {
            if (entry.is_object()) entries.push_back(entry);
        }
    }
    return entries;
}

QString iso_now() {
    return QDateTime::currentDateTime().toString(Qt::ISODate);
}

}  // namespace

SourceCounts source_counts(const AppContext* context) {
    SourceCounts counts;
    counts.interpretations =
        static_cast<int>(document_section(context, "correlation_interpretations").size());
    counts.predictions =
        static_cast<int>(document_section(context, "prediction_tasks").size());
    return counts;
}

bool link_available(const AppContext* context) {
    const auto store =
        context != nullptr ? context->projectStore() : nullptr;
    if (store == nullptr) {
        return false;
    }
    const Json& root = store->document().root();
    const auto coord_it = root.find("coordinate");
    if (coord_it == root.end() || !coord_it->is_object()) {
        return false;
    }
    const auto cal_it = coord_it->find("time_depth_calibrations");
    return cal_it != coord_it->end() && cal_it->is_array() &&
           !cal_it->empty();
}

void install(const Install& install) {
    auto* shell = install.shell;
    if (shell == nullptr || shell->validation_page() == nullptr) {
        return;
    }
    auto* page = shell->validation_page();

    // ---- 解释 vs 预测对比视图 ----------------------------------------------
    auto* view = new ComparisonView(page);
    view->set_source_provider([context = install.context]() {
        ComparisonView::SourceSet set;
        set.interpretations =
            document_section(context, "correlation_interpretations");
        set.predictions = document_section(context, "prediction_tasks");
        return set;
    });
    view->set_artifact_reader([context = install.context](
                                  const std::string& path)
                                  -> std::optional<Json> {
        const auto store =
            context != nullptr ? context->projectStore() : nullptr;
        if (store == nullptr) {
            return std::nullopt;
        }
        // Artifacts are project-relative portable JSON.
        const auto absolute =
            store->project_file().parent_path() / path;
        QFile file(QString::fromStdString(absolute.string()));
        if (!file.open(QIODevice::ReadOnly)) {
            return std::nullopt;  // honest per-version absence
        }
        const QByteArray body = file.readAll();
        try {
            return Json::parse(body.constData());
        } catch (...) {
            return std::nullopt;  // corrupt artifact — honest absence
        }
    });
    // F:75 gate: no fabricated calibration — the toggle stays disabled
    // with its reason until real time-depth data exists for the well.
    view->set_calibration_provider([](const std::string&) { return false; });
    page->set_compare_view(view);
    QObject::connect(view, &ComparisonView::status_message, shell,
                     &AppShell::status_message);

    // ---- 复核状态机面板 -----------------------------------------------------
    auto* panel = new ReviewDispositionPanel(page);
    panel->set_now_provider(&iso_now);
    panel->set_record_sink(
        [context = install.context, shell](
            const ReviewDispositionPanel::Draft& draft)
            -> std::vector<std::string> {
#if defined(PWB_WITH_M5_CLOSURE_REVIEW)
            const auto store =
                context != nullptr ? context->projectStore() : nullptr;
            if (store == nullptr) {
                return {"需要先打开工程"};
            }
            try {
                // Locate the report that carries this issue (active
                // reports first — the same payload the issue table shows).
                Json reports =
                    store->coordinator().document_section(
                        "quality_reports", store->document());
                if (!reports.is_array()) {
                    return {"工程内没有 QC 报告（先运行检查）"};
                }
                for (auto& report : reports) {
                    if (!report.is_object()) continue;
                    const auto issues_it = report.find("issues");
                    if (issues_it == report.end() || !issues_it->is_array()) {
                        continue;
                    }
                    bool carries = false;
                    for (const auto& issue : *issues_it) {
                        if (issue.is_object() &&
                            pwb::ui_review::qc_issue_key(issue) ==
                                draft.issue_key.toStdString()) {
                            carries = true;
                            break;
                        }
                    }
                    if (!carries) continue;

                    closure_review::ReviewRecord record;
                    record.issue_key = draft.issue_key.toStdString();
                    record.rule = draft.rule.toStdString();
                    record.severity = draft.severity.toStdString();
                    record.reviewer_note = draft.reviewer_note.toStdString();
                    record.created_at = iso_now().toStdString();
                    const auto disposition = closure_review::
                        review_disposition_from_string(
                            draft.disposition_id.toStdString());
                    if (disposition.has_value()) {
                        record.disposition = *disposition;
                    }
                    // 复核 ≠ 通过：attach never touches the original
                    // verdict; the record rides the existing report save.
                    const auto problems =
                        closure_review::attach_review_record(report, record);
                    if (!problems.empty()) {
                        return problems;
                    }
                    store->coordinator().set_document_section(
                        "quality_reports", reports, store->document());
                    if (const auto save_error = store->save_document();
                        !save_error.ok()) {
                        return {save_error.message};
                    }
                    return {};
                }
                return {"没有包含该问题的 QC 报告（输入可能已变化，请重跑检查）"};
            } catch (const std::exception& exc) {
                return {std::string("复核保存失败：") + exc.what()};
            }
#else
            (void)shell;
            return {"复核持久化切片未参与本次构建"};
#endif
        });
    page->set_review_panel(panel);
    QObject::connect(panel, &ReviewDispositionPanel::status_message, shell,
                     &AppShell::status_message);
    QObject::connect(panel, &ReviewDispositionPanel::rerun_requested, page,
                     [page] {
                         if (auto* button = page->findChild<QPushButton*>(
                                 QStringLiteral("ValidationRunQc"));
                             button != nullptr) {
                             button->click();
                         }
                     });

    // Selection link (M3 channel) → the review panel draft.
    QObject::connect(page, &ValidationWorkspacePage::issue_selected, panel,
                     &ReviewDispositionPanel::set_selected_issue);

    // Staleness banner: refreshed whenever the reports refresh.
    QObject::connect(page, &ValidationWorkspacePage::reports_refreshed, panel,
                     [context = install.context, page, panel] {
#if defined(PWB_WITH_M5_CLOSURE_REVIEW)
                         const auto store =
                             context != nullptr ? context->projectStore()
                                                : nullptr;
                         if (store == nullptr || page->reports().empty()) {
                             panel->set_stale(false, QString());
                             return;
                         }
                         const Json& root = store->document().root();
                         const Json& report = page->reports().front();
                         const Json* map_document = nullptr;
                         const auto doc_id_it =
                             report.find("linked_map_document_id");
                         const auto docs_it = root.find("paleomap_documents");
                         if (doc_id_it != report.end() &&
                             doc_id_it->is_string() &&
                             docs_it != root.end() && docs_it->is_array()) {
                             for (const auto& doc : *docs_it) {
                                 const auto id_it = doc.find("id");
                                 if (id_it != doc.end() &&
                                     id_it->is_string() &&
                                     id_it->get<std::string>() ==
                                         doc_id_it->get<std::string>()) {
                                     map_document = &doc;
                                     break;
                                 }
                             }
                         }
                         if (map_document == nullptr) {
                             panel->set_stale(false, QString());
                             return;
                         }
                         // NOTE: the fingerprint must be computed with the
                         // SAME QcInputs the run stamped. Today the
                         // product binds no qc_inputs delegate (the
                         // extended rules skip honestly), so {} on both
                         // sides matches; a future qc_inputs binding must
                         // thread the same inputs into this check.
                         const std::string current =
                             closure_review::qc_input_fingerprint(
                                 root, *map_document, {});
                         const bool stale = closure_review::report_is_stale(
                             report, current);
                         panel->set_stale(
                             stale,
                             QStringLiteral(
                                 "输入版本已变化：本报告已过期，重跑检查后再"
                                 "复核（旧记录保留可追溯）"));
#else
                         (void)context; (void)page;
                         panel->set_stale(false, QString());
#endif
                     });

    // ---- 模式/联动 QAction 组（Ribbon checkable 绑定） ----------------------
    auto* group = new QActionGroup(page);
    group->setExclusive(true);
    const struct {
        const char* name;
        const char* label;
        pwb::ui_review::CompareMode mode;
    } kModes[] = {
        {"VerifyModeSideBySide", "并排", pwb::ui_review::CompareMode::SideBySide},
        {"VerifyModeOverlay", "叠加", pwb::ui_review::CompareMode::Overlay},
        {"VerifyModeDifference", "差异", pwb::ui_review::CompareMode::Difference},
    };
    for (const auto& entry : kModes) {
        auto* action = new QAction(QString::fromUtf8(entry.label), page);
        action->setObjectName(QString::fromLatin1(entry.name));
        action->setCheckable(true);
        group->addAction(action);
        if (entry.mode == pwb::ui_review::CompareMode::SideBySide) {
            action->setChecked(true);
        }
        QObject::connect(action, &QAction::triggered, view,
                         [view, mode = entry.mode] { view->set_mode(mode); });
    }
    auto* link_action = new QAction(QStringLiteral("联动"), page);
    link_action->setObjectName(QStringLiteral("VerifyLinkToggle"));
    link_action->setCheckable(true);
    link_action->setEnabled(false);  // gated by the calibration provider
    QObject::connect(link_action, &QAction::triggered, view,
                     [view] { view->set_link_enabled(true); });
    QObject::connect(view, &ComparisonView::link_availability_changed,
                     link_action, &QAction::setEnabled);
    QObject::connect(view, &ComparisonView::link_changed, link_action,
                     [link_action](bool on) {
                         const QSignalBlocker block(link_action);
                         link_action->setChecked(on);
                     });

    // Ribbon checkable bindings (D4 — the same QAction objects the
    // command callbacks trigger).
    if (shell->ribbon() != nullptr) {
        auto* ribbon = shell->ribbon();
        const struct {
            const char* command_id;
            const char* action_name;
        } kBindings[] = {
            {"verify.side_by_side", "VerifyModeSideBySide"},
            {"verify.overlay", "VerifyModeOverlay"},
            {"verify.difference", "VerifyModeDifference"},
            {"verify.link", "VerifyLinkToggle"},
        };
        for (const auto& binding : kBindings) {
            ribbon->set_command_action(
                QString::fromLatin1(binding.command_id),
                page->findChild<QAction*>(
                    QString::fromLatin1(binding.action_name)));
        }
    }
}

}  // namespace pwb::app::m5_validation
