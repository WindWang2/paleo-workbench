#pragma once

// UI-09 — PredictionEvidencePanel Qt shell (prediction_evidence_panel.py).
// Right-hand evidence/action summary: output-nature / source / horizon /
// facies-count / class-distribution fields, evidence list, diagnostic log
// (copyable, pre-redacted upstream), export-format combo + actions. All
// label math comes from output_labels.hpp — the panel never re-derives
// the honesty rules.

#include <string>

#include <QFrame>
#include <QString>

#include <pwb/ui_wellseis/slices.hpp>

class QComboBox;
class QLabel;
class QListWidget;
class QPlainTextEdit;
class QProgressBar;
class QPushButton;
class QVBoxLayout;

namespace pwb::ui_wellseis::qt {

class PredictionEvidencePanel : public QFrame {
    Q_OBJECT
public:
    explicit PredictionEvidencePanel(QWidget* parent = nullptr);

    // update_state parity — task may be nullptr; selected_source marks the
    // "showing a picked source well" variant (数据管理井数据).
    void update_state(const PredictionTaskSlice* task, bool bound_las,
                      bool selected_source = false);
    void set_actions_enabled(bool can_export, bool can_send);
    // #850-7 parity — run/demo disabled while an inference runs.
    void set_inferring(bool busy);
    void set_status(const QString& text);
    void set_diagnostic_log(const QString& text);
    [[nodiscard]] QString status_text() const;

signals:
    void run_requested();
    void demo_requested();
    void send_requested();
    void export_requested(const QString& format_label);  // PNG|SVG|PDF

private:
    QLabel* add_value(QVBoxLayout* layout, const QString& label_text,
                      const QString& value_text);

    QLabel* mock_value_ = nullptr;
    QLabel* source_value_ = nullptr;
    QLabel* horizon_value_ = nullptr;
    QLabel* facies_count_value_ = nullptr;
    QLabel* class_distribution_value_ = nullptr;
    QLabel* status_value_ = nullptr;
    QLabel* waiting_label_ = nullptr;
    QProgressBar* waiting_indicator_ = nullptr;
    QListWidget* evidence_list_ = nullptr;
    QPlainTextEdit* diagnostic_log_ = nullptr;
    QPushButton* copy_diagnostic_btn_ = nullptr;
    QComboBox* export_format_combo_ = nullptr;
    QPushButton* export_btn_ = nullptr;
    QPushButton* run_btn_ = nullptr;
    QPushButton* demo_btn_ = nullptr;
    QPushButton* send_btn_ = nullptr;
    bool inferring_ = false;
};

}  // namespace pwb::ui_wellseis::qt
