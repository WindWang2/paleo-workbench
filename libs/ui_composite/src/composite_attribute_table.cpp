#include <pwb/ui_composite/composite_attribute_table.hpp>

#include <pwb/ui_composite/composite_controller.hpp>
#include <pwb/ui_composite/composite_controller_qt.hpp>
#include <pwb/ui_composite/templates.hpp>
#include <pwb/ui_composite/vector_layer.hpp>

#include <QAbstractItemView>
#include <QDoubleValidator>
#include <QFrame>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QItemSelection>
#include <QItemSelectionModel>
#include <QMenu>
#include <QPushButton>
#include <QVBoxLayout>

namespace pwb::ui_composite {

namespace {

const std::vector<std::string>& facies_keys() {
    return pwb::ui_widgets::core::kFaciesLevelKeys;
}

int facies_key_index(const std::string& key) {
    const auto& keys = facies_keys();
    for (size_t i = 0; i < keys.size(); ++i) {
        if (keys[i] == key) return static_cast<int>(i);
    }
    return -1;
}

QString attr_text(const Json& attributes, const std::string& key) {
    if (!attributes.is_object()) return QString();
    auto it = attributes.find(key);
    if (it == attributes.end() || it->is_null()) return QString();
    if (it->is_string()) return QString::fromStdString(it->get<std::string>());
    if (it->is_number() || it->is_boolean()) {
        return QString::fromStdString(it->dump());
    }
    return QString::fromStdString(it->dump());
}

}  // namespace

// ---------------------------------------------------------------------------
// AttributeTableView (QTableWidget-compatible test surface)
// ---------------------------------------------------------------------------

AttributeTableView::AttributeTableView(QWidget* parent)
    : QTableView(parent) {}

int AttributeTableView::rowCount() const {
    return model() == nullptr ? 0 : model()->rowCount();
}

int AttributeTableView::columnCount() const {
    return model() == nullptr ? 0 : model()->columnCount();
}

QString AttributeTableView::item_text(int row, int column) const {
    QAbstractItemModel* m = model();
    if (m == nullptr) return QString();
    const QVariant value = m->data(m->index(row, column));
    return value.isNull() ? QString() : value.toString();
}

QVariant AttributeTableView::item_data(int row, int column, int role) const {
    QAbstractItemModel* m = model();
    if (m == nullptr) return {};
    return m->data(m->index(row, column), role);
}

QString AttributeTableView::horizontal_header_text(int column) const {
    QAbstractItemModel* m = model();
    if (m == nullptr) return QString();
    const QVariant text = m->headerData(column, Qt::Horizontal);
    return text.isNull() ? QString() : text.toString();
}

void AttributeTableView::sortItems(int column, Qt::SortOrder order) {
    sortByColumn(column, order);
}

// ---------------------------------------------------------------------------
// AttributeTableModel
// ---------------------------------------------------------------------------

AttributeTableModel::AttributeTableModel(QObject* parent)
    : QAbstractTableModel(parent) {}

void AttributeTableModel::reset_from_layer(
    const std::vector<std::string>& fids,
    const std::vector<AttributeFieldMeta>& columns, bool editable) {
    beginResetModel();
    fids_ = fids;
    columns_ = columns;
    editable_ = editable;
    endResetModel();
}

int AttributeTableModel::rowCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : static_cast<int>(fids_.size());
}

int AttributeTableModel::columnCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : static_cast<int>(columns_.size()) + 1;
}

QVariant AttributeTableModel::headerData(int section,
                                         Qt::Orientation orientation,
                                         int role) const {
    if (role != Qt::DisplayRole || orientation != Qt::Horizontal) {
        return {};
    }
    if (section == 0) return QStringLiteral("fid");
    if (section > 0 && section <= static_cast<int>(columns_.size())) {
        return header_for ? header_for(columns_[section - 1]) : QVariant{};
    }
    return {};
}

Qt::ItemFlags AttributeTableModel::flags(const QModelIndex& index) const {
    if (!index.isValid()) return Qt::NoItemFlags;
    Qt::ItemFlags flags = Qt::ItemIsEnabled | Qt::ItemIsSelectable;
    if (index.column() > 0 && editable_) flags |= Qt::ItemIsEditable;
    return flags;
}

QVariant AttributeTableModel::data(const QModelIndex& index, int role) const {
    if (!index.isValid() || index.row() >= static_cast<int>(fids_.size())) {
        return {};
    }
    const std::string& fid = fids_[index.row()];
    if (index.column() == 0) {
        if (role == Qt::DisplayRole || role == Qt::EditRole ||
            role == Qt::UserRole) {
            return QString::fromStdString(fid);
        }
        return {};
    }
    const AttributeFieldMeta& field = columns_[index.column() - 1];
    const VectorFeature* feature =
        feature_for ? feature_for(fid) : nullptr;
    const Json attributes =
        feature != nullptr ? feature->attributes : Json::object();
    const Json value =
        attributes.is_object() && attributes.contains(field.key)
            ? attributes[field.key]
            : Json();
    if (role == Qt::UserRole) {
        return QVariantList{QString::fromStdString(fid),
                            QString::fromStdString(field.key),
                            QString::fromStdString(field.kind)};
    }
    if (role == Qt::DisplayRole || role == Qt::EditRole) {
        if (value.is_null()) return QString();
        if (field.numeric() &&
            (value.is_number() && !value.is_boolean())) {
            return value.get<double>();
        }
        if (field.numeric()) {
            const QString text = attr_text(attributes, field.key).trimmed();
            bool ok = false;
            const double parsed = text.toDouble(&ok);
            return ok ? QVariant(parsed) : QVariant(text);
        }
        return attr_text(attributes, field.key);
    }
    return {};
}

bool AttributeTableModel::setData(const QModelIndex& index,
                                  const QVariant& value, int role) {
    if (role != Qt::EditRole || !index.isValid() || index.column() == 0) {
        return false;
    }
    const AttributeFieldMeta& field = columns_[index.column() - 1];
    const std::string& fid = fids_[index.row()];
    const bool written =
        write_attribute
            ? write_attribute(fid, field.key, field.kind, value.toString())
            : false;
    if (!written) return false;
    emit dataChanged(index, index);
    return true;
}

void AttributeTableModel::sort(int column, Qt::SortOrder order) {
    if (column < 0 || column >= columnCount()) return;
    const bool reverse = order == Qt::DescendingOrder;
    std::vector<std::pair<std::string, QVariant>> keyed;
    keyed.reserve(fids_.size());
    for (size_t row = 0; row < fids_.size(); ++row) {
        keyed.emplace_back(
            fids_[row],
            data(index(static_cast<int>(row), column), Qt::DisplayRole));
    }
    auto sort_key = [](const QVariant& value)
        -> std::tuple<int, double, QString> {
        if (value.isNull() ||
            (value.typeId() == QMetaType::QString &&
             value.toString().isEmpty())) {
            return {1, 0.0, QString()};
        }
        if (value.typeId() == QMetaType::Double ||
            value.typeId() == QMetaType::Int ||
            value.typeId() == QMetaType::LongLong) {
            return {0, value.toDouble(), QString()};
        }
        return {0, 0.0, value.toString()};
    };
    emit layoutAboutToBeChanged();
    std::stable_sort(
        keyed.begin(), keyed.end(),
        [&](const auto& a, const auto& b) {
            const auto ka = sort_key(a.second);
            const auto kb = sort_key(b.second);
            return reverse ? kb < ka : ka < kb;
        });
    fids_.clear();
    for (auto& [fid, _value] : keyed) fids_.push_back(std::move(fid));
    emit layoutChanged();
}

void AttributeTableModel::emit_rows(
    const std::vector<std::string>& fids,
    const std::map<std::string, int>* row_by_id) {
    std::map<std::string, int> local;
    const std::map<std::string, int>& lookup =
        row_by_id != nullptr ? *row_by_id : (local = [this] {
            std::map<std::string, int> m;
            for (size_t i = 0; i < fids_.size(); ++i) {
                m[fids_[i]] = static_cast<int>(i);
            }
            return m;
        }());
    for (const std::string& fid : fids) {
        auto it = lookup.find(fid);
        if (it == lookup.end()) continue;
        const QModelIndex left = index(it->second, 0);
        const QModelIndex right = index(it->second, columnCount() - 1);
        emit dataChanged(left, right);
    }
}

// ---------------------------------------------------------------------------
// FieldEditorDelegate
// ---------------------------------------------------------------------------

FieldEditorDelegate::FieldEditorDelegate(
    std::function<const std::vector<AttributeFieldMeta>&()> columns_provider,
    std::function<const pwb::ui_widgets::core::FaciesTaxonomy*()>
        taxonomy_provider,
    QWidget* parent)
    : QStyledItemDelegate(parent),
      columns_provider_(std::move(columns_provider)),
      taxonomy_provider_(std::move(taxonomy_provider)) {}

std::optional<QStringList> FieldEditorDelegate::facies_choices(
    const QModelIndex& index, const AttributeFieldMeta& field) const {
    if (facies_key_index(field.key) < 0 || !taxonomy_provider_) {
        return std::nullopt;
    }
    const auto* taxonomy = taxonomy_provider_();
    if (taxonomy == nullptr || !*taxonomy) return std::nullopt;
    std::vector<std::string> parents;
    for (int i = 0; i < facies_key_index(field.key); ++i) {
        const QModelIndex sibling =
            index.sibling(index.row(), 1 + column_of(facies_keys()[i]));
        parents.push_back(sibling.isValid()
                              ? sibling.data().toString().trimmed().toStdString()
                              : "");
    }
    QStringList out;
    for (const std::string& name : taxonomy->names(field.key, parents)) {
        out.append(QString::fromStdString(name));
    }
    return out;
}

int FieldEditorDelegate::column_of(const std::string& key) const {
    if (!columns_provider_) return -1;
    const auto& columns = columns_provider_();
    for (size_t column = 0; column < columns.size(); ++column) {
        if (columns[column].key == key) return static_cast<int>(column);
    }
    return -1;
}

QWidget* FieldEditorDelegate::createEditor(
    QWidget* parent, const QStyleOptionViewItem& option,
    const QModelIndex& index) const {
    const int column = index.column() - 1;
    if (!columns_provider_ || column < 0 ||
        column >= static_cast<int>(columns_provider_().size())) {
        return QStyledItemDelegate::createEditor(parent, option, index);
    }
    const AttributeFieldMeta& field = columns_provider_()[column];
    const auto facies = facies_choices(index, field);
    if (facies.has_value()) {
        auto* combo = new QComboBox(parent);
        combo->setEditable(true);
        if (field.key != "facies") combo->addItem(QString());  // 不填
        combo->addItems(*facies);
        return combo;
    }
    if (!field.choices.empty()) {
        auto* combo = new QComboBox(parent);
        combo->setEditable(true);
        for (const std::string& choice : field.choices) {
            combo->addItem(QString::fromStdString(choice));
        }
        return combo;
    }
    if (field.kind == "bool") {
        auto* combo = new QComboBox(parent);
        combo->addItems({QStringLiteral("true"), QStringLiteral("false")});
        return combo;
    }
    if (field.numeric()) {
        auto* editor = new QLineEdit(parent);
        auto* validator = new QDoubleValidator(editor);
        validator->setNotation(QDoubleValidator::StandardNotation);
        if (field.value_range.has_value()) {
            validator->setRange(field.value_range->first,
                                field.value_range->second);
        }
        editor->setValidator(validator);
        return editor;
    }
    return QStyledItemDelegate::createEditor(parent, option, index);
}

void FieldEditorDelegate::setEditorData(QWidget* editor,
                                        const QModelIndex& index) const {
    if (auto* combo = qobject_cast<QComboBox*>(editor)) {
        const QString text = index.data().toString();
        if (!combo->isEditable()) {
            // review-1 P0-1：编辑器必须落在当前值上。
            const int position = combo->findText(text);
            combo->setCurrentIndex(position >= 0 ? position : 0);
            return;
        }
        const int position = combo->findText(text);
        combo->setCurrentIndex(position >= 0 ? position : -1);
        combo->lineEdit()->setText(text);
        return;
    }
    QStyledItemDelegate::setEditorData(editor, index);
}

void FieldEditorDelegate::setModelData(QWidget* editor,
                                       QAbstractItemModel* model,
                                       const QModelIndex& index) const {
    if (auto* combo = qobject_cast<QComboBox*>(editor)) {
        model->setData(index, combo->currentText());
        return;
    }
    QStyledItemDelegate::setModelData(editor, model, index);
}

// ---------------------------------------------------------------------------
// CompositeAttributeTableDialog
// ---------------------------------------------------------------------------

CompositeAttributeTableDialog::CompositeAttributeTableDialog(
    CompositeEditController* controller, const std::string& layer_id,
    CompositeEditControllerObject* notifier, QWidget* parent)
    : QDialog(parent), controller_(controller), layer_id_(layer_id) {
    setObjectName("CompositeAttributeTableDialog");
    VectorLayer* lyr = controller_->layer(layer_id_);
    setWindowTitle(QStringLiteral("属性表 — %1")
                       .arg(lyr != nullptr
                                ? QString::fromStdString(lyr->name())
                                : QString()));

    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(8, 8, 8, 8);
    outer->setSpacing(6);

    info_ = new QLabel(QString(), this);
    info_->setObjectName("WorkstationPanelFootnote");
    outer->addWidget(info_);

    model_ = new AttributeTableModel(this);
    model_->header_for = &CompositeAttributeTableDialog::header_for;
    model_->feature_for = [this](const std::string& fid) {
        return feature(fid);
    };
    model_->write_attribute =
        [this](const std::string& fid, const std::string& key,
               const std::string& kind, const QString& text) {
            return write_attribute(fid, key, kind, text);
        };
    table = new AttributeTableView(this);
    table->setObjectName("CompositeAttributeTableWidget");
    table->setModel(model_);
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    table->setSelectionMode(QAbstractItemView::ExtendedSelection);
    table->setEditTriggers(QAbstractItemView::DoubleClicked |
                           QAbstractItemView::SelectedClicked |
                           QAbstractItemView::EditKeyPressed);
    table->setSortingEnabled(true);
    table->verticalHeader()->setVisible(false);
    table->horizontalHeader()->setSectionResizeMode(
        QHeaderView::Interactive);
    table->horizontalHeader()->setSortIndicatorShown(true);
    table->setItemDelegate(new FieldEditorDelegate(
        [this]() -> const std::vector<AttributeFieldMeta>& {
            return columns();
        },
        // Lazy: reads the holder at editor-creation time so
        // set_taxonomy_provider may be injected after construction.
        [this]() -> const pwb::ui_widgets::core::FaciesTaxonomy* {
            return taxonomy_provider_holder_ ? taxonomy_provider_holder_()
                                             : nullptr;
        },
        table));
    // 相带家族图层：右键选中行 →「指定相带…」。
    const std::string tpl = controller_->layer_template(layer_id_);
    const std::string role = controller_->role_of_layer(layer_id_);
    if (is_facies_family_layer({{layer_id_, tpl}}, layer_id_, role)) {
        table->setContextMenuPolicy(Qt::CustomContextMenu);
        connect(table, &QWidget::customContextMenuRequested, this,
                &CompositeAttributeTableDialog::on_context_menu);
    }
    outer->addWidget(table, 1);

    auto* batch = new QFrame(this);
    auto* batch_layout = new QHBoxLayout(batch);
    batch_layout->setContentsMargins(0, 0, 0, 0);
    batch_layout->setSpacing(6);
    batch_layout->addWidget(
        new QLabel(QStringLiteral("批量修改选中行："), batch));
    batch_field_ = new QComboBox(batch);
    batch_value_ = new QLineEdit(batch);
    batch_value_->setPlaceholderText(QStringLiteral("新值"));
    auto* apply_button =
        new QPushButton(QStringLiteral("应用到选中"), batch);
    connect(apply_button, &QPushButton::clicked, this,
            &CompositeAttributeTableDialog::apply_batch);
    batch_layout->addWidget(batch_field_, 1);
    batch_layout->addWidget(batch_value_, 1);
    batch_layout->addWidget(apply_button);
    outer->addWidget(batch);

    auto* close = new QPushButton(QStringLiteral("关闭"), this);
    connect(close, &QPushButton::clicked, this, &QDialog::accept);
    outer->addWidget(close);

    connect(table->selectionModel(), &QItemSelectionModel::selectionChanged,
            this, &CompositeAttributeTableDialog::on_selection_changed);
    connect(table, &QTableView::doubleClicked, this,
            &CompositeAttributeTableDialog::on_cell_double_clicked);
    connect(table->horizontalHeader(), &QHeaderView::sortIndicatorChanged,
            this, &CompositeAttributeTableDialog::on_sort_changed);

    if (notifier != nullptr) {
        connect(notifier, &CompositeEditControllerObject::content_changed,
                this,
                &CompositeAttributeTableDialog::on_content_changed);
        connect(notifier, &CompositeEditControllerObject::state_changed,
                this, &CompositeAttributeTableDialog::on_state_changed);
    }

    refresh();
    resize(720, 420);
}

void CompositeAttributeTableDialog::set_taxonomy_provider(
    std::function<const pwb::ui_widgets::core::FaciesTaxonomy*()> provider) {
    taxonomy_provider_holder_ = std::move(provider);
}

void CompositeAttributeTableDialog::on_context_menu(
    const QPoint& position) {
    if (table->selectionModel()->selectedIndexes().isEmpty()) return;
    QMenu menu(table);
    QAction* action = menu.addAction(QStringLiteral("指定相带…"));
    QAction* chosen =
        menu.exec(table->viewport()->mapToGlobal(position));
    if (chosen == action) emit assign_facies_requested();
}

// -- data -------------------------------------------------------------------

VectorLayer* CompositeAttributeTableDialog::layer() const {
    return controller_->layer(layer_id_);
}

std::vector<VectorFeature> CompositeAttributeTableDialog::features() const {
    VectorLayer* lyr = layer();
    if (lyr == nullptr) return {};
    VectorEditSession* session = lyr->edit_session();
    return session != nullptr ? session->features() : lyr->features();
}

const VectorFeature* CompositeAttributeTableDialog::feature(
    const std::string& feature_id) const {
    VectorLayer* lyr = layer();
    if (lyr == nullptr) return nullptr;
    VectorEditSession* session = lyr->edit_session();
    if (session != nullptr) {
        return session->has_feature(feature_id)
                   ? &session->feature(feature_id)
                   : nullptr;
    }
    return lyr->has_feature(feature_id) ? &lyr->feature(feature_id)
                                        : nullptr;
}

const std::vector<AttributeFieldMeta>&
CompositeAttributeTableDialog::columns() {
    if (columns_cache_.has_value()) return *columns_cache_;
    AttributeLayerSource source;
    source.role_of_layer = [this](const std::string& id) {
        return controller_->role_of_layer(id);
    };
    source.layer_schema = [this](const std::string& id) {
        return controller_->layer_schema(id);
    };
    source.layer = [this](const std::string& id) -> const VectorLayer* {
        return controller_->layer(id);
    };
    columns_cache_ = field_descriptors_for_layer(source, layer_id_);
    return *columns_cache_;
}

void CompositeAttributeTableDialog::refresh() {
    VectorLayer* lyr = layer();
    if (lyr == nullptr) {
        reject();
        return;
    }
    invalidate_columns();
    const auto& cols = columns();
    const auto feats = features();
    const auto [editable, gate_reason] =
        controller_->can_edit_layer(layer_id_);
    const auto [parity_state, parity_detail] = qgis_parity(cols);
    suppress_item_changed_ = true;
    suppress_selection_sync_ = true;
    table->setSortingEnabled(false);
    {
        std::vector<std::string> fids;
        fids.reserve(feats.size());
        for (const VectorFeature& f : feats) fids.push_back(f.feature_id);
        model_->reset_from_layer(fids, cols, editable);
        info_->setText(status_text(static_cast<int>(feats.size()),
                                   static_cast<int>(cols.size()), lyr,
                                   editable, gate_reason, parity_state,
                                   parity_detail));
        batch_field_->clear();
        for (const AttributeFieldMeta& field : cols) {
            batch_field_->addItem(QString::fromStdString(field.label),
                                  QString::fromStdString(field.key));
        }
        sync_selection_from_layer(lyr);
    }
    table->setSortingEnabled(true);
    suppress_selection_sync_ = false;
    suppress_item_changed_ = false;
    VectorEditSession* session = lyr->edit_session();
    RefreshState state;
    state.session = session;
    state.revision = (lyr->data_revision << 32) +
                     (session != nullptr ? session->revision : 0);
    state.columns = cols;
    state.row_by_id = row_map();
    refresh_state_ = std::move(state);
}

std::pair<std::string, std::string>
CompositeAttributeTableDialog::qgis_parity(
    const std::vector<AttributeFieldMeta>& columns) {
    parity_state_ = qgis_schema_parity(schema_probe_, layer_id_, columns);
    return parity_state_;
}

QString CompositeAttributeTableDialog::header_for(
    const AttributeFieldMeta& field) {
    const QString mark = field.required ? QStringLiteral("*") : QString();
    return QString::fromStdString(field.label) + mark;
}

QString CompositeAttributeTableDialog::status_text(
    int feature_count, int column_count, VectorLayer* lyr, bool editable,
    const std::string& gate_reason, const std::string& parity_state,
    const std::string& parity_detail) const {
    QString parity_mark;
    if (parity_state == "synced") {
        parity_mark = QStringLiteral(" · QGIS provider schema 一致");
    } else if (parity_state == "drift") {
        parity_mark = QStringLiteral(" · %1")
                          .arg(QString::fromStdString(parity_detail));
    }
    const QString base =
        QStringLiteral("%1 个要素 · %2 个字段%3 · ")
            .arg(feature_count)
            .arg(column_count)
            .arg(parity_mark);
    if (!editable) {
        return base + QStringLiteral("只读 — %1")
                          .arg(QString::fromStdString(gate_reason));
    }
    return base +
           (lyr->edit_session() != nullptr
                ? QStringLiteral("编辑中（修改即时进入编辑会话）")
                : QStringLiteral(
                      "只读（编辑单元格将自动开始编辑会话）"));
}

std::map<std::string, int> CompositeAttributeTableDialog::row_map() const {
    std::map<std::string, int> out;
    const auto& fids = model_->fids();
    for (size_t i = 0; i < fids.size(); ++i) {
        out[fids[i]] = static_cast<int>(i);
    }
    return out;
}

void CompositeAttributeTableDialog::sync_selection_from_layer(
    VectorLayer* lyr) {
    const std::set<std::string> selection = lyr->selection();
    QItemSelectionModel* model = table->selectionModel();
    if (model == nullptr) return;
    QItemSelection sel;
    const auto& fids = model_->fids();
    for (size_t row = 0; row < fids.size(); ++row) {
        if (selection.count(fids[row])) {
            const QModelIndex index =
                model_->index(static_cast<int>(row), 0);
            sel.select(index, index);
        }
    }
    model->select(sel, QItemSelectionModel::ClearAndSelect |
                           QItemSelectionModel::Rows);
}

void CompositeAttributeTableDialog::on_sort_changed(int column,
                                                    Qt::SortOrder order) {
    (void)column;
    (void)order;
    // 排序移动行后重建差量刷新基线的行映射。
    if (!refresh_state_.has_value()) return;
    refresh_state_->row_by_id = row_map();
}

// -- editing ------------------------------------------------------------------

VectorEditSession* CompositeAttributeTableDialog::edit_session() {
    // 门禁下的会话获取（V6 B-P0-1：RAW 图层绝不开启会话）。
    if (layer() == nullptr) return nullptr;
    const auto [session, _reason] =
        controller_->ensure_layer_session(layer_id_);
    return session;
}

bool CompositeAttributeTableDialog::write_attribute(
    const std::string& feature_id, const std::string& key,
    const std::string& kind, const QString& text) {
    VectorEditSession* session = edit_session();
    if (session == nullptr) {
        VectorLayer* lyr = layer();
        const auto [_allowed, reason] =
            controller_->can_edit_layer(layer_id_);
        info_->setText(
            lyr != nullptr
                ? QStringLiteral("只读 — %1（输入未写入）")
                      .arg(QString::fromStdString(
                          reason.empty() ? "当前图层不可编辑" : reason))
                : QStringLiteral("只读"));
        return false;
    }
    const AttributeFieldMeta* field = nullptr;
    for (const AttributeFieldMeta& entry : columns()) {
        if (entry.key == key) {
            field = &entry;
            break;
        }
    }
    Json value = text.toStdString();
    if (field != nullptr && field->numeric()) {
        bool ok = false;
        const double parsed = text.toDouble(&ok);
        if (!ok) {
            if (field->value_range.has_value()) {
                // review-2 P2-2：带 Range 域的字段必须可解析为数值。
                info_->setText(
                    QStringLiteral(
                        "字段「%1」需要数值（Range 约束）——输入未写入")
                        .arg(QString::fromStdString(field->label)));
                return false;
            }
            // 无域约束：保留输入；校验在 schema 层标记。
        } else {
            value = parsed;
            if (field->value_range.has_value()) {
                const auto [low, high] = *field->value_range;
                if (!(low <= parsed && parsed <= high)) {
                    info_->setText(
                        QStringLiteral(
                            "字段「%1」超出范围 [%2, %3]——输入未写入"
                            "（QGIS Range 约束同源）")
                            .arg(QString::fromStdString(field->label))
                            .arg(low)
                            .arg(high));
                    return false;
                }
            }
        }
    }
    if (field != nullptr && field->required && text.trimmed().isEmpty()) {
        info_->setText(
            QStringLiteral("字段「%1」为必填（not-null）——输入未写入")
                .arg(QString::fromStdString(field->label)));
        return false;
    }
    if (field != nullptr && field->unique &&
        unique_value_taken(*field, feature_id,
                           value.is_string()
                               ? QVariant(QString::fromStdString(
                                     value.get<std::string>()))
                               : QVariant(value.get<double>()))) {
        info_->setText(
            QStringLiteral(
                "字段「%1」的值已被其他要素占用（unique 约束）"
                "——输入未写入")
                .arg(QString::fromStdString(field->label)));
        return false;
    }
    session->change_attribute(feature_id, key, value);
    // 属性变化驱动画布（标注渲染）与工程同步；本表自身的重建被抑制。
    suppress_content_refresh_ = true;
    if (controller_->events.content_changed) {
        controller_->events.content_changed(layer_id_);
    }
    suppress_content_refresh_ = false;
    return true;
}

bool CompositeAttributeTableDialog::unique_value_taken(
    const AttributeFieldMeta& field, const std::string& feature_id,
    const QVariant& value) const {
    const QString text = value.toString().trimmed();
    if (text.isEmpty()) return false;
    for (const VectorFeature& f : features()) {
        if (f.feature_id == feature_id) continue;  // 自身不构成冲突
        const QString other =
            attr_text(f.attributes, field.key).trimmed();
        if (other.isEmpty()) continue;
        if (field.numeric()) {
            bool ok_a = false, ok_b = false;
            const double a = other.toDouble(&ok_a);
            const double b = value.toDouble(&ok_b);
            if (ok_a && ok_b && a == b) return true;
            continue;
        }
        if (other == text) return true;
    }
    return false;
}

void CompositeAttributeTableDialog::apply_batch() {
    const std::string key =
        batch_field_->currentData().toString().toStdString();
    const QString text = batch_value_->text();
    if (key.empty()) return;
    std::set<int> rows;
    for (const QModelIndex& index : table->selectionModel()->selectedIndexes()) {
        rows.insert(index.row());
    }
    std::vector<std::string> feature_ids;
    for (const int row : rows) {
        if (row >= 0 && row < static_cast<int>(model_->fids().size())) {
            feature_ids.push_back(model_->fids()[row]);
        }
    }
    std::string kind = "text";
    for (const AttributeFieldMeta& entry : columns()) {
        if (entry.key == key) {
            kind = entry.kind;
            break;
        }
    }
    if (edit_session() == nullptr) return;
    for (const std::string& fid : feature_ids) {
        write_attribute(fid, key, kind, text);
    }
    refresh();
}

// -- selection sync -----------------------------------------------------------

void CompositeAttributeTableDialog::on_selection_changed() {
    if (suppress_selection_sync_) return;
    VectorLayer* lyr = layer();
    if (lyr == nullptr) return;
    std::set<std::string> feature_ids;
    for (const QModelIndex& index : table->selectionModel()->selectedIndexes()) {
        if (index.column() == 0 && index.row() >= 0 &&
            index.row() < static_cast<int>(model_->fids().size())) {
            feature_ids.insert(model_->fids()[index.row()]);
        }
    }
    lyr->set_selection(
        std::vector<std::string>(feature_ids.begin(), feature_ids.end()));
    if (controller_->events.state_changed) {
        controller_->events.state_changed();
    }
}

void CompositeAttributeTableDialog::on_cell_double_clicked(
    const QModelIndex& index) {
    if (!index.isValid() || index.column() != 0) return;
    if (index.row() >= 0 &&
        index.row() < static_cast<int>(model_->fids().size())) {
        emit feature_activated(
            QString::fromStdString(model_->fids()[index.row()]));
    }
}

// -- live refresh ---------------------------------------------------------------

void CompositeAttributeTableDialog::on_content_changed(
    const QString& layer_id) {
    if (layer_id.toStdString() == layer_id_ && !suppress_content_refresh_) {
        if (!refresh_changed_features()) refresh();
    }
}

bool CompositeAttributeTableDialog::refresh_changed_features() {
    // 差量刷新（C-P0-3）：会话内属性变更只更新受影响行。
    VectorLayer* lyr = layer();
    if (lyr == nullptr) return false;
    VectorEditSession* session = lyr->edit_session();
    if (session == nullptr || !refresh_state_.has_value() ||
        refresh_state_->session != session) {
        return false;
    }
    const qint64 revision =
        (lyr->data_revision << 32) + session->revision;
    if (revision == refresh_state_->revision) {
        return true;  // 重复通知，内容未变
    }
    const auto entries =
        session->changes_since(refresh_state_->revision & 0xFFFFFFFF);
    if (!entries.has_value()) return false;
    const auto& row_by_id = refresh_state_->row_by_id;
    const auto& cols = refresh_state_->columns;
    std::set<std::string> known_keys;
    for (const AttributeFieldMeta& field : cols) {
        known_keys.insert(field.key);
    }
    std::set<std::string> touched;
    for (const auto& ids : *entries) {
        touched.insert(ids.begin(), ids.end());
    }
    std::vector<std::string> changed;
    for (const std::string& fid : touched) {
        if (!row_by_id.count(fid)) return false;  // 新增 → 全量
        if (!session->has_feature(fid)) return false;  // 删除 → 全量
        const VectorFeature& f = session->feature(fid);
        if (f.attributes.is_object()) {
            for (auto it = f.attributes.begin(); it != f.attributes.end();
                 ++it) {
                if (!known_keys.count(it.key())) {
                    invalidate_columns();  // 新字段 → 列结构变化
                    return false;
                }
            }
        }
        changed.push_back(fid);
    }
    suppress_item_changed_ = true;
    table->setSortingEnabled(false);
    model_->emit_rows(changed, &row_by_id);
    table->setSortingEnabled(true);
    suppress_item_changed_ = false;
    refresh_state_->revision = revision;
    refresh_state_->row_by_id = row_map();
    return true;
}

void CompositeAttributeTableDialog::on_state_changed() {
    // 选择变化来自图层侧（画布点选）时同步表选区，避免整表重建。
    VectorLayer* lyr = layer();
    if (lyr == nullptr) return;
    suppress_selection_sync_ = true;
    sync_selection_from_layer(lyr);
    suppress_selection_sync_ = false;
}

}  // namespace pwb::ui_composite
