#pragma once

// UI-11 — catalog_health_dialog.py Qt shell: audit statistics + issues
// table + 快速/深度检查 workers (PwbTaskOwner on the QGIS task bridge,
// cooperative cancel) + the relink_requested signal. The audit itself is
// never mutating.

#include "pwb/ui_review/catalog_api.hpp"

#include <QDialog>

#include <functional>
#include <memory>

class QLabel;
class QPushButton;
class QTableView;

namespace pwb::qgis_processing { class PwbTaskOwner; }
namespace pwb::ui_widgets {
class ObjectTableModel;
class PwbEmptyState;
class PwbLoadingState;
}  // namespace pwb::ui_widgets

namespace pwb::ui_review::qt {

class CatalogHealthDialog : public QDialog {
    Q_OBJECT
public:
    // service_provider mirrors the Python kwarg: a callable returning
    // the bound ICatalogApi (nullptr = 未连接数据目录).
    explicit CatalogHealthDialog(
        QWidget* parent,
        std::function<ICatalogApi*()> service_provider);
    ~CatalogHealthDialog() override;

    // run_audit(deep=False) — starts the worker audit (no-op while busy
    // or unbound).
    void run_audit(bool deep = false);
    // update_report(report) — render an AuditReport (also called by the
    // worker completion).
    void update_report(const catalog::AuditReport& report);

    // Python attribute surface.
    QLabel* summary_label() const { return summary_label_; }
    QTableView* issues_table() const { return issues_table_; }
    ui_widgets::ObjectTableModel* model() const { return model_; }
    QPushButton* refresh_btn() const { return refresh_btn_; }
    QPushButton* deep_btn() const { return deep_btn_; }
    QPushButton* relink_btn() const { return relink_btn_; }
    ui_widgets::PwbLoadingState* progress() const { return progress_; }

signals:
    // D9: host opens RelinkSourcesDialog.
    void relink_requested();

public slots:
    void reject() override;

protected:
    void closeEvent(QCloseEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

private:
    void cancel_running_audit();
    void set_running(bool running);
    void update_empty_state();

    std::function<ICatalogApi*()> service_provider_;
    std::unique_ptr<pwb::qgis_processing::PwbTaskOwner> job_;

    QLabel* summary_label_ = nullptr;
    ui_widgets::ObjectTableModel* model_ = nullptr;
    QTableView* issues_table_ = nullptr;
    ui_widgets::PwbEmptyState* empty_state_ = nullptr;
    ui_widgets::PwbLoadingState* progress_ = nullptr;
    QPushButton* refresh_btn_ = nullptr;
    QPushButton* deep_btn_ = nullptr;
    QPushButton* relink_btn_ = nullptr;
};

}  // namespace pwb::ui_review::qt
