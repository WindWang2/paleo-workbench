// UI-06 — action_header.py :: ActionHeader Qt shell.
//
// Top banner of the 成图审核 page — title, action buttons, rules chips.
// State resolution lives in qc_summary.hpp (resolve_action_header).
#pragma once

#include <QFrame>

#include <pwb/domain/json.hpp>

class QLabel;
class QPushButton;

namespace pwb::ui_pages_data::qt {

class ActionHeader : public QFrame {
    Q_OBJECT
public:
    explicit ActionHeader(QWidget* parent = nullptr);

    // reports: [{linked_map_document_id, rules[]}];
    // docs: [{id, linked_target_horizon}] — same Json seam as the core.
    void update_state(const domain::Json& reports,
                      const domain::Json& docs);

    QPushButton* run_button() { return run_btn_; }
    QPushButton* export_button() { return export_btn_; }
    QPushButton* config_button() { return config_btn_; }
    QPushButton* finalize_button() { return finalize_btn_; }

Q_SIGNALS:
    void run_requested();
    void export_requested();
    void config_requested();
    void finalize_requested();

private:
    QLabel* title_label_;
    QLabel* rules_label_;
    QPushButton* run_btn_;
    QPushButton* config_btn_;
    QPushButton* export_btn_;
    QPushButton* finalize_btn_;
};

}  // namespace pwb::ui_pages_data::qt
