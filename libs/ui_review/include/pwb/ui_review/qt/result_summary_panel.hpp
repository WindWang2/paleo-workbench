#pragma once

// UI-11 — result_summary.py Qt shell: right-hand QC summary (pass /
// warning / error counts, advisory line, exported-artifact list). The
// counts/rows come from UI-06's ui_pages_data::summarize_qc — never
// re-derived here.

#include "pwb/domain/json.hpp"

#include <QFrame>

#include <vector>

class QLabel;
class QVBoxLayout;
class QWidget;

namespace pwb::ui_review::qt {

class ResultSummaryPanel : public QFrame {
    Q_OBJECT
public:
    explicit ResultSummaryPanel(QWidget* parent = nullptr);

    // update_state(reports, artifacts) parity — reports[0] rules drive
    // the counts; artifacts render as "• {format} — {output_path}" rows.
    void update_state(const domain::Json& reports,
                      const domain::Json& artifacts);

    QLabel* pass_label() const { return pass_label_; }
    QLabel* warning_label() const { return warning_label_; }
    QLabel* error_label() const { return error_label_; }
    QLabel* advisory_label() const { return advisory_label_; }
    const std::vector<QLabel*>& export_rows() const {
        return export_rows_;
    }

private:
    void clear_export();

    QLabel* pass_label_ = nullptr;
    QLabel* warning_label_ = nullptr;
    QLabel* error_label_ = nullptr;
    QLabel* advisory_label_ = nullptr;
    QWidget* export_container_ = nullptr;
    QVBoxLayout* export_layout_ = nullptr;
    std::vector<QLabel*> export_rows_;
};

}  // namespace pwb::ui_review::qt
