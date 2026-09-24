#pragma once

// UI-10 — Qt Widgets shells for the factor pages:
//   * factor_task_panel.py        → FactorTaskPanel (QFrame + task rows)
//   * factor_preview_grid.py      → FactorPreviewGrid (cards grid)
//   * create_factor_map_dialog.py → CreateFactorMapDialog (QDialog)
//
// View data comes from the Qt-free factor_state core; worker execution
// goes through job::JobSpec adapted onto the QGIS task bridge
// (PwbTaskOwner + pwb::qgis_processing::start_job_spec) over
// run_factor_map_job (UI-04 worker semantics, injected service seam).

#include <QDialog>
#include <QFrame>
#include <QLabel>

#include <memory>
#include <pwb/qgis_processing/task_bridge.hpp>
#include <pwb/ui_seqviz/factor_state.hpp>
#include <vector>

class QCheckBox;
class QComboBox;
class QProgressBar;
class QPushButton;
class QScrollArea;
class QSpinBox;
class QVBoxLayout;
class QGridLayout;

namespace pwb::qgis_processing {
struct CompatJobOutcome;  // job_compat.hpp (implementation-side seam)
}

namespace pwb::ui_seqviz::qt {

// ---------------------------------------------------------------------------
// factor_task_panel.py — left sidebar: horizon label + method combo +
// generate/contour-draft buttons + scrollable task rows + prepared summary.
// ---------------------------------------------------------------------------
class FactorTaskPanel : public QFrame {
    Q_OBJECT
public:
    // Row — one task entry (name · sub-label · status badge).
    class Row : public QWidget {
    public:
        explicit Row(const FactorTaskRecord& task, QWidget* parent = nullptr);
        QLabel* name_label() const { return name_label_; }
        QLabel* sub_label() const { return sub_label_; }

    private:
        QLabel* name_label_ = nullptr;
        QLabel* sub_label_ = nullptr;
    };

    explicit FactorTaskPanel(QWidget* parent = nullptr);

    // update_state parity: horizon label, common-method seeding (never
    // stomps a user pick — #894-2), row rebuild, prepared summary.
    void update_state(const std::vector<FactorTaskRecord>& tasks);
    QString selected_method() const;
    bool method_user_selected() const { return method_user_selected_; }
    int row_count() const { return row_count_; }
    // 08-line closure (PreparationPage install): read-only widget handles
    // so the page can gate enablement and render progress summaries —
    // additive accessors, no behavior change.
    QComboBox* method_combo() const { return method_combo_; }
    QPushButton* generate_btn() const { return generate_btn_; }
    QPushButton* contour_draft_btn() const { return contour_draft_btn_; }
    QLabel* summary_label() const { return summary_label_; }

signals:
    void generate_requested(const QString& method);
    void contour_draft_requested();

private:
    void clear_rows();
    void sync_method_tooltip(const QString& text);

    QLabel* horizon_label_ = nullptr;
    QComboBox* method_combo_ = nullptr;
    QPushButton* generate_btn_ = nullptr;
    QPushButton* contour_draft_btn_ = nullptr;
    QScrollArea* scroll_ = nullptr;
    QWidget* task_container_ = nullptr;
    QVBoxLayout* task_layout_ = nullptr;
    QLabel* summary_label_ = nullptr;
    bool method_user_selected_ = false;
    int row_count_ = 0;
};

// FactorPreviewCard — one completed-task card: title / range / R² (honest
// fallback) / dedup warning; left mouse release emits clicked. (Python
// nests this inside FactorPreviewGrid; moc requires a top-level class.)
class FactorPreviewCard : public QFrame {
    Q_OBJECT
public:
    explicit FactorPreviewCard(
        std::shared_ptr<const FactorTaskRecord> task,
        QWidget* parent = nullptr);
    std::shared_ptr<const FactorTaskRecord> task() const { return task_; }

signals:
    void clicked(std::shared_ptr<const FactorTaskRecord> task);

protected:
    void mouseReleaseEvent(QMouseEvent* event) override;

private:
    std::shared_ptr<const FactorTaskRecord> task_;
};

// ---------------------------------------------------------------------------
// factor_preview_grid.py — center grid of completed-task preview cards.
// ---------------------------------------------------------------------------
class FactorPreviewGrid : public QWidget {
    Q_OBJECT
public:
    explicit FactorPreviewGrid(QWidget* parent = nullptr);

    // update_state parity: completed-only filter, header line, card grid
    // (2 columns), empty-state label.
    void update_state(const std::vector<FactorTaskRecord>& tasks);
    int card_count() const { return card_count_; }
    QLabel* header_label() const { return header_label_; }

signals:
    void card_clicked(std::shared_ptr<const FactorTaskRecord> task);

private:
    void clear_grid();

    QLabel* header_label_ = nullptr;
    QScrollArea* scroll_ = nullptr;
    QWidget* grid_container_ = nullptr;
    QGridLayout* grid_layout_ = nullptr;
    QLabel* empty_label_ = nullptr;
    int card_count_ = 0;
};

// ---------------------------------------------------------------------------
// create_factor_map_dialog.py — modal factor-map creation dialog over the
// injected FactorMapServiceFn + a PwbTaskOwner (OwnedWorkerJob parity).
// ---------------------------------------------------------------------------
class CreateFactorMapDialog : public QDialog {
    Q_OBJECT
public:
    explicit CreateFactorMapDialog(QWidget* parent = nullptr);

    // The service seam (GeologicalMappingService.create_factor_map
    // replacement). Required before start_job().
    void set_service(FactorMapServiceFn service);
    // Seed the horizon combo: [stratigraphy.target_horizon?] + defaults,
    // deduped (dict.fromkeys parity).
    void set_stratigraphy_target(const QString& target_horizon);

    // The params dict _on_create_clicked assembles.
    FactorMapParams create_params() const;
    // _on_create_clicked — disabled while a job runs; returns false when a
    // job is already running or no service is configured.
    bool start_job();
    bool is_running() const { return job_owner_.is_running(); }

    // Host-typed payload of the created map document (std::any; empty
    // until a job finishes).
    const std::any& created_map_doc() const { return created_map_doc_; }

    QComboBox* factor_combo() const { return factor_combo_; }
    QComboBox* horizon_combo() const { return horizon_combo_; }
    QComboBox* method_combo() const { return method_combo_; }
    QSpinBox* grid_size_spin() const { return grid_size_spin_; }
    QComboBox* ramp_combo() const { return ramp_combo_; }

signals:
    void map_created(const pwb::ui_seqviz::FactorMapOutcome& outcome);
    // QMessageBox.information/critical seams — the host decides whether to
    // show a dialog; the shell never blocks.
    void info_requested(const QString& title, const QString& message);
    void error_requested(const QString& title, const QString& message);

protected:
    void closeEvent(QCloseEvent* event) override;

public slots:
    void reject() override;

private:
    void on_job_finished(
        const pwb::qgis_processing::CompatJobOutcome& outcome);

    FactorMapServiceFn service_;
    pwb::qgis_processing::PwbTaskOwner job_owner_;
    std::any created_map_doc_;

    QComboBox* factor_combo_ = nullptr;
    QComboBox* horizon_combo_ = nullptr;
    QComboBox* method_combo_ = nullptr;
    QSpinBox* grid_size_spin_ = nullptr;
    QComboBox* ramp_combo_ = nullptr;
    QCheckBox* chk_grid_ = nullptr;
    QCheckBox* chk_contour_ = nullptr;
    QCheckBox* chk_wells_ = nullptr;
    QCheckBox* chk_polygons_ = nullptr;
    QProgressBar* progress_bar_ = nullptr;
    QPushButton* btn_cancel_ = nullptr;
    QPushButton* btn_create_ = nullptr;
};

}  // namespace pwb::ui_seqviz::qt

Q_DECLARE_METATYPE(pwb::ui_seqviz::FactorMapOutcome)
