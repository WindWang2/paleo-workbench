#pragma once

// M5 — 问题级人工复核面板 (design F:72-80):
//
//   * the ORIGINAL check verdict (pass/warning/error) is shown unchanged
//     beside the human disposition — 复核 ≠ 通过, a review never rewrites
//     the check outcome;
//   * six-state disposition vocabulary (通过/未通过/待复核/未执行/不适用/
//     已过期);
//   * the reviewer note is MANDATORY — accepting a difference without a
//     reason is refused at the panel AND at the record sink;
//   * the stale banner (输入版本已变化) prompts an explicit re-run.
//
// The panel is backend-agnostic: records leave through the injected sink
// (the M5 install binds the closure_review document persistence), so the
// widget builds anywhere the validation page builds.

#include <functional>
#include <vector>

#include <QVariantMap>
#include <QWidget>

class QComboBox;
class QLabel;
class QPlainTextEdit;
class QPushButton;

namespace pwb::app {

class ReviewDispositionPanel : public QWidget {
    Q_OBJECT
public:
    // One saved-record view for the selected issue (empty = 待复核).
    struct RecordView {
        QString disposition_id;  // approved|rejected|pending|not_executed|not_applicable|outdated
        QString reviewer_note;
        QString created_at;
        QString author;
    };

    explicit ReviewDispositionPanel(QWidget* parent = nullptr);

    // Selection link from QcIssueTable / InteractiveQCHub (M3 channel).
    void set_selected_issue(const QVariantMap& issue);
    // Existing human record for the selected issue (from the report).
    void set_existing_record(const RecordView& record);
    // F:76 staleness banner.
    void set_stale(bool stale, const QString& reason);

    // Sink: persists one record; returns problems (empty = saved). The
    // note-empty refusal happens HERE too — a hostile caller must not
    // bypass the mandatory reason.
    struct Draft {
        QString issue_key;
        QString rule;
        QString severity;
        QString disposition_id;
        QString reviewer_note;
    };
    void set_record_sink(
        std::function<std::vector<std::string>(const Draft&)> sink);
    void set_now_provider(std::function<QString()> now);

    // Command/test surface.
    QComboBox* disposition_combo() const { return disposition_; }
    QPlainTextEdit* note_editor() const { return note_; }
    QPushButton* save_button() const { return save_; }

public slots:
    void save_record();  // invoked by verify.save_record

signals:
    void status_message(const QString& message);
    void rerun_requested();

private:
    void refresh_save_gate();

    QVariantMap issue_;
    QComboBox* disposition_ = nullptr;
    QPlainTextEdit* note_ = nullptr;
    QPushButton* save_ = nullptr;
    QLabel* original_verdict_ = nullptr;
    QLabel* stale_banner_ = nullptr;
    QPushButton* rerun_ = nullptr;
    std::function<std::vector<std::string>(const Draft&)> sink_;
    std::function<QString()> now_;
};

}  // namespace pwb::app
