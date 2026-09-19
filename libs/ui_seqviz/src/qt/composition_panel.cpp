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

#include <pwb/layout_export/layout_export.hpp>
#include <pwb/ui_seqviz/composition_state.hpp>

namespace pwb::ui_seqviz::qt {
namespace {

constexpr int kStaticFormRows = 5;  // title + x + y + w + h

domain::Json default_schema(const domain::Json& item) {
    auto it = item.find("default");
    if (it == item.end()) return domain::Json{};
    return it->second;
}

// Resolve the rendered element-type label for property keys that are
// expected to reference element types (kept minimal: only used when a
// schema field is itself a type-choice — composition_panel.py doesn't
// translate schema values, so we don't either).
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
        s->setDecimals(2);
        s->setSingleStep(1.0);
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
    export_row->addWidget(export_combo_);
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
            const std::string field = s == x_spin_   ? "x_mm"
                                      : s == y_spin_ ? "y_mm"
                                      : s == w_spin_ ? "width_mm"
                                                     : "height_mm";
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
            template_combo_->addItem(
                QString::fromStdString(t.label),
                QString::fromStdString(t.template_id));
            const int idx = template_combo_->count() - 1;
            if (!t.description.empty()) {
                template_combo_->setItemData(
                    idx, QString::fromStdString(t.description),
                    Qt::ToolTipRole);
            }
        }
    }
}

void CompositionPanel::set_document(const Composition& doc) {
    document_ = std::make_unique<Composition>(doc);
    session_ = std::make_unique<CompositionEditSession>(*document_,
                                                        factory_);
    schema_dirty_.clear();
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

// -- template row -------------------------------------------------------------

void CompositionPanel::build_add_menu() {
    auto* menu = add_btn_ ? add_btn_->menu() : nullptr;
    if (!menu) return;
    menu->clear();
    if (!seams_.element_menu) return;
    for (const auto& group : seams_.element_menu()) {
        if (group.specs.empty()) continue;
        auto* sub = menu->addMenu(
            QString::fromStdString(group.category_label));
        for (const auto& [type, label] : group.specs) {
            sub->addAction(QString::fromStdString(label), this,
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
        QMessageBox::warning(this, "模板新建失败",
                             QString::fromStdString(exc.what()));
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
        const std::string eid =
            session_->add_element(element_type);
        refresh_list();
        select_element(eid);
        refresh_preview();
        emit composition_changed(session_->revision());
    } catch (const mapping_document::ComposerError&) {
        // Python silently swallows ComposerError here (element type not in
        // the registry / unsupported) — the seam is the validator.
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
    if (!session_ || !document_) return;
    const auto* src = selected_element();
    if (!src) return;
    mapping_document::ComposerElement copy = *src;
    copy.id.clear();  // factory assigns a fresh id
    copy.z_index += 1;
    try {
        const std::string eid = session_->add_element(copy);
        refresh_list();
        select_element(eid);
        refresh_preview();
        emit composition_changed(session_->revision());
    } catch (const mapping_document::ComposerError&) {
    }
}

void CompositionPanel::toggle_lock(const std::string& element_id) {
    if (!session_ || !document_) return;
    auto* el = mapping_document::find_element(*document_, element_id);
    if (!el) return;
    try {
        session_->set_element_flag(element_id, "locked", !el->locked);
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
        session_->reorder_element(eid, mode);
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
    try {
        apply_element_geometry(*session_, *document_, eid, field, value);
    } catch (const mapping_document::ComposerError&) {
        return;
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
    domain::Json patch = domain::Json::object();
    for (const auto& name : schema_dirty_) {
        auto it = schema_getters_.find(name);
        if (it != schema_getters_.end() && it->second) {
            patch[name] = it->second();
        }
    }
    schema_dirty_.clear();
    if (patch.empty()) return;
    try {
        session_->configure_element(el->id, patch);
    } catch (const mapping_document::ComposerError&) {
        return;
    }
    refresh_preview();
    emit composition_changed(session_->revision());
}

// -- selection -----------------------------------------------------------------

void CompositionPanel::on_element_selected(int /*row*/) {
    schema_dirty_.clear();
    refresh_property_editor();
}

void CompositionPanel::on_element_menu(const QPoint& pos) {
    auto* item = element_list_->itemAt(pos);
    if (!item) return;
    const std::string eid =
        item->data(Qt::UserRole).toString().toStdString();
    QMenu menu(this);
    auto* lock_act = menu.addAction("锁定/解锁");
    auto* front_act = menu.addAction("置顶");
    auto* back_act = menu.addAction("置底");
    menu.addSeparator();
    auto* dup_act = menu.addAction("复制");
    auto* del_act = menu.addAction("删除");
    QAction* picked =
        menu.exec(element_list_->viewport()->mapToGlobal(pos));
    if (picked == lock_act) {
        toggle_lock(eid);
    } else if (picked == front_act) {
        try {
            if (session_) session_->reorder_element(eid, "front");
        } catch (const mapping_document::ComposerError&) {
        }
        refresh_list();
        select_element(eid);
        refresh_preview();
    } else if (picked == back_act) {
        try {
            if (session_) session_->reorder_element(eid, "back");
        } catch (const mapping_document::ComposerError&) {
        }
        refresh_list();
        select_element(eid);
        refresh_preview();
    } else if (picked == dup_act) {
        element_list_->setCurrentItem(item);
        duplicate_selected();
    } else if (picked == del_act) {
        element_list_->setCurrentItem(item);
        delete_selected();
    }
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
    for (const auto& row : composition_element_rows(
             document_.get(), seams_.element_label_fn)) {
        auto* item =
            new QListWidgetItem(QString::fromStdString(row.label));
        item->setData(Qt::UserRole,
                      QString::fromStdString(row.element_id));
        element_list_->addItem(item);
        if (row.element_id == keep.toStdString()) {
            element_list_->setCurrentItem(item);
        }
    }
    suppress_item_signals_ = false;
}

void CompositionPanel::refresh_history_state() {
    const auto hist =
        session_ ? composition_history_state(*session_)
                 : CompositionHistoryState{};
    undo_btn_->setEnabled(hist.can_undo);
    redo_btn_->setEnabled(hist.can_redo);
    undo_btn_->setToolTip(QString::fromStdString(hist.undo_tip));
    redo_btn_->setToolTip(QString::fromStdString(hist.redo_tip));
}

void CompositionPanel::clear_schema_rows() {
    while (property_form_->rowCount() > kStaticFormRows + 1) {
        property_form_->removeRow(kStaticFormRows + 1);
    }
    schema_editors_.clear();
    schema_getters_.clear();
}

void CompositionPanel::refresh_property_editor() {
    suppress_geometry_signals_ = true;
    suppress_schema_signals_ = true;
    clear_schema_rows();
    auto* el = selected_element();
    const auto state =
        element_geometry_state(el, session_ != nullptr);
    title_edit_->setEnabled(state.title_enabled);
    title_edit_->setText(QString::fromStdString(state.title_text));
    x_spin_->setEnabled(state.geometry_enabled);
    y_spin_->setEnabled(state.geometry_enabled);
    w_spin_->setEnabled(state.geometry_enabled);
    h_spin_->setEnabled(state.geometry_enabled);
    if (el) {
        x_spin_->setValue(el->x_mm);
        y_spin_->setValue(el->y_mm);
        w_spin_->setValue(el->width_mm);
        h_spin_->setValue(el->height_mm);
    }
    lock_hint_->setVisible(state.lock_hint_visible);

    if (el && !el->locked) {
        domain::Json schema =
            seams_.property_schema
                ? seams_.property_schema(el->element_type)
                : domain::Json{};
        for (const auto& desc : schema_editor_descriptors(
                 schema, el, seams_.chart_series_schemas)) {
            const domain::Json* value = nullptr;
            const auto pit = el->properties.find(desc.name);
            if (pit != el->properties.end()) value = &pit->second;
            domain::Json fallback;
            if (!value) {
                fallback = default_schema(desc.schema);
                value = &fallback;
            }
            QWidget* editor = make_editor(desc, *value, *el);
            if (!editor) continue;
            property_form_->addRow(
                QString::fromStdString(desc.label), editor);
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
    case SchemaEditorKind::Float: {
        auto* spin = new QDoubleSpinBox(this);
        spin->setDecimals(desc.decimals);
        spin->setSingleStep(desc.step);
        spin->setRange(desc.minimum, desc.maximum);
        spin->setValue(schema_float_value(value));
        schema_getters_[name] = [spin] {
            return domain::Json(spin->value());
        };
        connect(spin, &QDoubleSpinBox::editingFinished, this,
                [this, name, spin] {
                    on_schema_value_changed(name,
                                            domain::Json(spin->value()));
                });
        spin->installEventFilter(this);
        return spin;
    }
    case SchemaEditorKind::Int: {
        auto* spin = new QSpinBox(this);
        spin->setRange(desc.minimum < -1e9 ? -1'000'000'000
                                           : int(desc.minimum),
                       desc.maximum > 1e9 ? 1'000'000'000
                                          : int(desc.maximum));
        spin->setValue(int(schema_float_value(value)));
        schema_getters_[name] = [spin] {
            return domain::Json(long long(spin->value()));
        };
        connect(spin, &QSpinBox::editingFinished, this,
                [this, name, spin] {
                    on_schema_value_changed(
                        name, domain::Json(long long(spin->value())));
                });
        spin->installEventFilter(this);
        return spin;
    }
    case SchemaEditorKind::Choice: {
        auto* combo = new QComboBox(this);
        for (const auto& opt : desc.options) {
            combo->addItem(QString::fromStdString(opt),
                           QString::fromStdString(opt));
        }
        const std::string cur = schema_text_value(value);
        const int idx = combo->findText(QString::fromStdString(cur));
        combo->setCurrentIndex(idx >= 0 ? idx : 0);
        schema_getters_[name] = [combo] {
            return domain::Json(combo->currentData()
                                    .toString()
                                    .toStdString());
        };
        connect(combo, &QComboBox::currentTextChanged, this,
                [this, name](const QString& t) {
                    on_schema_value_changed(
                        name, domain::Json(t.toStdString()));
                });
        return combo;
    }
    case SchemaEditorKind::SeriesTable:
        return make_series_table_editor(element);
    case SchemaEditorKind::JsonText: {
        auto* edit = new QTextEdit(this);
        edit->setAcceptRichText(false);
        edit->setPlainText(
            QString::fromStdString(schema_json_text(value)));
        edit->setMaximumHeight(120);
        schema_getters_[name] = [edit] {
            const auto parsed =
                schema_json_value(edit->toPlainText().toStdString());
            return parsed.value_or(domain::Json{});
        };
        connect(edit, &QTextEdit::textChanged, this,
                [this, name] { mark_schema_dirty(name); });
        edit->installEventFilter(this);
        return edit;
    }
    case SchemaEditorKind::Line:
    default: {
        auto* edit = new QLineEdit(this);
        edit->setText(QString::fromStdString(schema_text_value(value)));
        schema_getters_[name] = [edit] {
            return domain::Json(edit->text().toStdString());
        };
        connect(edit, &QLineEdit::editingFinished, this,
                [this, name, edit] {
                    on_schema_value_changed(
                        name, domain::Json(edit->text().toStdString()));
                });
        edit->installEventFilter(this);
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
    auto* table = new QTableWidget(wrap);
    table->setColumnCount(2);
    table->setHorizontalHeaderLabels({"曲线列", "样式"});
    table->horizontalHeader()->setStretchLastSection(true);
    // Existing series rows — [{curve, label/color/...}] objects.
    int rows = 0;
    const auto sit = element.properties.find("series");
    if (sit != element.properties.end() && sit->second.is_array()) {
        rows = int(sit->second.size());
    }
    table->setRowCount(rows);
    for (int r = 0; r < rows; ++r) {
        const auto& obj = sit->second[size_t(r)];
        auto cell = [&obj](const char* key) {
            const auto it = obj.find(key);
            return (it != obj.end() && it->second.is_string())
                       ? QString::fromStdString(
                             it->second.get<std::string>())
                       : QString{};
        };
        table->setItem(r, 0, new QTableWidgetItem(cell("curve")));
        table->setItem(r, 1, new QTableWidgetItem(cell("label")));
    }
    lay->addWidget(table);
    auto* btn_row = new QHBoxLayout();
    auto* add = new QToolButton(wrap);
    add->setText("＋行");
    auto* remove = new QToolButton(wrap);
    remove->setText("−行");
    btn_row->addWidget(add);
    btn_row->addWidget(remove);
    btn_row->addStretch(1);
    lay->addLayout(btn_row);
    connect(add, &QToolButton::clicked, this,
            [table, this] {
                table->insertRow(table->rowCount());
                mark_schema_dirty("series");
            });
    connect(remove, &QToolButton::clicked, this, [table, this] {
        if (table->currentRow() >= 0) {
            table->removeRow(table->currentRow());
        } else if (table->rowCount() > 0) {
            table->removeRow(table->rowCount() - 1);
        }
        mark_schema_dirty("series");
    });
    connect(table, &QTableWidget::itemChanged, this,
            [this](QTableWidgetItem*) { mark_schema_dirty("series"); });
    schema_getters_[name] = [this, table] {
        return series_collect(table);
    };
    wrap->installEventFilter(this);
    return wrap;
}

domain::Json CompositionPanel::series_collect(QTableWidget* table) const {
    domain::Json out = domain::Json::array();
    for (int r = 0; r < table->rowCount(); ++r) {
        domain::Json row = domain::Json::object();
        auto* curve = table->item(r, 0);
        auto* style = table->item(r, 1);
        row["curve"] =
            curve ? curve->text().toStdString() : std::string{};
        row["label"] =
            style ? style->text().toStdString() : std::string{};
        out.push_back(std::move(row));
    }
    return out;
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
        QSvgRenderer renderer(
            QByteArray::fromStdString(svg));
        if (!renderer.isValid()) {
            preview_label_->setText("预览渲染失败");
            preview_label_->setPixmap(QPixmap{});
            return;
        }
        const auto [pw, ph] = mapping_document::
            composition_page_pixels(*document_, 96.0);
        QPixmap pix(int(pw), int(ph));
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
    try {
        const domain::Json payload =
            mapping_document::dump_composition(*document_);
        QFile f(path);
        if (!f.open(QIODevice::WriteOnly)) {
            throw std::runtime_error("无法写入文件");
        }
        f.write(QByteArray::fromStdString(payload.dump(2)));
        register_catalog_export(path.toStdString());
    } catch (const std::exception& exc) {
        QMessageBox::warning(this, "保存失败",
                             QString::fromStdString(exc.what()));
    }
}

void CompositionPanel::load_json() {
    const QString path = QFileDialog::getOpenFileName(
        this, "载入组图", {}, "JSON (*.json)");
    if (path.isEmpty()) return;
    try {
        QFile f(path);
        if (!f.open(QIODevice::ReadOnly)) {
            throw std::runtime_error("无法读取文件");
        }
        const auto payload = domain::Json::parse(
            f.readAll().toStdString());
        set_document(mapping_document::parse_composition(payload));
    } catch (const std::exception& exc) {
        QMessageBox::warning(this, "载入失败",
                             QString::fromStdString(exc.what()));
    }
}

void CompositionPanel::do_export() {
    if (!document_ || !seams_.export_fn) return;
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
            QString::fromStdString(
                res.message.empty() ? "导出引擎不可用" : res.message));
        return;
    }
    register_catalog_export(res.path.empty() ? path.toStdString()
                                             : res.path);
    emit composition_exported(QString::fromStdString(
        res.path.empty() ? path.toStdString() : res.path));
}

void CompositionPanel::register_catalog_export(
    const std::string& path) {
    // catalog_export_plan gate — best-effort provenance write.
    const auto plan = catalog_export_plan(
        seams_.project_provider ? seams_.project_provider() : std::any{},
        path);
    if (plan.registration_needed && seams_.record_export &&
        plan.project.has_value()) {
        try {
            seams_.record_export(*plan.project, plan.path);
        } catch (const std::exception&) {
            // Provenance writes are best-effort (Python wraps the whole
            // block in try/except and swallows).
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
