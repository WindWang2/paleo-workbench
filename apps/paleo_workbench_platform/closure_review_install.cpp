#include "closure_review_install.hpp"

#include <QDateTime>
#include <QObject>

#include <pwb/application/adapters/data_store.hpp>
#include <pwb/closure_review/project_review_actions.hpp>
#include <pwb/closure_review/review_disposition.hpp>
#include <pwb/closure_review/review_qc_core.hpp>
#ifdef PWB_WITH_CLOSURE_WORKFLOW
#include <pwb/closure_workflow/persistent_catalog.hpp>
#endif  // PWB_WITH_CLOSURE_WORKFLOW
#include <pwb/domain/errors.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_review/qt/review_export_page.hpp>
#include <pwb/ui_workstation/verify_records_panel.hpp>

#include "job_center.hpp"

#include <algorithm>
#include <filesystem>
#include <memory>
#include <mutex>
#include <optional>
#include <utility>
#include <vector>

#include "app_context.hpp"
#include "app_shell.hpp"
#include "validation_workspace_page.hpp"

// The backend lives in pwb::closure_review; inside pwb::app::closure_review
// the unqualified name would resolve to this (empty) namespace.
namespace clr = pwb::closure_review;

namespace pwb::app::closure_review {

namespace {

constexpr const char* kBindingObjectName = "pwb_closure_review_binding";

// The shell-parented binding: owns the ProjectReviewActions whose
// delegates resolve the CURRENT AppContext store on every call, so a
// project open/close is picked up without re-installing. Not a Q_OBJECT —
// it is looked up by its reserved object name (only this file creates it),
// which keeps the app target free of new moc inputs.
class ReviewBinding : public QObject {
public:
#ifdef PWB_WITH_CLOSURE_WORKFLOW
    // BEGIN V14-COMPILATION-PUBLISH — per-project workflow provenance rail.
    std::shared_ptr<pwb::closure_workflow::FileCatalogRepository> rail_;
    std::filesystem::path rail_file_;
    std::mutex rail_mutex_;
#endif  // PWB_WITH_CLOSURE_WORKFLOW
    // The SAME registrar the sync path delegates through (the async QC
    // merge stamps provenance with this copy — one registration surface).
    std::function<std::string(const domain::Json&)> provenance_fn_;
    // Async QC task owner (JobCenter slot; registered for close protocol).
    pwb::qgis_processing::PwbTaskOwner* qc_owner_ = nullptr;

    ReviewBinding(AppShell* shell, AppContext* context)
        : QObject(shell), shell_(shell), context_(context) {
#ifdef PWB_WITH_DATA_INTEGRATION
        clr::ProjectReviewActions::Delegates d;
        d.document = [this]() -> domain::Json* {
            const auto store = context_->projectStore();
            return store != nullptr ? &store->document().root() : nullptr;
        };
        d.project_file = [this]() -> std::filesystem::path {
            const auto store = context_->projectStore();
            return store != nullptr ? store->project_file()
                                    : std::filesystem::path();
        };
        d.save = [this]() -> domain::DataError {
            const auto store = context_->projectStore();
            if (store == nullptr) {
                return domain::DataError(domain::ErrorCode::InvalidArgument,
                                         "未绑定工程");
            }
            return store->save_document();
        };
        // BEGIN V14-COMPILATION-PUBLISH — the QC provenance registrar:
        // the report's DataRun registration rides the workflow provenance
        // rail (FileCatalogRepository — the production CatalogRepository
        // the cpp-close-02 line established). The registrar returns the
        // run id on success and an empty string on any failure, so the
        // report's provenance_registered flag stays honest either way.
        // The deep-core catalog bridge (the adapter's register_run) is a
        // declared follow-up: until it lands this rail is the real,
        // persisted registration surface. Without the closure_workflow
        // slice the seam stays unbound — the report keeps its honest
        // provenance_registered=false marker (never a claimed run).
#ifdef PWB_WITH_CLOSURE_WORKFLOW
        provenance_fn_ = [this](const domain::Json& report) -> std::string {
            const auto store = context_->projectStore();
            if (store == nullptr) return {};
            auto rail = workflow_rail();
            if (!rail) return {};
            try {
                const std::string run_id = rail->register_run(
                    "map_qc", {}, report, "closure-review-v1", "running");
                rail->update_run_status(run_id, "complete");
                return run_id;
            } catch (...) {
                // A registration failure must never fail the QC run; the
                // false provenance_registered flag makes the loss visible.
                return {};
            }
        };
        d.provenance = provenance_fn_;
#endif  // PWB_WITH_CLOSURE_WORKFLOW
        actions_ =
            std::make_unique<clr::ProjectReviewActions>(std::move(d));
#endif  // PWB_WITH_DATA_INTEGRATION
    }

#ifdef PWB_WITH_CLOSURE_WORKFLOW
    // The per-project workflow provenance rail (lazy; opened once per
    // project file). A corrupt/absent file yields an empty store, never a
    // silent reset over provenance (FileCatalogRepository::open contract).
    // Returns a COPY (shared_ptr by value): the caller then uses the rail
    // without holding the mutex, and a concurrent project switch cannot
    // destroy the instance mid-use.
    std::shared_ptr<pwb::closure_workflow::FileCatalogRepository> workflow_rail() {
        const auto store = context_ != nullptr ? context_->projectStore() : nullptr;
        const std::filesystem::path project_file =
            store != nullptr ? store->project_file() : std::filesystem::path();
        std::lock_guard<std::mutex> guard(rail_mutex_);
        if (rail_ != nullptr && rail_file_ == project_file) return rail_;
        rail_ = nullptr;
        rail_file_ = project_file;
        if (project_file.empty()) return rail_;
        try {
            auto rail =
                std::make_shared<pwb::closure_workflow::FileCatalogRepository>();
            rail->open(project_file.parent_path() / "workflow_store");
            rail_ = std::move(rail);
        } catch (...) {
            // Corrupt rail: refuse to register over provenance — the QC
            // report keeps provenance_registered=false (honest).
            rail_ = nullptr;
        }
        return rail_;
    }
#endif  // PWB_WITH_CLOSURE_WORKFLOW

    void attach(JobCenter* jobs) {
        setObjectName(QString::fromLatin1(kBindingObjectName));
        auto* widget = review_page();
        if (widget == nullptr) {
            return;
        }
#ifdef PWB_WITH_DATA_INTEGRATION
        // The binding outlives the page's provider calls (QObject child of
        // the shell); the page additionally guards with project_bound_, so
        // an absent store keeps its honest 未绑定工程 state.
        ui_review::IReviewActions* exposed = actions_.get();
        widget->set_actions_provider(
            [exposed]() -> ui_review::IReviewActions* { return exposed; });
        // M3 (P0-4): the 验证 workspace page consumes the SAME provider —
        // one review authority for both surfaces (run/locate/export stay
        // in ProjectReviewActions).
        if (auto* validation = shell_->validation_page();
            validation != nullptr) {
            validation->set_actions_provider(
                [exposed]() -> ui_review::IReviewActions* {
                    return exposed;
                });
            // ---- async QC seam（verify.cancel 的生产基础） ---------------
            // snapshot(GUI) → run(worker, 快照副本 + 协作取消) →
            // merge(GUI, provenance + apply_qc_report 进 LIVE root +
            // save)。cancelled 永不 merge——上一份有效报告保持不变。
            if (jobs != nullptr) {
                qc_owner_ = &jobs->make_owner(this);
                validation->set_task_owner(qc_owner_);
            }
            ValidationWorkspacePage::AsyncQc seam;
            seam.snapshot =
                [this]() -> std::optional<
                    std::pair<domain::Json, std::vector<std::string>>> {
                    const auto store = context_->projectStore();
                    if (store == nullptr) return std::nullopt;
                    const domain::Json& root =
                        store->document().root();
                    const domain::Json docs =
                        clr::paleomap_documents_of(root);
                    if (!docs.is_array() || docs.empty()) {
                        return std::nullopt;
                    }
                    std::vector<std::string> ids;
                    for (const auto& doc : docs) {
                        if (doc.is_object() && doc.contains("id")
                            && doc.at("id").is_string()) {
                            ids.push_back(
                                doc.at("id").get<std::string>());
                        }
                    }
                    if (ids.empty()) return std::nullopt;
                    // Json copy = deep copy：worker 拿到的是不可变快照。
                    return std::make_pair(root, ids);
                };
            seam.run = [](domain::Json& snapshot_root,
                          const std::vector<std::string>& doc_ids,
                          const std::function<bool()>& check_cancelled)
                -> std::vector<domain::Json> {
                // The delegate seam takes a pointer to a function OBJECT —
                // a static wrapper keeps it alive for the whole run.
                static const clr::CartographicQaDelegate
                    kDefaultCartographic =
                        &clr::geometry_cartographic_issues;
                const std::string iso =
                    QDateTime::currentDateTime()
                        .toString(Qt::ISODate)
                        .toStdString();
                std::vector<domain::Json> reports;
                for (const std::string& id : doc_ids) {
                    if (!check_cancelled()) break;
                    auto result = clr::run_map_qc_on_document(
                        snapshot_root, id, /*inputs=*/{},
                        &kDefaultCartographic, iso,
                        /*provenance=*/nullptr);
                    if (result.is_ok()) {
                        reports.push_back(std::move(result).value());
                    }
                }
                return reports;
            };
            seam.merge =
                [this](const std::vector<domain::Json>& reports)
                -> std::string {
                const auto store = context_->projectStore();
                if (store == nullptr) return "未绑定工程";
                try {
                    domain::Json& root = store->document().root();
                    const std::string iso = QDateTime::currentDateTime()
                                                .toString(Qt::ISODate)
                                                .toStdString();
                    for (const domain::Json& report : reports) {
                        domain::Json stored = report;
                        // provenance 注册与同步路径同一注册面（注册失败
                        // 不失败 QC——false 标记可见）。
                        stored["provenance_registered"] = false;
                        if (provenance_fn_) {
                            try {
                                const std::string run_id =
                                    provenance_fn_(stored);
                                if (!run_id.empty()) {
                                    stored["provenance_registered"] =
                                        true;
                                    stored["provenance_run_id"] =
                                        run_id;
                                }
                            } catch (...) {
                            }
                        }
                        clr::apply_qc_report(root, stored, iso);
                    }
                    const auto save_error = store->save_document();
                    if (!save_error.ok()) return save_error.message;
                    return {};
                } catch (const std::exception& exc) {
                    return exc.what();
                }
            };
            validation->set_async_qc(std::move(seam));
        }
        // 底条「验证记录」表 = quality_reports[].review_records 的只读
        // 投影 —— 同一复核权威；provider 每次 refresh 重拉当前文档，
        // 无工程/无记录即空表（诚实缺席）。
        if (auto* panel = shell_->verify_records_panel();
            panel != nullptr) {
            panel->set_records_provider(
                [this]() -> std::vector<QStringList> {
                    std::vector<QStringList> rows;
                    if (!available()) return rows;
                    const domain::Json reports = clr::active_quality_reports_of(
                        context_->projectStore()->document().root());
                    if (!reports.is_array()) return rows;
                    for (const auto& report : reports) {
                        if (!report.is_object()) continue;
                        for (const auto& record :
                             clr::review_records_of(report)) {
                            rows.push_back(
                                {QString::fromStdString(record.issue_key),
                                 QString::fromStdString(record.rule),
                                 QString::fromStdString(record.severity),
                                 QString::fromUtf8(
                                     clr::review_disposition_label(
                                         record.disposition)),
                                 QString::fromStdString(record.author),
                                 QString::fromStdString(record.created_at)});
                        }
                    }
                    return rows;
                });
        }
#endif
        refresh();
    }

    void rebind(AppContext* context) {
        context_ = context;
        refresh();
    }

    void refresh() {
        auto* widget = review_page();
        if (widget == nullptr) {
            return;
        }
#ifdef PWB_WITH_DATA_INTEGRATION
        if (available()) {
            widget->set_project_bound(true);
            const domain::Json& root =
                context_->projectStore()->document().root();
            const domain::Json reports =
                clr::active_quality_reports_of(root);
            widget->update_state(reports, clr::paleomap_documents_of(root),
                                 export_artifacts_section(root));
            // M3: the 验证 workspace page renders the same reports in its
            // issue table + review hub (one report payload, two views).
            if (auto* validation = shell_->validation_page();
                validation != nullptr) {
                std::vector<domain::Json> report_list;
                if (reports.is_array()) {
                    for (const auto& entry : reports) {
                        if (entry.is_object()) report_list.push_back(entry);
                    }
                }
                validation->update_reports(report_list);
            }
            if (auto* panel = shell_->verify_records_panel();
                panel != nullptr) {
                panel->refresh();
            }
            return;
        }
#endif
        widget->set_project_bound(false);
        widget->update_state(domain::Json::array(), domain::Json::array(),
                             domain::Json::array());
        if (auto* validation = shell_->validation_page();
            validation != nullptr) {
            validation->update_reports({});
        }
        if (auto* panel = shell_->verify_records_panel();
            panel != nullptr) {
            panel->refresh();
        }
    }

private:
#ifdef PWB_WITH_DATA_INTEGRATION
    bool available() const {
        return context_ != nullptr && context_->projectStore() != nullptr;
    }
#else
    bool available() const { return false; }
#endif

    ui_review::qt::ReviewExportPage* review_page() const {
        return shell_ != nullptr ? shell_->review_page() : nullptr;
    }

    static domain::Json export_artifacts_section(const domain::Json& root) {
        const auto it = root.find("export_artifacts");
        if (it != root.end() && it->is_array()) {
            return *it;
        }
        return domain::Json::array();
    }

    AppShell* shell_ = nullptr;
    AppContext* context_ = nullptr;
#ifdef PWB_WITH_DATA_INTEGRATION
    std::unique_ptr<clr::ProjectReviewActions> actions_;
#endif
};

}  // namespace

void install_review_actions(AppShell* shell, AppContext* context,
                         JobCenter* jobs) {
    if (shell == nullptr) {
        return;
    }
    // One binding per shell: a re-install refreshes in place.
    if (auto* existing = shell->findChild<QObject*>(kBindingObjectName)) {
        static_cast<ReviewBinding*>(existing)->rebind(context);
        return;
    }
    auto* binding = new ReviewBinding(shell, context);
    binding->attach(jobs);
}

void notify_project_store_changed(AppShell* shell, AppContext* context) {
    if (shell == nullptr) {
        return;
    }
    if (auto* existing = shell->findChild<QObject*>(kBindingObjectName)) {
        static_cast<ReviewBinding*>(existing)->rebind(context);
        return;
    }
    install_review_actions(shell, context, nullptr);
}

}  // namespace pwb::app::closure_review
