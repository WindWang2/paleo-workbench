// V14-DATA-LINEAGE (P4) — IngestPlanDialog implementation. Widget style
// follows the ui_review dialogs (lineage_explorer_dialog / relink): plain
// QVBoxLayout composition, Chinese button labels, no stylesheet coupling.
#include <pwb/ui_pages_data/qt/ingest_plan_dialog.hpp>

#include <QCheckBox>
#include <QComboBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QPushButton>
#include <QStringList>
#include <QTableWidget>
#include <QTableWidgetItem>
#include <QVBoxLayout>

#include <utility>

namespace pwb::ui_pages_data::qt {
namespace {

// Column layout (index order is load-bearing — sync_row matches it).
enum Column {
    kColInclude = 0,
    kColFile,
    kColType,
    kColRole,
    kColEntity,
    kColDecision,
    kColNote,
    kColCount,
};

QString decision_label(const std::string& decision) {
    if (decision == kPlanDecisionAccept) return QStringLiteral("接受");
    if (decision == kPlanDecisionSkip) return QStringLiteral("跳过");
    if (decision == kPlanDecisionAsNewVersion)
        return QStringLiteral("作为新版本");
    return QStringLiteral("待定");
}

std::string label_decision(const QString& label) {
    if (label == QStringLiteral("接受")) return kPlanDecisionAccept;
    if (label == QStringLiteral("跳过")) return kPlanDecisionSkip;
    if (label == QStringLiteral("作为新版本"))
        return kPlanDecisionAsNewVersion;
    return kPlanDecisionPending;
}

QString entity_text(const PlanItemRow& row) {
    if (row.entity_id.empty() && row.entity_name.empty()) {
        return row.ambiguous ? QStringLiteral("⚠ 歧义")
                             : QStringLiteral("（未解析）");
    }
    QString text = QString::fromStdString(
        row.entity_name.empty() ? row.entity_id : row.entity_name);
    if (row.new_entity) text += QStringLiteral("（新建）");
    return text;
}

QString note_text(const PlanItemRow& row) {
    QString note;
    if (row.duplicate) {
        note += QStringLiteral("重复 → ") +
                QString::fromStdString(row.duplicate_of_version);
    }
    if (!row.notes.empty()) {
        if (!note.isEmpty()) note += QStringLiteral(" · ");
        note += QString::fromStdString(row.notes);
    }
    return note;
}

}  // namespace

IngestPlanDialog::IngestPlanDialog(std::vector<PlanItemRow> rows,
                                   ExecuteFn execute, CancelFn cancel,
                                   QWidget* parent)
    : QDialog(parent),
      model_(std::move(rows)),
      execute_(std::move(execute)),
      cancel_(std::move(cancel)) {
    setWindowTitle(QStringLiteral("导入计划审查 (Ingest Plan)"));
    resize(980, 560);

    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(8);

    table_ = new QTableWidget(this);
    table_->setColumnCount(kColCount);
    table_->setHorizontalScrollMode(QTableWidget::ScrollPerPixel);
    table_->verticalHeader()->hide();
    table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    connect(table_, &QTableWidget::itemChanged, this,
            [this](QTableWidgetItem* item) {
                if (rebuilding_ || item == nullptr ||
                    item->column() != kColInclude) {
                    return;
                }
                const std::size_t index = static_cast<std::size_t>(item->row());
                const PlanItemRow* row = model_.row(index);
                if (row == nullptr) return;
                const bool include = item->checkState() == Qt::Checked;
                if (row->include != include) {
                    model_.toggle_include(index);
                    refresh_view();
                }
            });
    layout->addWidget(table_, 1);

    issues_label_ = new QLabel(this);
    issues_label_->setWordWrap(true);
    issues_label_->setStyleSheet(
        QStringLiteral("color: #b3261e; font-size: 12px;"));
    layout->addWidget(issues_label_);

    auto* buttons = new QHBoxLayout();
    auto* accept_all_btn =
        new QPushButton(QStringLiteral("全部接受"), this);
    auto* skip_all_btn = new QPushButton(QStringLiteral("全部跳过"), this);
    connect(accept_all_btn, &QPushButton::clicked, this,
            &IngestPlanDialog::accept_all);
    connect(skip_all_btn, &QPushButton::clicked, this,
            &IngestPlanDialog::skip_all);
    buttons->addWidget(accept_all_btn);
    buttons->addWidget(skip_all_btn);
    buttons->addStretch(1);

    execute_btn_ = new QPushButton(QStringLiteral("执行导入"), this);
    auto* cancel_btn = new QPushButton(QStringLiteral("取消"), this);
    connect(execute_btn_, &QPushButton::clicked, this,
            &IngestPlanDialog::run_execute);
    connect(cancel_btn, &QPushButton::clicked, this, [this]() {
        if (cancel_) cancel_();
        Q_EMIT cancelled();
        reject();
    });
    buttons->addWidget(execute_btn_);
    buttons->addWidget(cancel_btn);
    layout->addLayout(buttons);

    refresh_view();
}

void IngestPlanDialog::accept_all() {
    model_.set_all_decisions(kPlanDecisionAccept);
    refresh_view();
}

void IngestPlanDialog::skip_all() {
    model_.set_all_decisions(kPlanDecisionSkip);
    refresh_view();
}

void IngestPlanDialog::refresh_view() {
    if (rebuilding_) return;  // cellChanged feedback loop guard
    rebuilding_ = true;

    table_->clearContents();
    table_->setRowCount(static_cast<int>(model_.size()));
    table_->setHorizontalHeaderLabels(
        {QStringLiteral("含入"), QStringLiteral("文件"), QStringLiteral("类型"),
         QStringLiteral("角色"), QStringLiteral("实体"),
         QStringLiteral("决定"), QStringLiteral("说明")});

    for (std::size_t i = 0; i < model_.size(); ++i) {
        sync_row(i);
    }
    table_->resizeColumnsToContents();
    rebuilding_ = false;
    update_issues();
}

void IngestPlanDialog::sync_row(std::size_t index) {
    const PlanItemRow* row = model_.row(index);
    if (row == nullptr) return;
    const int i = static_cast<int>(index);

    // 含入 — checkbox item.
    auto* include_item = new QTableWidgetItem();
    include_item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable |
                           Qt::ItemIsUserCheckable);
    include_item->setCheckState(row->include ? Qt::Checked : Qt::Unchecked);
    table_->setItem(i, kColInclude, include_item);

    // 文件.
    auto* file_item =
        new QTableWidgetItem(QString::fromStdString(row->filename));
    file_item->setToolTip(QString::fromStdString(row->path));
    file_item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
    table_->setItem(i, kColFile, file_item);

    // 类型 (read-only; "" never guessed into something).
    auto* type_item =
        new QTableWidgetItem(QString::fromStdString(row->type));
    type_item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
    table_->setItem(i, kColType, type_item);

    // 角色 — editable within the entity vocabulary.
    auto* role_combo = new QComboBox(table_);
    for (const auto& allowed : row->allowed_roles) {
        role_combo->addItem(QString::fromStdString(allowed));
    }
    if (!row->allowed_roles.empty()) {
        role_combo->setCurrentText(QString::fromStdString(row->role));
    }
    connect(role_combo, &QComboBox::currentTextChanged, this,
            [this, index](const QString& text) {
                if (rebuilding_) return;
                model_.set_role(index, text.toStdString());
                refresh_view();
            });
    table_->setCellWidget(i, kColRole, role_combo);

    // 实体 (read-only proposal).
    auto* entity_item = new QTableWidgetItem(entity_text(*row));
    entity_item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
    entity_item->setToolTip(QString::fromStdString(
        row->entity_type + " / " + row->strategy));
    if (row->primary) {
        entity_item->setText(entity_item->text() + QStringLiteral(" ★主件"));
    }
    table_->setItem(i, kColEntity, entity_item);

    // 决定 — combo over the domain vocabulary.
    auto* decision_combo = new QComboBox(table_);
    decision_combo->addItem(QStringLiteral("待定"));
    decision_combo->addItem(QStringLiteral("接受"));
    decision_combo->addItem(QStringLiteral("跳过"));
    decision_combo->addItem(QStringLiteral("作为新版本"));
    decision_combo->setCurrentText(decision_label(row->decision));
    connect(decision_combo, &QComboBox::currentTextChanged, this,
            [this, index](const QString& text) {
                if (rebuilding_) return;
                model_.set_decision(index, label_decision(text));
                refresh_view();
            });
    table_->setCellWidget(i, kColDecision, decision_combo);

    // 说明 (duplicate + plan note, read-only).
    auto* note_item = new QTableWidgetItem(note_text(*row));
    note_item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
    table_->setItem(i, kColNote, note_item);
}

void IngestPlanDialog::update_issues() {
    const auto issues = model_.validation();
    if (issues.empty()) {
        const auto summary = model_.summary();
        issues_label_->setStyleSheet(
            QStringLiteral("color: #1b6e3f; font-size: 12px;"));
        issues_label_->setText(
            QStringLiteral("共 %1 项 · 接受 %2 · 跳过 %3 · 重复 %4")
                .arg(summary.total)
                .arg(summary.accepted)
                .arg(summary.skipped)
                .arg(summary.duplicates));
        execute_btn_->setEnabled(true);
        return;
    }
    issues_label_->setStyleSheet(
        QStringLiteral("color: #b3261e; font-size: 12px;"));
    QStringList lines;
    for (const auto& issue : issues) lines << QString::fromStdString(issue);
    issues_label_->setText(lines.join(QStringLiteral("\n")));
}

bool IngestPlanDialog::run_execute() {
    const auto issues = model_.validation();
    if (!issues.empty()) {
        update_issues();
        return false;  // honest refusal — never execute an invalid review
    }
    if (!execute_) {
        Q_EMIT executed(QString());
        Q_EMIT accepted();
        accept();
        return true;
    }
    QString summary;
    try {
        summary = QString::fromStdString(execute_(model_.rows()));
    } catch (const std::exception& error) {
        issues_label_->setStyleSheet(
            QStringLiteral("color: #b3261e; font-size: 12px;"));
        issues_label_->setText(
            QStringLiteral("执行失败: ") + QString::fromUtf8(error.what()));
        return false;
    }
    Q_EMIT executed(summary);
    Q_EMIT accepted();
    accept();
    return true;
}

}  // namespace pwb::ui_pages_data::qt
