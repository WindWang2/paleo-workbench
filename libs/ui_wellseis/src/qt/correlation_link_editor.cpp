#include <pwb/ui_wellseis/qt/correlation_link_editor.hpp>

#include <QComboBox>
#include <QDialogButtonBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QTableView>
#include <QVBoxLayout>

#include <pwb/ui_wellseis/correlation.hpp>
#include <pwb/ui_wellseis/qt/object_table_model.hpp>

namespace pwb::ui_wellseis::qt {

namespace {

QString qs(const std::string& text) {
    return QString::fromUtf8(text.data(), static_cast<int>(text.size()));
}

}  // namespace

CorrelationLinkEditor::CorrelationLinkEditor(
    CorrelationDraftSlice& draft, QWidget* parent,
    CorrelationEditorHooks hooks)
    : QDialog(parent), draft_(draft), hooks_(std::move(hooks)) {
    setWindowTitle(QStringLiteral("相关链接与顶点属性编辑"));
    resize(760, 520);
    auto* root = new QVBoxLayout(this);

    link_model_ = new StringTableModel(this);
    link_model_->set_columns(
        {{QStringLiteral("marker"), QStringLiteral("层位")},
         {QStringLiteral("pair"), QStringLiteral("井 A → 井 B")},
         {QStringLiteral("method"), QStringLiteral("方法")},
         {QStringLiteral("adjacent"), QStringLiteral("邻接")},
         {QStringLiteral("notes"), QStringLiteral("备注")}});
    top_model_ = new StringTableModel(this);
    top_model_->set_columns(
        {{QStringLiteral("well"), QStringLiteral("井")},
         {QStringLiteral("marker"), QStringLiteral("层位")},
         {QStringLiteral("depth"), QStringLiteral("深度")},
         {QStringLiteral("method"), QStringLiteral("方法")},
         {QStringLiteral("confidence"), QStringLiteral("置信度")}});

    root->addWidget(
        new QLabel(QStringLiteral("井间相关链接（保存后进入解释版本）"),
                   this));
    link_table_ = new QTableView(this);
    link_table_->setModel(link_model_);
    link_table_->horizontalHeader()->setSectionResizeMode(
        QHeaderView::Stretch);
    link_table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    link_table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    link_table_->setSelectionMode(QAbstractItemView::SingleSelection);
    root->addWidget(link_table_, 2);

    auto* link_buttons = new QHBoxLayout();
    auto* add_btn = new QPushButton(QStringLiteral("新增链接…"), this);
    connect(add_btn, &QPushButton::clicked, this,
            &CorrelationLinkEditor::add_link);
    auto* remove_btn = new QPushButton(QStringLiteral("删除链接"), this);
    connect(remove_btn, &QPushButton::clicked, this,
            &CorrelationLinkEditor::remove_link);
    auto* method_btn =
        new QPushButton(QStringLiteral("改方法/备注…"), this);
    connect(method_btn, &QPushButton::clicked, this,
            &CorrelationLinkEditor::edit_link);
    link_buttons->addWidget(add_btn);
    link_buttons->addWidget(remove_btn);
    link_buttons->addWidget(method_btn);
    link_buttons->addStretch(1);
    root->addLayout(link_buttons);

    root->addWidget(new QLabel(
        QStringLiteral("顶点属性（方法 / 置信度 / 状态 / 备注）"), this));
    top_table_ = new QTableView(this);
    top_table_->setModel(top_model_);
    top_table_->horizontalHeader()->setSectionResizeMode(
        QHeaderView::Stretch);
    top_table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    top_table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    top_table_->setSelectionMode(QAbstractItemView::SingleSelection);
    root->addWidget(top_table_, 2);

    auto* top_buttons = new QHBoxLayout();
    auto* top_btn =
        new QPushButton(QStringLiteral("编辑顶点属性…"), this);
    connect(top_btn, &QPushButton::clicked, this,
            &CorrelationLinkEditor::edit_top);
    top_buttons->addWidget(top_btn);
    top_buttons->addStretch(1);
    root->addLayout(top_buttons);

    auto* buttons =
        new QDialogButtonBox(QDialogButtonBox::Close, this);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);
    connect(buttons, &QDialogButtonBox::clicked, this,
            [this, buttons](QAbstractButton* button) {
                if (buttons->standardButton(button) ==
                    QDialogButtonBox::Close) {
                    reject();
                }
            });
    root->addWidget(buttons);

    rebuild_tables();
}

int CorrelationLinkEditor::generation() const {
    return draft_.generation;
}

void CorrelationLinkEditor::rebuild_tables() {
    // The id->top snapshot is rebuilt per refresh — link row resolution
    // reads through correlation_link_rows (R3-M3 parity).
    tops_snapshot_ = draft_.tops;

    const auto links = correlation_link_rows(draft_);
    const auto tops = correlation_top_rows(draft_);

    const auto link_keys = capture_selected_keys(
        link_table_->selectionModel(), link_model_);
    const auto link_current =
        current_key(link_table_->selectionModel(), link_model_);
    std::vector<std::string> link_ids;
    std::vector<std::vector<QString>> link_rows;
    link_ids.reserve(links.size());
    link_rows.reserve(links.size());
    for (const CorrelationLinkRow& row : links) {
        link_ids.push_back(row.id);
        link_rows.push_back({qs(row.marker), qs(row.pair_text),
                             qs(row.method_label), qs(row.adjacent_text),
                             qs(row.notes)});
    }
    link_model_->set_rows(link_ids, link_rows);
    restore_selected_keys(link_table_->selectionModel(), link_model_,
                          link_keys, link_current);

    const auto top_keys =
        capture_selected_keys(top_table_->selectionModel(), top_model_);
    const auto top_current =
        current_key(top_table_->selectionModel(), top_model_);
    std::vector<std::string> top_ids;
    std::vector<std::vector<QString>> top_rows;
    top_ids.reserve(tops.size());
    top_rows.reserve(tops.size());
    for (const CorrelationTopRow& row : tops) {
        top_ids.push_back(row.id);
        top_rows.push_back({qs(row.well_name), qs(row.marker),
                            qs(row.depth_text), qs(row.method_label),
                            qs(row.confidence_text)});
    }
    top_model_->set_rows(top_ids, top_rows);
    restore_selected_keys(top_table_->selectionModel(), top_model_,
                          top_keys, top_current);
}

std::string CorrelationLinkEditor::selected_link_id() const {
    const auto key = link_model_->key_for_index(
        link_table_->currentIndex());
    return key.value_or("");
}

std::string CorrelationLinkEditor::selected_top_id() const {
    const auto key =
        top_model_->key_for_index(top_table_->currentIndex());
    return key.value_or("");
}

void CorrelationLinkEditor::add_link() {
    const auto choices = correlation_top_choices(draft_);
    if (choices.size() < 2) {
        QMessageBox::information(this, QStringLiteral("新增链接"),
                                 QStringLiteral("至少需要两个顶点。"));
        return;
    }
    QStringList labels;
    for (const CorrelationTopChoice& choice : choices) {
        labels << qs(choice.label);
    }
    const auto pick_from = [this, &labels](const QString& label,
                                           int current) {
        if (hooks_.pick_item) {
            return hooks_.pick_item(QStringLiteral("新增链接"), label,
                                    labels, current);
        }
        bool ok = false;
        const QString item = QInputDialog::getItem(
            this, QStringLiteral("新增链接"), label, labels, current,
            /*editable=*/false, &ok);
        return std::make_pair(item, ok);
    };
    const auto [a_label, ok_a] = pick_from(QStringLiteral("顶点 A"), 0);
    if (!ok_a) {
        return;
    }
    const auto [b_label, ok_b] = pick_from(QStringLiteral("顶点 B"), 1);
    if (!ok_b) {
        return;
    }
    const auto find_top = [&choices](const QString& label)
        -> const CorrelationTopChoice* {
        for (const auto& choice : choices) {
            if (qs(choice.label) == label) {
                return &choice;
            }
        }
        return nullptr;
    };
    const CorrelationTopChoice* top_a = find_top(a_label);
    const CorrelationTopChoice* top_b = find_top(b_label);
    if (top_a == nullptr || top_b == nullptr) {
        return;
    }
    const std::string new_id =
        hooks_.new_link_id
            ? hooks_.new_link_id(draft_)
            : "link:" + std::to_string(draft_.links.size());
    try {
        if (!correlation_add_manual_link(draft_, new_id, top_a->top_id,
                                         top_b->top_id,
                                         /*adjacent_only=*/false, {})) {
            return;
        }
    } catch (const std::exception& exc) {
        QMessageBox::warning(this, QStringLiteral("新增链接"),
                             qs(exc.what()));
        return;
    }
    rebuild_tables();
}

void CorrelationLinkEditor::remove_link() {
    const std::string link_id = selected_link_id();
    if (link_id.empty()) {
        return;
    }
    correlation_remove_link(draft_, link_id);
    rebuild_tables();
}

void CorrelationLinkEditor::edit_link() {
    const std::string link_id = selected_link_id();
    if (link_id.empty()) {
        return;
    }
    const CorrelationLinkSlice* link = nullptr;
    for (const auto& candidate : draft_.links) {
        if (candidate.id == link_id) {
            link = &candidate;
            break;
        }
    }
    if (link == nullptr) {
        return;
    }
    QDialog dialog(this);
    dialog.setWindowTitle(QStringLiteral("链接属性"));
    auto* form = new QFormLayout(&dialog);
    auto* method_combo = new QComboBox(&dialog);
    for (const std::string& method :
         {"MANUAL", "DTW_ASSISTED", "CURVE_SHAPE_ASSISTED", "IMPORTED"}) {
        method_combo->addItem(qs(correlation_method_label(method)),
                              qs(method));
    }
    method_combo->setCurrentText(qs(correlation_method_label(link->method)));
    auto* notes_edit = new QLineEdit(qs(link->notes), &dialog);
    form->addRow(QStringLiteral("方法"), method_combo);
    form->addRow(QStringLiteral("备注"), notes_edit);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog,
            &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog,
            &QDialog::reject);
    form->addRow(buttons);
    if (dialog.exec() != QDialog::Accepted) {
        return;
    }
    correlation_edit_link(draft_, link_id,
                          method_combo->currentData()
                              .toString()
                              .toStdString(),
                          notes_edit->text().trimmed().toStdString());
    rebuild_tables();
}

void CorrelationLinkEditor::edit_top() {
    const std::string top_id = selected_top_id();
    if (top_id.empty()) {
        return;
    }
    const CorrelationTopSlice* top = nullptr;
    for (const auto& candidate : tops_snapshot_) {
        if (candidate.id == top_id) {
            top = &candidate;
            break;
        }
    }
    if (top == nullptr) {
        return;
    }
    QDialog dialog(this);
    dialog.setWindowTitle(QStringLiteral("顶点属性 · %1 %2")
                              .arg(qs(top->well_name), qs(top->marker)));
    auto* form = new QFormLayout(&dialog);
    auto* method_combo = new QComboBox(&dialog);
    for (const std::string& method :
         {"MANUAL", "DTW_ASSISTED", "CURVE_SHAPE_ASSISTED", "IMPORTED"}) {
        method_combo->addItem(qs(correlation_method_label(method)),
                              qs(method));
    }
    method_combo->setCurrentText(qs(correlation_method_label(top->method)));
    auto* confidence_edit = new QLineEdit(qs(top->confidence), &dialog);
    confidence_edit->setPlaceholderText(
        QStringLiteral("自由文本（如 高 / 中 / 0.8）"));
    auto* status_combo = new QComboBox(&dialog);
    for (const std::string& status : kCorrelationStatuses) {
        status_combo->addItem(qs(status));
    }
    status_combo->setCurrentText(qs(top->status));
    auto* notes_edit = new QLineEdit(qs(top->notes), &dialog);
    form->addRow(QStringLiteral("方法"), method_combo);
    form->addRow(QStringLiteral("置信度"), confidence_edit);
    form->addRow(QStringLiteral("状态"), status_combo);
    form->addRow(QStringLiteral("备注"), notes_edit);
    auto* buttons = new QDialogButtonBox(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, &dialog);
    connect(buttons, &QDialogButtonBox::accepted, &dialog,
            &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog,
            &QDialog::reject);
    form->addRow(buttons);
    if (dialog.exec() != QDialog::Accepted) {
        return;
    }
    correlation_edit_top(draft_, top_id,
                         method_combo->currentData()
                             .toString()
                             .toStdString(),
                         confidence_edit->text().trimmed().toStdString(),
                         status_combo->currentText().toStdString(),
                         notes_edit->text().trimmed().toStdString());
    rebuild_tables();
}

void run_link_editor(QWidget* parent, CorrelationDraftSlice& draft,
                     CorrelationEditorHooks hooks,
                     const std::function<void()>& on_changed) {
    const int generation_before = draft.generation;
    CorrelationLinkEditor dialog(draft, parent, std::move(hooks));
    dialog.exec();
    if (draft.generation != generation_before && on_changed) {
        on_changed();
    }
}

}  // namespace pwb::ui_wellseis::qt
