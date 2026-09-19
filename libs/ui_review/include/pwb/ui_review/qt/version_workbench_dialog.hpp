#pragma once

// UI-11 — version_workbench_dialog.py Qt shell: single-asset version
// timeline (newest first) + selection-driven detail + gated lifecycle
// actions (promote/copy to OUTPUT, open location, compare, trash,
// restore). All reads/mutations go through ICatalogApi; committed
// versions stay immutable. Promote runs off the GUI thread via JobOwner
// (payload copy + SHA-256 can be unbounded); the timeline reloads after
// every successful mutation and emits versions_changed.

#include "pwb/ui_review/catalog_api.hpp"
#include "pwb/ui_review/version_view.hpp"

#include <QDialog>

#include <functional>
#include <memory>
#include <vector>

namespace pwb::job {
class JobScheduler;
}  // namespace pwb::job
namespace pwb::job::qtbridge {
class JobOwner;
}  // namespace pwb::job::qtbridge
namespace pwb::ui_widgets {
class ObjectTableModel;
class StableSelection;
}  // namespace pwb::ui_widgets

class QLabel;
class QPlainTextEdit;
class QPushButton;
class QTableView;
class QTableWidget;

namespace pwb::ui_review::qt {

// _VersionCompareDialog parity — strictly read-only two-version diff.
class VersionCompareDialog : public QDialog {
    Q_OBJECT
public:
    VersionCompareDialog(QWidget* parent,
                         const catalog::DataVersion& newer,
                         const catalog::DataVersion& older);

    QTableWidget* table() const { return table_; }

private:
    QTableWidget* table_ = nullptr;
};

class VersionWorkbenchDialog : public QDialog {
    Q_OBJECT
public:
    VersionWorkbenchDialog(
        QWidget* parent,
        std::function<ICatalogApi*()> service_provider,
        QString asset_id,
        std::shared_ptr<job::JobScheduler> scheduler = nullptr);
    ~VersionWorkbenchDialog() override;

    // reload_versions parity — re-read asset + versions (cache nothing),
    // restore the stable selection, resync detail + action gates.
    void reload_versions();

    // Python attribute surface.
    QLabel* header_label() const { return header_label_; }
    QLabel* count_label() const { return count_label_; }
    QTableView* versions_table() const { return versions_table_; }
    ui_widgets::ObjectTableModel* versions_model() const {
        return versions_model_;
    }
    QPushButton* promote_btn() const { return promote_btn_; }
    QPushButton* open_btn() const { return open_btn_; }
    QPushButton* compare_btn() const { return compare_btn_; }
    QPushButton* trash_btn() const { return trash_btn_; }
    QPushButton* restore_btn() const { return restore_btn_; }
    QLabel* detail_title_label() const { return detail_title_label_; }
    QLabel* detail_parents_label() const { return detail_parents_label_; }
    QLabel* detail_run_label() const { return detail_run_label_; }
    QPlainTextEdit* detail_run_params() const { return detail_run_params_; }
    QLabel* detail_path_label() const { return detail_path_label_; }
    QLabel* detail_resolved_label() const { return detail_resolved_label_; }
    QPlainTextEdit* detail_meta_text() const { return detail_meta_text_; }

signals:
    void versions_changed();

private:
    ICatalogApi* service() const;
    void apply_timeline_rows();
    std::vector<int> selected_rows() const;
    const catalog::DataVersion* single_selection() const;
    void on_selection_changed();
    void set_actions_enabled(bool enabled);
    void sync_action_buttons();
    void show_detail(const catalog::DataVersion* version);

    bool confirm(const QString& title, const QString& text);
    void finish_mutation();
    void on_promote_clicked();
    void on_open_clicked();
    void on_compare_clicked();
    void on_trash_clicked();
    void on_restore_clicked();

    std::function<ICatalogApi*()> service_provider_;
    QString asset_id_;
    std::shared_ptr<job::JobScheduler> scheduler_;
    std::unique_ptr<job::qtbridge::JobOwner> promote_job_;
    std::unique_ptr<ui_widgets::StableSelection> timeline_selection_;

    std::vector<catalog::DataVersion> versions_;
    std::string current_version_id_;

    QLabel* header_label_ = nullptr;
    QLabel* count_label_ = nullptr;
    ui_widgets::ObjectTableModel* versions_model_ = nullptr;
    QTableView* versions_table_ = nullptr;
    QLabel* detail_title_label_ = nullptr;
    QLabel* detail_parents_label_ = nullptr;
    QLabel* detail_run_label_ = nullptr;
    QPlainTextEdit* detail_run_params_ = nullptr;
    QLabel* detail_path_label_ = nullptr;
    QLabel* detail_resolved_label_ = nullptr;
    QPlainTextEdit* detail_meta_text_ = nullptr;
    QPushButton* promote_btn_ = nullptr;
    QPushButton* open_btn_ = nullptr;
    QPushButton* compare_btn_ = nullptr;
    QPushButton* trash_btn_ = nullptr;
    QPushButton* restore_btn_ = nullptr;
};

}  // namespace pwb::ui_review::qt
