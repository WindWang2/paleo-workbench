#include "closure_review_install.hpp"

#include <QObject>

#include <pwb/closure_review/project_review_actions.hpp>
#include <pwb/domain/errors.hpp>
#include <pwb/domain/json.hpp>
#include <pwb/ui_review/qt/review_export_page.hpp>

#include <filesystem>
#include <memory>
#include <utility>

#include "app_context.hpp"
#include "app_shell.hpp"

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
    ReviewBinding(AppShell* shell, AppContext* context)
        : QObject(shell), shell_(shell), context_(context) {
#ifdef PWB_WITH_DATA_INTEGRATION
        closure_review::ProjectReviewActions::Delegates d;
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
        actions_ =
            std::make_unique<closure_review::ProjectReviewActions>(
                std::move(d));
#endif  // PWB_WITH_DATA_INTEGRATION
    }

    void attach() {
        setObjectName(QString::fromLatin1(kBindingObjectName));
        auto* page = page();
        if (page == nullptr) {
            return;
        }
#ifdef PWB_WITH_DATA_INTEGRATION
        // The binding outlives the page's provider calls (QObject child of
        // the shell); the page additionally guards with project_bound_, so
        // an absent store keeps its honest 未绑定工程 state.
        ui_review::IReviewActions* exposed = actions_.get();
        page->set_actions_provider(
            [exposed]() -> ui_review::IReviewActions* { return exposed; });
#endif
        refresh();
    }

    void rebind(AppContext* context) {
        context_ = context;
        refresh();
    }

    void refresh() {
        auto* page = page();
        if (page == nullptr) {
            return;
        }
        page->set_project_bound(available());
#ifdef PWB_WITH_DATA_INTEGRATION
        if (available()) {
            const domain::Json& root =
                context_->projectStore()->document().root();
            page->update_state(closure_review::active_quality_reports_of(root),
                               closure_review::paleomap_documents_of(root),
                               export_artifacts_section(root));
            return;
        }
#endif
        page->update_state(domain::Json::array(), domain::Json::array(),
                           domain::Json::array());
    }

private:
#ifdef PWB_WITH_DATA_INTEGRATION
    bool available() const {
        return context_ != nullptr && context_->projectStore() != nullptr;
    }
#else
    bool available() const { return false; }
#endif

    ui_review::qt::ReviewExportPage* page() const {
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
    std::unique_ptr<closure_review::ProjectReviewActions> actions_;
#endif
};

}  // namespace

void install_review_actions(AppShell* shell, AppContext* context) {
    if (shell == nullptr) {
        return;
    }
    // One binding per shell: a re-install refreshes in place.
    if (auto* existing = shell->findChild<QObject*>(kBindingObjectName)) {
        static_cast<ReviewBinding*>(existing)->rebind(context);
        return;
    }
    auto* binding = new ReviewBinding(shell, context);
    binding->attach();
}

void notify_project_store_changed(AppShell* shell, AppContext* context) {
    if (shell == nullptr) {
        return;
    }
    if (auto* existing = shell->findChild<QObject*>(kBindingObjectName)) {
        static_cast<ReviewBinding*>(existing)->rebind(context);
        return;
    }
    install_review_actions(shell, context);
}

}  // namespace pwb::app::closure_review
