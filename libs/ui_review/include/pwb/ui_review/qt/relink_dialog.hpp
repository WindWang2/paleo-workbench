#pragma once

// UI-11 — relink_dialog.py Qt shell: missing-source list + per-row /
// folder-batch relink (fail-closed identity proof). Scan AND relink run
// on separate PwbTaskOwners (one task per role — never torn down and reused
// mid-session; shutdown only on close). The dialog never touches managed
// payloads and never mutates the catalog beyond explicit relink writes.

#include "pwb/ui_review/catalog_api.hpp"

#include <QDialog>

#include <functional>
#include <memory>
#include <vector>

namespace pwb::qgis_processing {
class PwbTaskOwner;
}  // namespace pwb::qgis_processing
namespace pwb::ui_widgets {
class ObjectTableModel;
class PwbEmptyState;
class PwbLoadingState;
class StableSelection;
}  // namespace pwb::ui_widgets

class QCloseEvent;
class QLabel;
class QPushButton;
class QResizeEvent;
class QTableView;

namespace pwb::ui_review::qt {

class RelinkSourcesDialog : public QDialog {
    Q_OBJECT
public:
    RelinkSourcesDialog(
        QWidget* parent,
        std::function<ICatalogApi*()> service_provider);
    ~RelinkSourcesDialog() override;

    // start_scan parity — stat-only missing-source scan on a worker.
    void start_scan();

    // Python attribute surface.
    QLabel* summary_label() const { return summary_label_; }
    QLabel* detail_label() const { return detail_label_; }
    QTableView* table() const { return table_; }
    ui_widgets::ObjectTableModel* model() const { return model_; }
    ui_widgets::PwbLoadingState* progress() const { return progress_; }
    QPushButton* relink_btn() const { return relink_btn_; }
    QPushButton* folder_btn() const { return folder_btn_; }
    QPushButton* rescan_btn() const { return rescan_btn_; }
    bool busy() const { return busy_; }

signals:
    void sources_relinked(int count);

protected:
    void closeEvent(QCloseEvent* event) override;
    void reject() override;
    void resizeEvent(QResizeEvent* event) override;

private:
    void cancel_running();
    void sync_buttons();
    const catalog::MissingSource* selected_entry() const;
    void relink_selected();
    void relink_folder();
    void apply_relinks(
        const std::vector<std::pair<const catalog::MissingSource*,
                                    std::filesystem::path>>& pending);
    void update_empty_state();

    std::function<ICatalogApi*()> service_provider_;
    std::unique_ptr<pwb::qgis_processing::PwbTaskOwner> scan_job_;
    std::unique_ptr<pwb::qgis_processing::PwbTaskOwner> relink_job_;
    // Explicit busy flag instead of job->is_running() — the thread can
    // still be draining when a queued result slot fires.
    bool busy_ = false;
    std::vector<catalog::MissingSource> entries_;

    QLabel* summary_label_ = nullptr;
    QLabel* detail_label_ = nullptr;
    ui_widgets::ObjectTableModel* model_ = nullptr;
    QTableView* table_ = nullptr;
    ui_widgets::PwbEmptyState* empty_state_ = nullptr;
    ui_widgets::PwbLoadingState* progress_ = nullptr;
    QPushButton* relink_btn_ = nullptr;
    QPushButton* folder_btn_ = nullptr;
    QPushButton* rescan_btn_ = nullptr;
};

}  // namespace pwb::ui_review::qt
