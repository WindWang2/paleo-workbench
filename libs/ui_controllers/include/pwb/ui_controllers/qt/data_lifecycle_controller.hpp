#pragma once

// UI-14 — DataLifecycleController Qt shell
// (data_lifecycle_controller.py surface parity).
//
// Owns DataLifecycleCore + the catalog-copy and verify JobOwnerRunners
// (page._catalog_copy_job / page._verify_job parity) and binds the page,
// catalog-runtime, service and dialog seams. The trivial dialogs map onto
// stock Qt widgets here (tag input → QInputDialog, delivery path →
// QFileDialog, open-url → QDesktopServices); the composite dialogs
// (new-version / promote / trash-impact preview) stay injected seams the
// integration adapter binds to the ported widgets.

#include <QObject>

#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <vector>

#include <pwb/ui_controllers/qt/job_owner_runner.hpp>
#include <pwb/ui_controllers/data_lifecycle.hpp>

class QWidget;

namespace pwb::ui_shell {
class OperationRegistry;
}

namespace pwb::ui_controllers::qt {


class DataLifecycleController : public QObject {
    Q_OBJECT
public:
    // `operations` may be nullptr (the verify booking then stays local).
    // The catalog-copy/verify jobs run through JobOwnerRunners over the
    // QGIS task bridge (process-shared gate when installed).
    explicit DataLifecycleController(
        ui_shell::OperationRegistry* operations = nullptr,
        QObject* parent = nullptr);
    ~DataLifecycleController() override;

    // The seam bags the integration adapter fills (bind before first
    // core() use).
    DataPageApi& page_api() { return page_; }
    CatalogRuntimeApi& catalog_api() { return catalog_; }
    DataLifecycleServiceApi& services() { return services_; }
    LifecycleDialogApi& dialogs() { return dialogs_; }

    DataLifecycleCore& core();
    void rebind() { core_.reset(); }

    // Bind the stock-Qt dialog implementations against `parent`
    // (tag input / delivery path / open-url only — composite dialogs
    // remain the integrator's seams).
    void bind_dialogs(QWidget* parent);

    // The runners the Python page exposes (tests + drain inspect them).
    UiJobRunner* catalog_job() { return catalog_job_.get(); }
    UiJobRunner* verify_job() { return verify_job_.get(); }

public slots:
    // The page-facing slots (data_page wire-up parity — the integrator
    // connects page signals to these).
    void remove_assets(const std::vector<AssetHandle>& items) {
        core().remove_assets(items);
    }
    void restore_selected_asset() { core().restore_selected_asset(); }
    void rescan_selected_asset() { core().rescan_selected_asset(); }
    void create_derived_copy(const AssetHandle& item) {
        core().create_derived_copy(item);
    }
    void materialize_asset(const AssetHandle& item) {
        core().materialize_asset(item);
    }
    void new_version_from_asset(const AssetHandle& item) {
        core().new_version_from_asset(item);
    }
    void promote_asset(const AssetHandle& item) {
        core().promote_asset(item);
    }
    void deliver_asset(const AssetHandle& item) {
        core().deliver_asset(item);
    }
    void handle_tag_added(const AssetHandle& item,
                          const QString& tag_name) {
        core().handle_tag_added(item, tag_name.toStdString());
    }
    void handle_tag_removed(const AssetHandle& item,
                            const QString& tag_name) {
        core().handle_tag_removed(item, tag_name.toStdString());
    }
    void prompt_add_tag_to_assets(const std::vector<AssetHandle>& items) {
        core().prompt_add_tag_to_assets(items);
    }
    void prompt_remove_tag_from_assets(
        const std::vector<AssetHandle>& items) {
        core().prompt_remove_tag_from_assets(items);
    }
    void verify_assets(const std::vector<AssetHandle>& items) {
        core().verify_assets(items);
    }

private:
    ui_shell::OperationRegistry* operations_;
    std::unique_ptr<JobOwnerRunner> catalog_job_;
    std::unique_ptr<JobOwnerRunner> verify_job_;
    std::unique_ptr<DataLifecycleCore> core_;
    DataPageApi page_;
    CatalogRuntimeApi catalog_;
    DataLifecycleServiceApi services_;
    LifecycleDialogApi dialogs_;
};

}  // namespace pwb::ui_controllers::qt
