#include <pwb/ui_seqviz/qt/sequence_panels.hpp>

#include <QAbstractItemView>
#include <QHeaderView>
#include <QLineEdit>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>

#include <pwb/ui_seqviz/page_tokens.hpp>

namespace pwb::ui_seqviz::qt {

namespace {

QLabel* field_label(const QString& text, QWidget* parent) {
    auto* label = new QLabel(text, parent);
    label->setObjectName("WorkFieldLabel");
    return label;
}

QLabel* field_value(const QString& text, QWidget* parent) {
    auto* label = new QLabel(text, parent);
    label->setObjectName("WorkFieldValue");
    return label;
}

void add_value_row(QVBoxLayout* layout, const QString& label_text,
                   QLabel** value_out, const QString& value_text,
                   QWidget* parent) {
    layout->addWidget(field_label(label_text, parent));
    *value_out = field_value(value_text, parent);
    layout->addWidget(*value_out);
}

}  // namespace

// ---------------------------------------------------------------------------
// SequenceBoundaryTable (QFrame + inner table — Python widget parity)
// ---------------------------------------------------------------------------

SequenceBoundaryTable::SequenceBoundaryTable(QWidget* parent)
    : QFrame(parent) {
    setObjectName("SequenceBoundaryTable");
    auto* layout = new QVBoxLayout(this);
    const int pad = tokens::PANEL_PADDING;
    layout->setContentsMargins(pad, pad, pad, pad);
    layout->setSpacing(tokens::SPACE_2);

    title_label_ = new QLabel("层序界面清单", this);
    title_label_->setObjectName("MapDockTitle");
    layout->addWidget(title_label_);

    empty_label_ =
        new QLabel("未配置层序界面（双击行可设为目标层位）", this);
    empty_label_->setObjectName("EmptyStateLabel");
    layout->addWidget(empty_label_);

    table_ = new QTableWidget(0, 3, this);
    table_->setHorizontalHeaderLabels({"界面", "目标层位", "说明"});
    table_->verticalHeader()->setVisible(false);
    table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table_->setAlternatingRowColors(true);
    table_->horizontalHeader()->setStretchLastSection(true);
    layout->addWidget(table_, 1);

    connect(table_, &QTableWidget::itemDoubleClicked, this,
            [this](QTableWidgetItem* item) {
                if (item == nullptr) {
                    return;
                }
                QTableWidgetItem* name_item =
                    table_->item(item->row(), 0);
                if (name_item != nullptr &&
                    !name_item->text().trimmed().isEmpty()) {
                    emit boundary_activated(name_item->text().trimmed());
                }
            });
}

void SequenceBoundaryTable::update_state(
    const StratigraphySlice& stratigraphy) {
    const auto rows = sequence_boundary_rows(stratigraphy);
    table_->setRowCount(static_cast<int>(rows.size()));
    empty_label_->setHidden(!rows.empty());
    int row_index = 0;
    for (const auto& row : rows) {
        table_->setItem(
            row_index, 0,
            new QTableWidgetItem(QString::fromStdString(row.name)));
        table_->setItem(
            row_index, 1,
            new QTableWidgetItem(QString::fromStdString(row.target)));
        table_->setItem(
            row_index, 2,
            new QTableWidgetItem(QString::fromStdString(row.note)));
        ++row_index;
    }
}

// ---------------------------------------------------------------------------
// SequenceTargetPanel
// ---------------------------------------------------------------------------

SequenceTargetPanel::SequenceTargetPanel(QWidget* parent) : QFrame(parent) {
    setObjectName("SequenceTargetPanel");
    setMinimumWidth(240);
    setMaximumWidth(static_cast<int>(240 * 1.6));

    auto* layout = new QVBoxLayout(this);
    const int pad = tokens::PANEL_PADDING;
    layout->setContentsMargins(pad, pad, pad, pad);
    layout->setSpacing(tokens::SPACE_2);

    auto* title = new QLabel("层序格架设置", this);
    title->setObjectName("MapDockTitle");
    layout->addWidget(title);

    layout->addWidget(field_label("目标层位", this));
    target_combo_ = new QComboBox(this);
    target_combo_->setEditable(true);
    target_combo_->setInsertPolicy(QComboBox::NoInsert);
    target_combo_->setObjectName("SequenceTargetCombo");
    target_combo_->lineEdit()->setPlaceholderText("未设置");
    layout->addWidget(target_combo_);

    add_value_row(layout, "解释版本", &version_value_, "v1", this);

    layout->addWidget(field_label("体系域方案", this));
    scheme_combo_ = new QComboBox(this);
    scheme_combo_->addItem("LST/TST/HST");
    for (const auto& scheme : tokens::sequence_schemes()) {
        scheme_combo_->addItem(QString::fromStdString(scheme));
    }
    layout->addWidget(scheme_combo_);

    add_value_row(layout, "适用范围", &scope_value_, "0 口井 / 0 条测线",
                  this);
    layout->addStretch(1);

    // Commit-only target emission: returnPressed AND activated can both
    // fire for one Enter on an editable combo — dedupe on committed text.
    connect(target_combo_->lineEdit(), &QLineEdit::returnPressed, this,
            &SequenceTargetPanel::on_target_committed);
    connect(target_combo_, &QComboBox::activated, this,
            [this](int) { on_target_committed(); });
    connect(scheme_combo_, &QComboBox::currentTextChanged, this,
            [this](const QString& text) {
                if (!suppress_) {
                    emit scheme_changed(text.trimmed());
                }
            });
}

QString SequenceTargetPanel::current_target() const {
    return target_combo_->currentText().trimmed();
}

QString SequenceTargetPanel::target_horizon_text() const {
    const QString text = current_target();
    return text.isEmpty() ? QStringLiteral("未设置") : text;
}

QString SequenceTargetPanel::current_scheme() const {
    return scheme_combo_->currentText().trimmed();
}

void SequenceTargetPanel::on_target_committed() {
    if (suppress_) {
        return;
    }
    const QString text = current_target();
    if (tracker_.should_emit(text.toStdString())) {
        emit target_changed(text);
    }
}

void SequenceTargetPanel::update_state(
    const StratigraphySlice& stratigraphy) {
    const SequenceTargetView view = sequence_target_view(stratigraphy);
    suppress_ = true;
    target_combo_->clear();
    for (const auto& option : view.options) {
        target_combo_->addItem(QString::fromStdString(option));
    }
    if (view.selected_index >= 0) {
        target_combo_->setCurrentIndex(view.selected_index);
    } else {
        target_combo_->setCurrentIndex(-1);
        target_combo_->setEditText(QString::fromStdString(view.edit_text));
    }
    if (view.selected_index >= 0 && !view.edit_text.empty()) {
        target_combo_->setEditText(QString::fromStdString(view.edit_text));
    }
    version_value_->setText(QString::fromStdString(view.version_text));
    const QString scheme = QString::fromStdString(view.scheme_text);
    if (scheme_combo_->findText(scheme) < 0) {
        scheme_combo_->addItem(scheme);
    }
    scheme_combo_->setCurrentText(scheme);
    scope_value_->setText(QString::fromStdString(view.scope_text));
    tracker_.resync(view.last_committed_target);
    suppress_ = false;
}

// ---------------------------------------------------------------------------
// SequenceSchemeSummary
// ---------------------------------------------------------------------------

SequenceSchemeSummary::SequenceSchemeSummary(QWidget* parent)
    : QFrame(parent) {
    setObjectName("PanelCard");
    setMinimumWidth(220);
    setMaximumWidth(static_cast<int>(220 * 1.6));

    auto* layout = new QVBoxLayout(this);
    const int pad = tokens::PANEL_PADDING;
    layout->setContentsMargins(pad, pad, pad, pad);
    layout->setSpacing(tokens::SPACE_2);

    auto* title = new QLabel("层序方案摘要", this);
    title->setObjectName("MapDockTitle");
    layout->addWidget(title);

    add_value_row(layout, "当前方案", &scheme_value_, "LST/TST/HST", this);
    add_value_row(layout, "层序界面", &boundary_count_value_, "0 个", this);
    add_value_row(layout, "体系域", &systems_tract_value_, "LST / TST / HST",
                  this);
    add_value_row(layout, "绑定状态", &status_value_, "未保存", this);

    layout->addStretch();
    auto* save_btn = new QPushButton("保存层序方案", this);
    save_btn->setObjectName("PrimaryButton");
    connect(save_btn, &QPushButton::clicked, this,
            &SequenceSchemeSummary::save_requested);
    layout->addWidget(save_btn);
}

void SequenceSchemeSummary::update_state(
    const StratigraphySlice& stratigraphy) {
    const auto view = sequence_scheme_summary_view(stratigraphy);
    scheme_value_->setText(QString::fromStdString(view.scheme_text));
    boundary_count_value_->setText(
        QString::fromStdString(view.boundary_count_text));
    systems_tract_value_->setText(
        QString::fromStdString(view.systems_tract_text));
    status_value_->setText(QString::fromStdString(view.status_text));
}

void SequenceSchemeSummary::set_bind_status(const QString& text) {
    status_value_->setText(text);
}

}  // namespace pwb::ui_seqviz::qt
