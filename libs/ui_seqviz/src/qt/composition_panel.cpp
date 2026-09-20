#include <pwb/ui_seqviz/qt/composition_panel.hpp>

#include <QAction>
#include <QApplication>
#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QListWidgetItem>
#include <QMenu>
#include <QMessageBox>
#include <QPainter>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QSplitter>
#include <QSvgRenderer>
#include <QTableWidget>
#include <QTableWidgetItem>
#include <QTextEdit>
#include <QTimer>
#include <QToolButton>
#include <QVBoxLayout>

#include <algorithm>

#include <pwb/mapping_document/document_io.hpp>
#include <pwb/ui_seqviz/composition_state.hpp>

namespace pwb::ui_seqviz::qt {
namespace {

constexpr int kStaticFormRows = 5;  // title + x + y + w + h

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

// f"{value:g}" — Python's %g default precision (6 significant digits),
// used for the series-table 数值 cells.
QString py_g(double value) {
    return QString::number(value, 'g', 6);
}

}  // namespace

// ---------------------------------------------------------------------------

CompositionPanel::CompositionPanel(QWidget* parent) : QFrame(parent) {
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(6, 6, 6, 6);
    root->setSpacing(4);

    // -- row 1: template combo + 模板新建 ----------------------------------
    auto* top = new QHBoxLayout();
    top->addWidget(new QLabel("模板:"));
    template_combo_ = new QComboBox(this);
    template_combo_->setMinimumWidth(220);
    top->addWidget(template_combo_, 1);
    new_from_template_btn_ = new QPushButton("模板新建", this);
    top->addWidget(new_from_template_btn_);
    root->addLayout(top);

    // -- row 2: history + save/load ---------------------------------------
    auto* hist = new QHBoxLayout();
    undo_btn_ = new QToolButton(this);
    undo_btn_->setText("↶ 撤销");
    redo_btn_ = new QToolButton(this);
    redo_btn_->setText("↷ 重做");
    hist->addWidget(undo_btn_);
    hist->addWidget(redo_btn_);
    hist->addStretch(1);
    save_btn_ = new QToolButton(this);
    save_btn_->setText("保存 JSON");
    load_btn_ = new QToolButton(this);
    load_btn_->setText("载入 JSON");
    hist->addWidget(save_btn_);
    hist->addWidget(load_btn_);
    root->addLayout(hist);

    // -- splitter: left element list / center preview / right form --------
    auto* split = new QSplitter(Qt::Horizontal, this);

    auto* left_box = new QWidget(split);
    auto* left_lay = new QVBoxLayout(left_box);
    left_lay->setContentsMargins(0, 0, 0, 0);
    element_list_ = new QListWidget(left_box);
    element_list_->setContextMenuPolicy(Qt::CustomContextMenu);
    left_lay->addWidget(element_list_, 1);
    auto* btn_row = new QHBoxLayout();
    add_btn_ = new QToolButton(left_box);
    add_btn_->setText("＋组件");
    add_btn_->setPopupMode(QToolButton::InstantPopup);
    add_btn_->setMenu(new QMenu(add_btn_));
    delete_btn_ = new QToolButton(left_box);
    delete_btn_->setText("删除");
    duplicate_btn_ = new QToolButton(left_box);
    duplicate_btn_->setText("复制");
    front_btn_ = new QToolButton(left_box);
    front_btn_->setText("置顶");
    back_btn_ = new QToolButton(left_box);
    back_btn_->setText("置底");
    for (auto* b : {add_btn_, delete_btn_, duplicate_btn_, front_btn_,
                    back_btn_}) {
        btn_row->addWidget(b);
    }
    left_lay->addLayout(btn_row);
    split->addWidget(left_box);

    auto* center = new QScrollArea(split);
    center->setWidgetResizable(true);
    preview_label_ = new QLabel(center);
    preview_label_->setAlignment(Qt::AlignCenter);
    preview_label_->setMinimumSize(320, 240);
    preview_label_->setText("尚无组图");
    center->setWidget(preview_label_);
    split->addWidget(center);

    auto* right_box = new QWidget(split);
    auto* right_lay = new QVBoxLayout(right_box);
    right_lay->setContentsMargins(0, 0, 0, 0);
    auto* prop_box = new QGroupBox("属性", right_box);
    auto* prop_lay = new QVBoxLayout(prop_box);
    property_form_ = new QFormLayout();
    property_form_->setFieldGrowthPolicy(
        QFormLayout::AllNonFixedFieldsGrow);
    title_edit_ = new QLineEdit(prop_box);
    property_form_->addRow("标题", title_edit_);
    auto make_spin = [prop_box](double lo, double hi) {
        auto* s = new QDoubleSpinBox(prop_box);
        s->setRange(lo, hi);
        s->setDecimals(1);
        s->setSingleStep(1.0);
        s->setSuffix(" mm");
        return s;
    };
    x_spin_ = make_spin(-1e4, 1e4);
    y_spin_ = make_spin(-1e4, 1e4);
    w_spin_ = make_spin(0.1, 1e4);
    h_spin_ = make_spin(0.1, 1e4);
    property_form_->addRow("x (mm)", x_spin_);
    property_form_->addRow("y (mm)", y_spin_);
    property_form_->addRow("宽 (mm)", w_spin_);
    property_form_->addRow("高 (mm)", h_spin_);
    lock_hint_ = new QLabel("元素已锁定", prop_box);
    lock_hint_->setStyleSheet("color: #c66;");
    property_form_->addRow(lock_hint_);
    prop_lay->addLayout(property_form_);
    right_lay->addWidget(prop_box);
    right_lay->addStretch(1);
    split->addWidget(right_box);
    split->setSizes({220, 520, 300});
    root->addWidget(split, 1);

    // -- row 4: export ------------------------------------------------------
    auto* export_row = new QHBoxLayout();
    export_row->addWidget(new QLabel("导出:"));
    export_combo_ = new QComboBox(this);
    export_combo_->addItems({"pdf", "png", "svg"});
    export_row->addWidget(export_combo_, 1);
    export_row->addWidget(new QLabel("DPI:"));
    dpi_spin_ = new QSpinBox(this);
    dpi_spin_->setRange(72, 1200);
    dpi_spin_->setValue(300);
    export_row->addWidget(dpi_spin_);
    export_btn_ = new QPushButton("导出…", this);
    export_row->addWidget(export_btn_);
    export_row->addStretch(1);
    root->addLayout(export_row);

    // -- wiring -------------------------------------------------------------
    connect(new_from_template_btn_, &QPushButton::clicked, this,
            &CompositionPanel::new_from_template);
    connect(undo_btn_, &QToolButton::clicked, this,
            &CompositionPanel::undo);
    connect(redo_btn_, &QToolButton::clicked, this,
            &CompositionPanel::redo);
    connect(save_btn_, &QToolButton::clicked, this,
            &CompositionPanel::save_json);
    connect(load_btn_, &QToolButton::clicked, this,
            &CompositionPanel::load_json);
    connect(element_list_, &QListWidget::currentRowChanged, this,
            &CompositionPanel::on_element_selected);
    connect(element_list_, &QListWidget::customContextMenuRequested,
            this, &CompositionPanel::on_element_menu);
    connect(delete_btn_, &QToolButton::clicked, this,
            &CompositionPanel::delete_selected);
    connect(duplicate_btn_, &QToolButton::clicked, this,
            &CompositionPanel::duplicate_selected);
    connect(front_btn_, &QToolButton::clicked, this,
            [this] { reorder("front"); });
    connect(back_btn_, &QToolButton::clicked, this,
            [this] { reorder("back"); });
    connect(title_edit_, &QLineEdit::editingFinished, this,
            &CompositionPanel::apply_title);
    for (auto* s : {x_spin_, y_spin_, w_spin_, h_spin_}) {
        connect(s, &QDoubleSpinBox::editingFinished, this, [this, s] {
            if (suppress_geometry_signals_) return;
            const std::string field = s == x_spin_   ? "x"
                                      : s == y_spin_ ? "y"
                                      : s == w_spin_ ? "w"
                                                     : "h";
            apply_geometry(field, s->value());
        });
    }
    connect(export_btn_, &QPushButton::clicked, this,
            &CompositionPanel::do_export);
    title_edit_->installEventFilter(this);

    build_add_menu();
    refresh_all();
}

// -- injected seams -----------------------------------------------------------

void CompositionPanel::set_factory(
    mapping_document::CompositionFactory factory) {
    factory_ = std::move(factory);
}

void CompositionPanel::set_registry(CompositionRegistrySeams seams) {
    seams_ = std::move(seams);
    build_add_menu();
    // Rebuild the template combo from TEMPLATE_LIBRARY order.
    template_combo_->clear();
    if (seams_.template_library) {
        for (const auto& t : seams_.template_library()) {
            template_combo_->addItem(qstr(t.label),
                                     qstr(t.template_id));
            const int idx = template_combo_->count() - 1;
            if (!t.description.empty()) {
                template_combo_->setItemData(
                    idx, qstr(t.description), Qt::ToolTipRole);
            }
        }
    }
    // Python __init__ creates the default-template document right away;
    // with injected seams the same observable state is "first registry
    // install opens the current template" (never a fabricated document).
    if (document_ == nullptr && seams_.instantiate_template) {
        const QString tid = template_combo_->currentData().toString();
        if (!tid.isEmpty()) {
            try {
                set_document(
                    seams_.instantiate_template(tid.toStdString()));
            } catch (const std::exception&) {
                // Empty-panel state stays honest (no template resolved).
            }
        }
    }
}

void CompositionPanel::set_document(const Composition& doc) {
    document_ = std::make_unique<Composition>(doc);
    session_ = std::make_unique<CompositionEditSession>(*document_,
                                                        factory_);
    schema_dirty_.clear();
    title_edit_->setText(qstr(document_->title));
    refresh_all();
    emit composition_changed(session_->revision());
}

Composition* CompositionPanel::document() { return document_.get(); }

long long CompositionPanel::apply_bindings(
    const domain::Json& binding_context) {
    if (!document_) return 0;
    const long long resolved =
        mapping_document::bind_template(*document_, binding_context);
    refresh_preview();
    refresh_list();
    return resolved;
}

bool CompositionPanel::set_main_map(const std::any& map_document) {
    if (!session_ || !seams_.main_map_bind_fn) return false;
    const bool ok = seams_.main_map_bind_fn(*session_, *document_,
                                            map_document);
    if (ok) {
        refresh_preview();
        emit composition_changed(session_->revision());
    }
    return ok;
}

// BEGIN V14-COMPILATION-PUBLISH — headless export (do_export without the
// file dialog): the same seam, the same honest refusal.
CompositionExportResult CompositionPanel::export_to(const std::string& path,
                                                    const std::string& format,
                                                    double dpi) {
    CompositionExportResult result;
    if (!document_) {
        result.message = "no composition document";
        return result;
    }
    if (!seams_.export_fn) {
        result.message = "no composition export engine wired";
        return result;
    }
    result = seams_.export_fn(*document_, path, format, dpi);
    if (result.ok) {
        register_catalog_export(result.path.empty() ? path : result.path);
        emit composition_exported(
            qstr(result.path.empty() ? path : result.path));
    }
    return result;
}
// END V14-COMPILATION-PUBLISH

// -- template row -------------------------------------------------------------

void CompositionPanel::build_add_menu() {
    auto* menu = add_btn_ ? add_btn_->menu() : nullptr;
    if (!menu) return;
    menu->clear();
    if (!seams_.element_menu) return;
    for (const auto& group : seams_.element_menu()) {
        if (group.specs.empty()) continue;
        auto* sub = menu->addMenu(qstr(group.category_label));
        for (const auto& [type, label] : group.specs) {
            sub->addAction(qstr(label), this,
                           [this, type] { add_element(type); });
        }
    }
}

void CompositionPanel::new_from_template() {
    const QString tid = template_combo_->currentData().toString();
    if (tid.isEmpty() || !seams_.instantiate_template) return;
    try {
        set_document(seams_.instantiate_template(tid.toStdString()));
    } catch (const std::exception& exc) {
        QMessageBox::warning(this, "模板新建失败", qstr(exc.what()));
    }
}

// -- element ops ----------------------------------------------------------------

std::string CompositionPanel::selected_element_id() const {
    auto* item = element_list_->currentItem();
    return item ? item->data(Qt::UserRole).toString().toStdString()
                : std::string{};
}

mapping_document::ComposerElement* CompositionPanel::selected_element() {
    if (!document_) return nullptr;
    const std::string eid = selected_element_id();
    if (eid.empty()) return nullptr;
    return mapping_document::find_element(*document_, eid);
}

void CompositionPanel::add_element(const std::string& element_type) {
    if (!session_) return;
    try {
        const ComposerElement created =
            session_->add_element(element_type);
        refresh_list();
        select_element(created.id);
        refresh_preview();
        emit composition_changed(session_->revision());
    } catch (const mapping_document::ComposerError&) {
        // Registry/refusal path — the injected spec provider decides.
    }
}

void CompositionPanel::delete_selected() {
    if (!session_) return;
    const std::string eid = selected_element_id();
    if (eid.empty()) return;
    try {
        session_->remove_element(eid);
    } catch (const mapping_document::ComposerError&) {
        return;
    }
    refresh_list();
    refresh_property_editor();
    refresh_preview();
    emit composition_changed(session_->revision());
}

void CompositionPanel::duplicate_selected() {
    if (!session_) return;
    const std::string eid = selected_element_id();
    if (eid.empty()) return;
    std::optional<ComposerElement> copy;
    try {
        copy = session_->duplicate_element(eid);
    } catch (const mapping_document::ComposerError&) {
        return;  // locked → refused (Python catches ComposerError)
    }
    if (!copy) return;  // missing → no command (Python None)
    refresh_list();
    select_element(copy->id);
    refresh_preview();
    emit composition_changed(session_->revision());
}

void CompositionPanel::toggle_lock(const std::string& element_id) {
    if (!session_ || !document_) return;
    auto* el = mapping_document::find_element(*document_, element_id);
    if (!el) return;
    try {
        session_->set_locked(element_id, !el->locked);
    } catch (const mapping_document::ComposerError&) {
        return;
    }
    refresh_list();
    refresh_property_editor();
    emit composition_changed(session_->revision());
}

void CompositionPanel::reorder(const std::string& mode) {
    if (!session_) return;
    const std::string eid = selected_element_id();
    if (eid.empty()) return;
    try {
        if (mode == "front") {
            session_->bring_to_front(eid);
        } else {
            session_->send_to_back(eid);
        }
    } catch (const mapping_document::ComposerError&) {
        return;
    }
    refresh_list();
    select_element(eid);
    refresh_preview();
    emit composition_changed(session_->revision());
}

void CompositionPanel::undo() {
    if (!session_ || !session_->undo()) return;
    refresh_all();
    emit composition_changed(session_->revision());
}

void CompositionPanel::redo() {
    if (!session_ || !session_->redo()) return;
    refresh_all();
    emit composition_changed(session_->revision());
}

// -- property edits ---------------------------------------------------------------

void CompositionPanel::apply_title() {
    if (!session_ || !document_) return;
    apply_composition_title(*session_, *document_,
                            title_edit_->text().toStdString());
    refresh_preview();
    emit composition_changed(session_->revision());
}

void CompositionPanel::apply_geometry(const std::string& field,
                                      double value) {
    if (!session_ || !document_) return;
    const std::string eid = selected_element_id();
    if (eid.empty()) return;
    if (!apply_element_geometry(*session_, *document_, eid, field,
                                value)) {
        return;  // locked/missing → no-op (Python parity)
    }
    refresh_preview();
    emit composition_changed(session_->revision());
}

void CompositionPanel::on_schema_value_changed(const std::string& name,
                                               const domain::Json& value) {
    if (suppress_schema_signals_ || !session_) return;
    auto* el = selected_element();
    if (!el) return;
    try {
        session_->configure_element(el->id,
                                    domain::Json{{name, value}});
    } catch (const mapping_document::ComposerError&) {
        return;
    }
    // Discard the pending-dirty marker — the committed value wins.
    schema_dirty_.erase(name);
    // A chart_type change rebuilds the schema editor (Python schedules it
    // via QTimer.singleShot so the combo signal finishes first).
    if (name == "chart_type") {
        QTimer::singleShot(0, this,
                           &CompositionPanel::refresh_property_editor);
    }
    refresh_preview();
    emit composition_changed(session_->revision());
}

void CompositionPanel::on_schema_json_changed(const std::string& name,
                                              const QString& text) {
    const auto parsed = schema_json_value(text.toStdString());
    if (!parsed.has_value()) return;  // stay dirty — _commit on focus-out
    on_schema_value_changed(name, *parsed);
}

void CompositionPanel::mark_schema_dirty(const std::string& name) {
    schema_dirty_.insert(name);
}

void CompositionPanel::commit_schema_edits() {
    if (!session_) return;
    auto* el = selected_element();
    if (!el) {
        schema_dirty_.clear();
        return;
    }
    // Python commits each dirty property as its own configure command
    // (one undo step per property), not one merged patch. Iterate a COPY:
    // on_schema_value_changed erases from schema_dirty_.
    const std::set<std::string> pending = schema_dirty_;
    schema_dirty_.clear();
    for (const auto& name : pending) {
        const auto it = schema_getters_.find(name);
        if (it == schema_getters_.end() || !it->second) continue;
        on_schema_value_changed(name, it->second());
    }
}

// -- selection -----------------------------------------------------------------

void CompositionPanel::on_element_selected(int /*row*/) {
    if (suppress_item_signals_) return;
    schema_dirty_.clear();
    refresh_property_editor();
}

void CompositionPanel::on_element_menu(const QPoint& pos) {
    auto* item = element_list_->itemAt(pos);
    if (!item || !session_) return;
    const std::string eid =
        item->data(Qt::UserRole).toString().toStdString();
    auto* el = mapping_document::find_element(*document_, eid);
    if (!el) return;
    QMenu menu(this);
    auto* lock_act = menu.addAction(el->locked ? "解锁" : "锁定");
    auto* toggle_act = menu.addAction("显示/隐藏");
    auto* dup_act = menu.addAction("复制组件");
    auto* front_act = menu.addAction("置顶");
    auto* back_act = menu.addAction("置底");
    QAction* picked =
        menu.exec(element_list_->viewport()->mapToGlobal(pos));
    if (picked == lock_act) {
        toggle_lock(eid);
        return;
    }
    if (picked == toggle_act) {
        session_->set_element_visible(eid, !el->visible);
    } else if (picked == dup_act) {
        try {
            if (!session_->duplicate_element(eid)) return;
        } catch (const mapping_document::ComposerError&) {
            return;  // locked → refused (Python parity, no selection change)
        }
        refresh_all();
        emit composition_changed(session_->revision());
        return;
    } else if (picked == front_act) {
        session_->bring_to_front(eid);
    } else if (picked == back_act) {
        session_->send_to_back(eid);
    } else {
        return;
    }
    refresh_all();
    select_element(eid);
    emit composition_changed(session_->revision());
}

// -- refresh passes -----------------------------------------------------------------

void CompositionPanel::refresh_all() {
    refresh_list();
    refresh_history_state();
    refresh_property_editor();
    refresh_preview();
}

void CompositionPanel::refresh_list() {
    suppress_item_signals_ = true;
    const QString keep = QString::fromStdString(selected_element_id());
    element_list_->clear();
    std::vector<CompositionElementRow> rows;
    if (document_ != nullptr) {
        rows = composition_element_rows(*document_, seams_.element_label_fn);
    }
    for (const auto& row : rows) {
        auto* item = new QListWidgetItem(qstr(row.label));
        item->setData(Qt::UserRole, qstr(row.id));
        // Visible/hidden check state (context menu toggles visibility).
        item->setCheckState(row.checked ? Qt::Checked : Qt::Unchecked);
        element_list_->addItem(item);
        if (row.id == keep.toStdString()) {
            element_list_->setCurrentItem(item);
        }
    }
    suppress_item_signals_ = false;
    if (!keep.isEmpty()) {
        refresh_property_editor();
    }
}

void CompositionPanel::refresh_history_state() {
    const auto hist = history_state(session_.get());
    undo_btn_->setEnabled(hist.can_undo);
    redo_btn_->setEnabled(hist.can_redo);
}

void CompositionPanel::clear_schema_rows() {
    while (property_form_->rowCount() > kStaticFormRows + 1) {
        property_form_->removeRow(kStaticFormRows + 1);
    }
    schema_editors_.clear();
    schema_getters_.clear();
    schema_dirty_.clear();
}

void CompositionPanel::refresh_property_editor() {
    suppress_geometry_signals_ = true;
    suppress_schema_signals_ = true;
    if (document_ != nullptr) {
        title_edit_->setText(qstr(document_->title));
    }
    title_edit_->setEnabled(document_ != nullptr);
    auto* el = selected_element();
    const auto state = property_geometry_state(el);
    x_spin_->setEnabled(state.editable);
    y_spin_->setEnabled(state.editable);
    w_spin_->setEnabled(state.editable);
    h_spin_->setEnabled(state.editable);
    if (el != nullptr) {
        x_spin_->setValue(state.x);
        y_spin_->setValue(state.y);
        w_spin_->setValue(state.w);
        h_spin_->setValue(state.h);
    }
    lock_hint_->setVisible(state.lock_hint_visible);

    clear_schema_rows();
    if (el != nullptr && !el->locked) {
        domain::Json schema = domain::Json::array();
        if (seams_.property_schema) {
            schema = seams_.property_schema(el->element_type);
        }
        // Python walks spec.property_schema with properties.get(name) —
        // no schema-default fallback; a missing key edits as null.
        const auto& properties = el->properties;
        for (const auto& desc : schema_editor_descs(
                 schema, *el, seams_.chart_series_schemas)) {
            const domain::Json* value = nullptr;
            if (properties.is_object()) {
                const auto pit = properties.find(desc.name);
                if (pit != properties.end()) value = &pit.value();
            }
            static const domain::Json kNull;
            const domain::Json& current = value ? *value : kNull;
            QWidget* editor = make_editor(desc, current, *el);
            if (!editor) continue;
            editor->setEnabled(true);
            property_form_->addRow(qstr(desc.label), editor);
            schema_editors_[desc.name] = editor;
        }
    }
    suppress_geometry_signals_ = false;
    suppress_schema_signals_ = false;
}

QWidget* CompositionPanel::make_editor(const SchemaEditorDesc& desc,
                                       const domain::Json& value,
                                       const ComposerElement& element) {
    const std::string name = desc.name;
    switch (desc.kind) {
    case SchemaEditorKind::Bool: {
        auto* box = new QCheckBox(this);
        box->setChecked(schema_bool_value(value));
        schema_getters_[name] = [box] {
            return domain::Json(box->isChecked());
        };
        connect(box, &QCheckBox::toggled, this, [this, name](bool on) {
            on_schema_value_changed(name, domain::Json(on));
        });
        return box;
    }
    case SchemaEditorKind::Number: {
        auto* spin = new QDoubleSpinBox(this);
        spin->setRange(desc.min, desc.max);
        spin->setDecimals(2);
        spin->setSingleStep(0.1);
        spin->setValue(schema_float_value(value));
        schema_getters_[name] = [spin] {
            return domain::Json(spin->value());
        };
        connect(spin, &QDoubleSpinBox::valueChanged, this,
                [this, name](double v) {
                    on_schema_value_changed(name, domain::Json(v));
                });
        return spin;
    }
    case SchemaEditorKind::Choices: {
        auto* combo = new QComboBox(this);
        for (const auto& opt : desc.choices) {
            combo->addItem(qstr(opt));
        }
        // current = str(value or (choices[0] if choices else ""))
        std::string current;
        if (schema_bool_value(value)) {
            current = schema_text_value(value);
        } else if (!desc.choices.empty()) {
            current = desc.choices.front();
        }
        if (!current.empty() && combo->findText(qstr(current)) < 0) {
            combo->insertItem(0, qstr(current));
        }
        combo->setCurrentText(qstr(current));
        schema_getters_[name] = [combo] {
            return domain::Json(
                combo->currentText().toStdString());
        };
        connect(combo, &QComboBox::currentIndexChanged, this,
                [this, name, combo] {
                    on_schema_value_changed(
                        name,
                        domain::Json(
                            combo->currentText().toStdString()));
                });
        return combo;
    }
    case SchemaEditorKind::Text: {
        auto* edit = new QTextEdit(this);
        edit->setAcceptRichText(false);
        edit->setPlainText(qstr(schema_text_value(value)));
        edit->setMaximumHeight(64);
        schema_getters_[name] = [edit] {
            return domain::Json(
                edit->toPlainText().toStdString());
        };
        connect(edit, &QTextEdit::textChanged, this,
                [this, name] { mark_schema_dirty(name); });
        edit->installEventFilter(this);
        return edit;
    }
    case SchemaEditorKind::SeriesTable:
        return make_series_table_editor(element);
    case SchemaEditorKind::Json: {
        // Non [{label,value}] list shapes degrade to a JSON line box.
        auto* edit = new QLineEdit(this);
        edit->setText(qstr(desc.json_text));
        schema_getters_[name] = [edit] {
            const auto parsed = schema_json_value(
                edit->text().toStdString());
            return parsed.value_or(domain::Json{});
        };
        connect(edit, &QLineEdit::editingFinished, this,
                [this, name, edit] {
                    on_schema_json_changed(name, edit->text());
                });
        return edit;
    }
    case SchemaEditorKind::Str:
    default: {
        auto* edit = new QLineEdit(this);
        edit->setText(qstr(schema_text_value(value)));
        schema_getters_[name] = [edit] {
            return domain::Json(edit->text().toStdString());
        };
        connect(edit, &QLineEdit::editingFinished, this,
                [this, name, edit] {
                    on_schema_value_changed(
                        name,
                        domain::Json(
                            edit->text().toStdString()));
                });
        return edit;
    }
    }
}

QWidget* CompositionPanel::make_series_table_editor(
    const ComposerElement& element) {
    const std::string name = "series";
    auto* wrap = new QWidget(this);
    auto* lay = new QVBoxLayout(wrap);
    lay->setContentsMargins(0, 0, 0, 0);
    lay->setSpacing(2);
    const domain::Json* series = nullptr;
    if (element.properties.is_object()) {
        const auto sit = element.properties.find("series");
        if (sit != element.properties.end()) series = &sit.value();
    }
    const int rows =
        series != nullptr && series->is_array()
            ? std::max(1, static_cast<int>(series->size()))
            : 1;
    auto* table = new QTableWidget(rows, 2, wrap);
    table->setHorizontalHeaderLabels({"标签", "数值"});
    table->verticalHeader()->setVisible(false);
    table->setMaximumHeight(120);
    table->horizontalHeader()->setStretchLastSection(true);
    suppress_schema_signals_ = true;
    for (int r = 0; r < rows; ++r) {
        if (series != nullptr && series->is_array() &&
            r < static_cast<int>(series->size())) {
            const auto& entry = (*series)[size_t(r)];
            auto cell_text = [&entry](const char* key,
                                      bool numeric) {
                if (!entry.is_object()) return QString{};
                const auto it = entry.find(key);
                if (it == entry.end()) return QString{};
                if (numeric) {
                    return py_g(schema_float_value(*it));
                }
                return qstr(schema_text_value(*it));
            };
            table->setItem(r, 0,
                           new QTableWidgetItem(cell_text("label", false)));
            table->setItem(r, 1,
                           new QTableWidgetItem(cell_text("value", true)));
        } else {
            table->setItem(r, 0, new QTableWidgetItem({}));
            table->setItem(r, 1, new QTableWidgetItem("0"));
        }
    }
    suppress_schema_signals_ = false;

    // collect() — (label, raw) rows → core series_collect (blank-row
    // skip + float coercion), registered as the property getter too.
    auto collect = [table]() -> domain::Json {
        std::vector<std::pair<std::string, std::string>> rows;
        rows.reserve(size_t(table->rowCount()));
        for (int r = 0; r < table->rowCount(); ++r) {
            auto* label_item = table->item(r, 0);
            auto* value_item = table->item(r, 1);
            rows.emplace_back(
                label_item ? label_item->text().toStdString()
                           : std::string{},
                value_item ? value_item->text().toStdString()
                           : std::string{});
        }
        return pwb::ui_seqviz::series_collect(rows);
    };
    schema_getters_[name] = collect;

    connect(table, &QTableWidget::cellChanged, this,
            [this, collect](int, int) {
                on_schema_value_changed("series", collect());
            });
    auto* btn_row = new QHBoxLayout();
    auto* add = new QToolButton(wrap);
    add->setText("＋行");
    auto* remove = new QToolButton(wrap);
    remove->setText("－行");
    btn_row->addWidget(add);
    btn_row->addWidget(remove);
    btn_row->addStretch(1);
    lay->addWidget(table);
    lay->addLayout(btn_row);
    connect(add, &QToolButton::clicked, this, [this, table, collect] {
        suppress_schema_signals_ = true;
        const int row = table->rowCount();
        table->insertRow(row);
        table->setItem(row, 0, new QTableWidgetItem({}));
        table->setItem(row, 1, new QTableWidgetItem("0"));
        suppress_schema_signals_ = false;
        on_schema_value_changed("series", collect());
    });
    connect(remove, &QToolButton::clicked, this, [this, table, collect] {
        int row = table->currentRow();
        if (row < 0) {
            row = table->rowCount() - 1;
        }
        if (row >= 0) {
            table->removeRow(row);
            on_schema_value_changed("series", collect());
        }
    });
    wrap->installEventFilter(this);
    return wrap;
}

void CompositionPanel::refresh_preview() {
    if (!session_ || !document_) {
        preview_label_->setText("尚无组图");
        preview_label_->setPixmap(QPixmap{});
        return;
    }
    if (!seams_.render_svg) {
        preview_label_->setText("预览渲染失败");
        preview_label_->setPixmap(QPixmap{});
        return;
    }
    try {
        const std::string svg = seams_.render_svg(*document_);
        QSvgRenderer renderer(QByteArray::fromStdString(svg));
        if (!renderer.isValid()) {
            preview_label_->setText("预览渲染失败");
            preview_label_->setPixmap(QPixmap{});
            return;
        }
        const auto [pw, ph] =
            mapping_document::composition_page_pixels(*document_, 96.0);
        QPixmap pix{int(pw), int(ph)};
        pix.fill(Qt::white);
        QPainter painter(&pix);
        renderer.render(&painter);
        painter.end();
        preview_label_->setPixmap(pix);
        preview_label_->setText({});
    } catch (const std::exception&) {
        preview_label_->setText("预览渲染失败");
        preview_label_->setPixmap(QPixmap{});
    }
}

// -- save/load/export -----------------------------------------------------------------

void CompositionPanel::save_json() {
    if (!document_) return;
    const QString path = QFileDialog::getSaveFileName(
        this, "保存组图", {}, "JSON (*.json)");
    if (path.isEmpty()) return;
    // document_io atomic save (temp+fsync+bak) with the CONV-02 dump —
    // not a bare QFile write.
    std::string error;
    auto store = mapping_document::make_std_file_store();
    if (!mapping_document::save_composition_file(
            *store, path.toStdString(), *document_, error)) {
        QMessageBox::warning(this, "保存失败", qstr(error));
        return;
    }
    register_catalog_export(path.toStdString());
}

void CompositionPanel::load_json() {
    const QString path = QFileDialog::getOpenFileName(
        this, "载入组图", {}, "JSON (*.json)");
    if (path.isEmpty()) return;
    auto store = mapping_document::make_std_file_store();
    mapping_document::DocumentIoDiagnostics diagnostics;
    Composition loaded;
    const auto result = mapping_document::load_composition_file(
        *store, path.toStdString(), loaded, &diagnostics);
    if (result.status == mapping_document::LoadStatus::kUnreadable ||
        result.status == mapping_document::LoadStatus::kCorrupt) {
        QMessageBox::warning(this, "载入失败", qstr(result.error));
        return;
    }
    set_document(loaded);
    if (result.status ==
        mapping_document::LoadStatus::kRecoveredFromBackup) {
        QMessageBox::information(
            this, "载入组图",
            "主文件缺失或损坏，已从备份恢复。");
    }
}

void CompositionPanel::do_export() {
    if (!document_) return;
    if (!seams_.export_fn) {
        // No export engine wired into this host — honest refusal (never a
        // silent no-op).
        QMessageBox::information(this, "导出组图", "导出引擎不可用");
        return;
    }
    const QString fmt = export_combo_->currentText();
    const QString path = QFileDialog::getSaveFileName(
        this, "导出组图", {},
        QString("%1 (*.%1)").arg(fmt));
    if (path.isEmpty()) return;
    const CompositionExportResult res = seams_.export_fn(
        *document_, path.toStdString(), fmt.toStdString(),
        double(dpi_spin_->value()));
    if (!res.ok) {
        QMessageBox::warning(
            this, "导出失败",
            qstr(res.message.empty() ? "导出引擎不可用" : res.message));
        return;
    }
    register_catalog_export(res.path.empty() ? path.toStdString()
                                             : res.path);
    emit composition_exported(
        qstr(res.path.empty() ? path.toStdString() : res.path));
}

void CompositionPanel::register_catalog_export(
    const std::string& path) {
    // catalog_export_plan gate — best-effort provenance write.
    const std::any project =
        seams_.project_provider ? seams_.project_provider() : std::any{};
    const auto plan = catalog_export_plan(project.has_value());
    if (plan.should_register && seams_.record_export &&
        project.has_value()) {
        try {
            seams_.record_export(project, path);
        } catch (const std::exception&) {
            // Provenance writes are best-effort (Python swallows).
        }
    }
}

void CompositionPanel::select_element(const std::string& element_id) {
    for (int i = 0; i < element_list_->count(); ++i) {
        auto* item = element_list_->item(i);
        if (item->data(Qt::UserRole).toString().toStdString() ==
            element_id) {
            element_list_->setCurrentItem(item);
            return;
        }
    }
}

bool CompositionPanel::eventFilter(QObject* watched, QEvent* event) {
    if (event->type() == QEvent::FocusOut) {
        // Python commits pending schema edits on focus-out (the
        // FocusOut event filter installed on every editor).
        for (const auto& [name, editor] : schema_editors_) {
            if (watched == editor || watched == title_edit_) {
                commit_schema_edits();
                break;
            }
        }
    }
    return QFrame::eventFilter(watched, event);
}

}  // namespace pwb::ui_seqviz::qt
