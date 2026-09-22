#include "review_disposition_panel.hpp"

#include <QComboBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QVBoxLayout>

namespace pwb::app {

namespace {

// Display order matches the design vocabulary; ids are the stable Latin
// keys the record sink persists (closure_review::ReviewDisposition).
const struct {
    const char* id;
    const char* label;
} kDispositions[] = {
    {"pending", "待复核"},
    {"approved", "通过"},
    {"rejected", "未通过"},
    {"not_executed", "未执行"},
    {"not_applicable", "不适用"},
    {"outdated", "已过期"},
};

QString severity_text(const QString& severity) {
    if (severity == QLatin1String("error")) return QStringLiteral("未通过（检查）");
    if (severity == QLatin1String("warning")) return QStringLiteral("警告（检查）");
    if (severity == QLatin1String("pass")) return QStringLiteral("通过（检查）");
    return severity.isEmpty() ? QStringLiteral("—") : severity;
}

}  // namespace

ReviewDispositionPanel::ReviewDispositionPanel(QWidget* parent)
    : QWidget(parent) {
    setObjectName(QStringLiteral("ReviewDispositionPanel"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(6, 4, 6, 4);
    layout->setSpacing(4);

    original_verdict_ = new QLabel(this);
    original_verdict_->setObjectName(QStringLiteral("ReviewOriginalVerdict"));
    original_verdict_->setWordWrap(true);
    layout->addWidget(original_verdict_);

    stale_banner_ = new QLabel(
        QStringLiteral("输入版本已变化：本报告已过期，请重跑检查后再复核"), this);
    stale_banner_->setObjectName(QStringLiteral("ReviewStaleBanner"));
    stale_banner_->setStyleSheet(QStringLiteral(
        "QLabel#ReviewStaleBanner { background: #FDECEA; color: #B71C1C; "
        "padding: 4px 8px; border-radius: 2px; }"));
    stale_banner_->setWordWrap(true);
    stale_banner_->hide();
    layout->addWidget(stale_banner_);
    rerun_ = new QPushButton(QStringLiteral("重跑检查"), this);
    rerun_->setObjectName(QStringLiteral("ReviewRerunButton"));
    connect(rerun_, &QPushButton::clicked, this,
            [this] { emit rerun_requested(); });
    layout->addWidget(rerun_, 0, Qt::AlignLeft);
    rerun_->hide();

    auto* disposition_row = new QHBoxLayout;
    disposition_row->addWidget(new QLabel(QStringLiteral("人工复核结论"), this));
    disposition_ = new QComboBox(this);
    disposition_->setObjectName(QStringLiteral("ReviewDispositionCombo"));
    for (const auto& entry : kDispositions) {
        disposition_->addItem(QString::fromUtf8(entry.label),
                              QString::fromLatin1(entry.id));
    }
    disposition_row->addWidget(disposition_, 1);
    layout->addLayout(disposition_row);

    layout->addWidget(new QLabel(QStringLiteral("复核备注（必填）"), this));
    note_ = new QPlainTextEdit(this);
    note_->setObjectName(QStringLiteral("ReviewNoteEdit"));
    note_->setPlaceholderText(QStringLiteral(
        "接受差异必须说明理由；已复核 ≠ 检查通过"));
    note_->setMinimumHeight(64);
    connect(note_, &QPlainTextEdit::textChanged, this,
            [this] { refresh_save_gate(); });
    layout->addWidget(note_);

    save_ = new QPushButton(QStringLiteral("保存复核记录"), this);
    save_->setObjectName(QStringLiteral("ReviewSaveRecord"));
    connect(save_, &QPushButton::clicked, this,
            [this] { save_record(); });
    layout->addWidget(save_, 0, Qt::AlignLeft);

    refresh_save_gate();
}

void ReviewDispositionPanel::set_selected_issue(const QVariantMap& issue) {
    issue_ = issue;
    const QString rule = issue.value(QStringLiteral("rule")).toString();
    const QString message = issue.value(QStringLiteral("message")).toString();
    const QString severity =
        issue.value(QStringLiteral("severity")).toString();
    original_verdict_->setText(QStringLiteral(
        "原检查结论（不因复核改写）：%1\n%2 · %3")
                                   .arg(severity_text(severity), rule,
                                        message));
    // A new selection starts a fresh draft but keeps an existing record
    // visible via set_existing_record.
    note_->clear();
    disposition_->setCurrentIndex(0);
    refresh_save_gate();
}

void ReviewDispositionPanel::set_existing_record(const RecordView& record) {
    if (record.disposition_id.isEmpty()) {
        return;  // no human record yet — 待复核
    }
    const int index =
        disposition_->findData(record.disposition_id);
    if (index >= 0) {
        disposition_->setCurrentIndex(index);
    }
    note_->setPlainText(record.reviewer_note);
    original_verdict_->setText(original_verdict_->text() +
                               QStringLiteral("\n已有复核记录（%1 · %2）：%3")
                                   .arg(record.created_at, record.author,
                                        record.reviewer_note));
    refresh_save_gate();
}

void ReviewDispositionPanel::set_stale(bool stale, const QString& reason) {
    stale_banner_->setVisible(stale);
    rerun_->setVisible(stale);
    if (stale && !reason.isEmpty()) {
        stale_banner_->setText(reason);
    }
}

void ReviewDispositionPanel::set_record_sink(
    std::function<std::vector<std::string>(const Draft&)> sink) {
    sink_ = std::move(sink);
}

void ReviewDispositionPanel::set_now_provider(std::function<QString()> now) {
    now_ = std::move(now);
}

void ReviewDispositionPanel::refresh_save_gate() {
    // 复核备注必填 — the save button is the visible gate; save_record()
    // re-checks so no caller can bypass it.
    const bool has_issue = !issue_.isEmpty();
    const bool note_ok = !note_->toPlainText().trimmed().isEmpty();
    save_->setEnabled(has_issue && note_ok);
    save_->setToolTip(!has_issue
                          ? QStringLiteral("先在问题列表中选择一条问题")
                      : !note_ok ? QStringLiteral("复核备注必填")
                                 : QStringLiteral("保存人工复核记录"));
}

void ReviewDispositionPanel::save_record() {
    if (issue_.isEmpty()) {
        emit status_message(QStringLiteral("请先选择要复核的问题"));
        return;
    }
    Draft draft;
    draft.issue_key = issue_.value(QStringLiteral("key")).toString();
    draft.rule = issue_.value(QStringLiteral("rule")).toString();
    draft.severity = issue_.value(QStringLiteral("severity")).toString();
    draft.disposition_id =
        disposition_->currentData().toString();
    draft.reviewer_note = note_->toPlainText().trimmed();
    if (draft.reviewer_note.isEmpty()) {
        // Mandatory reason — accepting a difference without one is the
        // exact failure mode F:78 forbids.
        emit status_message(QStringLiteral("复核备注必填（接受差异必须说明理由）"));
        refresh_save_gate();
        return;
    }
    if (sink_ == nullptr) {
        emit status_message(QStringLiteral("复核持久化通道未装配"));
        return;
    }
    const std::vector<std::string> problems = sink_(draft);
    if (!problems.empty()) {
        emit status_message(
            QString::fromStdString(problems.front()));
        return;
    }
    emit status_message(QStringLiteral("复核记录已保存（原检查结论未改动）"));
}

}  // namespace pwb::app
