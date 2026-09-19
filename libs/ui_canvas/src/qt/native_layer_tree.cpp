// UI-15 — Qt control surface for the authoritative layer registry
// (native_layer_tree.py parity).

#include <pwb/ui_canvas/qt/native_layer_tree.hpp>

#include <cmath>

#include <QAction>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QMenu>
#include <QMimeData>
#include <QTreeView>
#include <QUuid>
#include <QVBoxLayout>

#include <pwb/ui_widgets/icon_factory.hpp>
#include <pwb/ui_widgets/ui_context.hpp>

namespace pwb::ui_canvas {

namespace lm = pwb::layer_model;

// ---------------------------------------------------------------------------
// NativeLayerModel
// ---------------------------------------------------------------------------

NativeLayerModel::NativeLayerModel(lm::LayerRegistry* registry,
                                   QObject* parent)
    : QAbstractItemModel(parent), registry_(registry) {}

std::size_t NativeLayerModel::token_for(const std::string& layer_id) {
    const auto it = id_to_token_.find(layer_id);
    if (it != id_to_token_.end()) {
        return it->second;
    }
    const std::size_t token = next_token_++;
    id_to_token_[layer_id] = token;
    token_to_id_[token] = layer_id;
    return token;
}

std::optional<std::string>
NativeLayerModel::id_from_index(const QModelIndex& index) const {
    if (!index.isValid()) {
        return std::nullopt;
    }
    const auto it = token_to_id_.find(
        static_cast<std::size_t>(index.internalId()));
    if (it == token_to_id_.end()) {
        return std::nullopt;
    }
    return it->second;
}

lm::MapLayer* NativeLayerModel::layer_at(const QModelIndex& index) const {
    const auto id = id_from_index(index);
    if (!id.has_value() || registry_ == nullptr) {
        return nullptr;
    }
    return registry_->get(*id);
}

int NativeLayerModel::columnCount(const QModelIndex& /*parent*/) const {
    return 2;
}

int NativeLayerModel::rowCount(const QModelIndex& parent) const {
    if (registry_ == nullptr) {
        return 0;
    }
    if (parent.isValid() && parent.column() != 0) {
        return 0;
    }
    const auto parent_id = id_from_index(parent).value_or("");
    return static_cast<int>(display_children(*registry_, parent_id).size());
}

QModelIndex NativeLayerModel::index(int row, int column,
                                    const QModelIndex& parent) const {
    if (registry_ == nullptr || row < 0 || column < 0 ||
        column >= columnCount(parent)) {
        return {};
    }
    const auto parent_id = id_from_index(parent).value_or("");
    const auto children = display_children(*registry_, parent_id);
    if (row >= static_cast<int>(children.size())) {
        return {};
    }
    return createIndex(row, column,
                       static_cast<quintptr>(
                           const_cast<NativeLayerModel*>(this)->token_for(
                               children[static_cast<std::size_t>(row)]
                                   ->id())));
}

QModelIndex NativeLayerModel::parent(const QModelIndex& index) const {
    const auto id = id_from_index(index);
    if (!id.has_value() || registry_ == nullptr) {
        return {};
    }
    const std::string parent_id = registry_->parent_id(*id);
    if (parent_id.empty()) {
        return {};
    }
    return index_for_id(parent_id);
}

QVariant NativeLayerModel::data(const QModelIndex& index, int role) const {
    const lm::MapLayer* layer = layer_at(index);
    if (layer == nullptr) {
        return {};
    }
    if (role == Qt::DisplayRole) {
        if (index.column() == 0) {
            return QString::fromStdString(layer->name());
        }
        if (index.column() == 1) {
            return QStringLiteral("%1%").arg(
                QString::number(layer->opacity() * 100.0, 'f', 0));
        }
    }
    if (role == Qt::CheckStateRole && index.column() == 0) {
        return layer->visible() ? Qt::Checked : Qt::Unchecked;
    }
    if (role == LayerIdRole) {
        return QString::fromStdString(layer->id());
    }
    if (role == Qt::ToolTipRole) {
        QStringList parts;
        // Python uses layer.type.name (enum member name).
        switch (layer->type()) {
            case lm::LayerType::ScalarGrid: parts << "ScalarGrid"; break;
            case lm::LayerType::Raster: parts << "Raster"; break;
            case lm::LayerType::Contour: parts << "Contour"; break;
            case lm::LayerType::Vector: parts << "Vector"; break;
            case lm::LayerType::Point: parts << "Point"; break;
            case lm::LayerType::Annotation: parts << "Annotation"; break;
            case lm::LayerType::Group: parts << "Group"; break;
        }
        if (!layer->crs().empty()) {
            parts << QString::fromStdString(layer->crs());
        }
        if (!layer->source_ref().empty()) {
            parts << QString::fromStdString(layer->source_ref());
        }
        return parts.join(QStringLiteral(" · "));
    }
    return {};
}

QVariant NativeLayerModel::headerData(int section,
                                      Qt::Orientation orientation,
                                      int role) const {
    if (orientation == Qt::Horizontal && role == Qt::DisplayRole &&
        section < 2) {
        return section == 0 ? QStringLiteral("图层")
                            : QStringLiteral("不透明度");
    }
    return {};
}

Qt::ItemFlags NativeLayerModel::flags(const QModelIndex& index) const {
    if (!index.isValid()) {
        return Qt::ItemIsDropEnabled;
    }
    const lm::MapLayer* layer = layer_at(index);
    if (layer == nullptr) {
        return Qt::NoItemFlags;
    }
    Qt::ItemFlags flags = Qt::ItemIsEnabled | Qt::ItemIsSelectable;
    if (index.column() == 0) {
        flags |= Qt::ItemIsUserCheckable | Qt::ItemIsEditable |
                 Qt::ItemIsDragEnabled;
        if (layer->type() == lm::LayerType::Group) {
            flags |= Qt::ItemIsDropEnabled;
        }
        return flags;
    }
    return flags | Qt::ItemIsEditable;
}

QStringList NativeLayerModel::mimeTypes() const { return {MimeType}; }

QMimeData* NativeLayerModel::mimeData(
    const QModelIndexList& indexes) const {
    QJsonArray ids;
    for (const QModelIndex& index : indexes) {
        if (index.column() != 0) {
            continue;
        }
        const auto id = id_from_index(index);
        if (id.has_value() &&
            !ids.contains(QString::fromStdString(*id))) {
            ids.append(QString::fromStdString(*id));
        }
    }
    auto* mime = new QMimeData();
    mime->setData(MimeType,
                  QJsonDocument(ids).toJson(QJsonDocument::Compact));
    return mime;
}

Qt::DropActions NativeLayerModel::supportedDropActions() const {
    return Qt::MoveAction;
}

bool NativeLayerModel::dropMimeData(const QMimeData* data,
                                    Qt::DropAction action, int row,
                                    int /*column*/,
                                    const QModelIndex& parent) {
    if (action == Qt::IgnoreAction) {
        return true;
    }
    if (action != Qt::MoveAction || data == nullptr ||
        !data->hasFormat(MimeType) || registry_ == nullptr) {
        return false;
    }
    const QJsonDocument doc =
        QJsonDocument::fromJson(data->data(MimeType));
    if (!doc.isArray() || doc.array().size() != 1) {
        return false;
    }
    const std::string layer_id =
        doc.array().first().toString().toStdString();
    if (registry_->get(layer_id) == nullptr) {
        return false;
    }
    const std::string drop_parent = id_from_index(parent).value_or("");
    const auto resolution =
        resolve_drop(*registry_, layer_id, drop_parent, row);
    if (!resolution.has_value() || !resolution->parent_id.has_value()) {
        return false;
    }
    beginResetModel();
    if (!registry_->set_parent(layer_id, *resolution->parent_id)) {
        endResetModel();
        return false;
    }
    // Python parity: move_layer is attempted unconditionally after the
    // reparent; its clamped-move result does not veto the drop.
    registry_->move_layer(layer_id, resolution->absolute_index);
    endResetModel();
    emit layer_changed(QString::fromStdString(layer_id));
    return true;
}

bool NativeLayerModel::setData(const QModelIndex& index,
                               const QVariant& value, int role) {
    lm::MapLayer* layer = layer_at(index);
    if (layer == nullptr) {
        return false;
    }
    bool changed = false;
    if (index.column() == 0 && role == Qt::CheckStateRole) {
        const bool visible = value.toInt() == Qt::Checked ||
                             (value.metaType().id() == QMetaType::Bool &&
                              value.toBool());
        if (layer->visible() != visible) {
            layer->set_visible(visible);
            changed = true;
        }
    } else if (index.column() == 0 && role == Qt::EditRole) {
        const std::string name = value.toString().toStdString();
        if (layer->name() != name) {
            layer->set_name(name);
            changed = true;
        }
    } else if (index.column() == 1 && role == Qt::EditRole) {
        bool ok = false;
        const double raw = value.toDouble(&ok);
        if (!ok || !std::isfinite(raw)) {
            return false;
        }
        // Clamp identically to the MapLayer guard: assigning the raw value
        // let out-of-range opacity persist into the authoritative registry.
        const float opacity =
            static_cast<float>(std::clamp(raw, 0.0, 1.0));
        if (layer->opacity() != opacity) {
            layer->set_opacity(opacity);
            changed = true;
        }
    }
    if (!changed) {
        return false;
    }
    emit dataChanged(index, index, {role, Qt::DisplayRole});
    emit layer_changed(QString::fromStdString(layer->id()));
    return true;
}

void NativeLayerModel::refresh() {
    beginResetModel();
    endResetModel();
}

lm::MapLayer* NativeLayerModel::add_layer(
    const std::string& layer_id, const std::string& name,
    lm::LayerType layer_type, const std::string& parent_id) {
    beginResetModel();
    lm::MapLayer* layer = registry_->add_layer(
        std::make_unique<lm::MapLayer>(layer_id, name, layer_type),
        parent_id);
    endResetModel();
    if (layer != nullptr) {
        emit layer_changed(QString::fromStdString(layer->id()));
    }
    return layer;
}

bool NativeLayerModel::remove_layer(const std::string& layer_id) {
    beginResetModel();
    const bool removed = registry_->remove_layer(layer_id);
    endResetModel();
    if (removed && active_layer_id_ == layer_id) {
        active_layer_id_.reset();
        emit active_layer_changed(std::nullopt);
    }
    if (removed) {
        emit layer_changed(QString::fromStdString(layer_id));
    }
    return removed;
}

bool NativeLayerModel::move_layer(const std::string& layer_id,
                                  std::size_t new_index) {
    beginResetModel();
    const bool moved = registry_->move_layer(layer_id, new_index);
    endResetModel();
    if (moved) {
        emit layer_changed(QString::fromStdString(layer_id));
    }
    return moved;
}

bool NativeLayerModel::set_active_layer(
    const std::optional<std::string>& layer_id) {
    if (layer_id.has_value() && registry_->get(*layer_id) == nullptr) {
        return false;
    }
    if (active_layer_id_ == layer_id) {
        return true;
    }
    active_layer_id_ = layer_id;
    emit active_layer_changed(layer_id);
    return true;
}

bool NativeLayerModel::request_zoom_to_layer(
    const std::string& layer_id) {
    const lm::MapLayer* layer = registry_->get(layer_id);
    if (layer == nullptr) {
        return false;
    }
    const lm::Extent e = layer->extent();
    emit zoom_to_layer_requested(
        QString::fromStdString(layer_id),
        std::array<double, 4>{e[0], e[1], e[2], e[3]});
    return true;
}

QModelIndex NativeLayerModel::index_for_id(const std::string& layer_id,
                                           int column) const {
    if (registry_ == nullptr || registry_->get(layer_id) == nullptr) {
        return {};
    }
    const std::string parent_id = registry_->parent_id(layer_id);
    const auto siblings = display_children(*registry_, parent_id);
    for (std::size_t row = 0; row < siblings.size(); ++row) {
        if (siblings[row]->id() == layer_id) {
            return createIndex(static_cast<int>(row), column,
                               static_cast<quintptr>(
                                   const_cast<NativeLayerModel*>(this)
                                       ->token_for(layer_id)));
        }
    }
    return {};
}

// ---------------------------------------------------------------------------
// NativeLayerTree
// ---------------------------------------------------------------------------

NativeLayerTree::NativeLayerTree(lm::LayerRegistry* registry,
                                 QWidget* parent)
    : QFrame(parent) {
    setObjectName(QStringLiteral("NativeLayerTree"));
    setMinimumWidth(240);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(pwb::ui_widgets::kSpaceL,
                               pwb::ui_widgets::kSpaceL,
                               pwb::ui_widgets::kSpaceL,
                               pwb::ui_widgets::kSpaceL);
    layout->setSpacing(pwb::ui_widgets::kSpaceM);

    auto* title = new QLabel(QStringLiteral("原生图层"), this);
    title->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title);

    // Layer management lives entirely on the tree's right-click menu — no
    // always-visible button row (the panel stays a clean layer list).
    using pwb::ui_widgets::tinted_map_icon;
    add_layer_action_ = new QAction(
        tinted_map_icon(QStringLiteral("tree-add-layer")),
        QStringLiteral("添加图层"), this);
    add_group_action_ = new QAction(
        tinted_map_icon(QStringLiteral("tree-add-group")),
        QStringLiteral("添加分组"), this);
    remove_action_ = new QAction(
        tinted_map_icon(QStringLiteral("tree-remove")),
        QStringLiteral("移除图层"), this);
    move_up_action_ = new QAction(
        tinted_map_icon(QStringLiteral("tree-move-up")),
        QStringLiteral("上移"), this);
    move_down_action_ = new QAction(
        tinted_map_icon(QStringLiteral("tree-move-down")),
        QStringLiteral("下移"), this);
    zoom_action_ = new QAction(
        tinted_map_icon(QStringLiteral("tree-zoom")),
        QStringLiteral("缩放至图层"), this);
    properties_action_ = new QAction(
        tinted_map_icon(QStringLiteral("tree-properties")),
        QStringLiteral("属性"), this);

    model_ = new NativeLayerModel(registry, this);
    tree_ = new QTreeView(this);
    tree_->setObjectName(QStringLiteral("NativeLayerTreeView"));
    tree_->setModel(model_);
    tree_->setAlternatingRowColors(true);
    tree_->setEditTriggers(QAbstractItemView::EditKeyPressed |
                           QAbstractItemView::SelectedClicked);
    tree_->setDragEnabled(true);
    tree_->setAcceptDrops(true);
    tree_->setDropIndicatorShown(true);
    tree_->setDragDropMode(QAbstractItemView::InternalMove);
    tree_->setDefaultDropAction(Qt::MoveAction);
    tree_->setContextMenuPolicy(Qt::CustomContextMenu);
    tree_->header()->setSectionResizeMode(0, QHeaderView::Stretch);
    tree_->header()->setSectionResizeMode(1,
                                          QHeaderView::ResizeToContents);
    layout->addWidget(tree_, 1);

    connect(tree_->selectionModel(), &QItemSelectionModel::currentChanged,
            this, [this](const QModelIndex& current, const QModelIndex&) {
                const QVariant id = model_->data(current,
                                                 NativeLayerModel::LayerIdRole);
                model_->set_active_layer(
                    id.isValid() && !id.toString().isEmpty()
                        ? std::optional<std::string>(
                              id.toString().toStdString())
                        : std::nullopt);
                sync_action_state();
            });
    connect(tree_, &QAbstractItemView::doubleClicked, this,
            [this](const QModelIndex& index) {
                const QVariant id = model_->data(
                    index, NativeLayerModel::LayerIdRole);
                if (id.isValid() && !id.toString().isEmpty()) {
                    model_->request_zoom_to_layer(
                        id.toString().toStdString());
                }
            });
    connect(tree_, &QWidget::customContextMenuRequested, this,
            [this](const QPoint& pos) {
                select_row_at(pos);
                QMenu* menu = build_context_menu();
                menu->exec(tree_->viewport()->mapToGlobal(pos));
                menu->deleteLater();
            });
    connect(model_, &NativeLayerModel::active_layer_changed, this,
            &NativeLayerTree::active_layer_changed);
    connect(model_, &NativeLayerModel::zoom_to_layer_requested, this,
            &NativeLayerTree::zoom_to_layer_requested);
    connect(add_layer_action_, &QAction::triggered, this,
            &NativeLayerTree::add_layer_requested);
    connect(add_group_action_, &QAction::triggered, this,
            &NativeLayerTree::add_group);
    connect(remove_action_, &QAction::triggered, this,
            &NativeLayerTree::remove_current);
    connect(move_up_action_, &QAction::triggered, this,
            [this]() { move_current(1); });
    connect(move_down_action_, &QAction::triggered, this,
            [this]() { move_current(-1); });
    connect(zoom_action_, &QAction::triggered, this,
            &NativeLayerTree::zoom_current);
    connect(properties_action_, &QAction::triggered, this,
            &NativeLayerTree::properties_current);
    sync_action_state();
}

std::optional<std::string> NativeLayerTree::current_layer_id() const {
    const QVariant id =
        model_->data(tree_->currentIndex(), NativeLayerModel::LayerIdRole);
    if (!id.isValid() || id.toString().isEmpty()) {
        return std::nullopt;
    }
    return id.toString().toStdString();
}

void NativeLayerTree::sync_action_state() {
    const auto layer_id = current_layer_id();
    const lm::MapLayer* layer =
        layer_id.has_value()
            ? model_->registry()->get(*layer_id)
            : nullptr;
    const bool has_layer = layer != nullptr;
    remove_action_->setEnabled(has_layer);
    zoom_action_->setEnabled(has_layer);
    properties_action_->setEnabled(has_layer);
    // Display convention: top row = highest z (drawn last). "Move Up"
    // raises the z-order (index + 1), "Move Down" lowers it.
    move_up_action_->setEnabled(
        has_layer &&
        model_->registry()->index_of(*layer_id) + 1 <
            model_->registry()->size());
    move_down_action_->setEnabled(
        has_layer && model_->registry()->index_of(*layer_id) > 0);
}

void NativeLayerTree::add_group() {
    // f"group_{uuid4().hex[:12]}" parity — 12 hex chars.
    const std::string layer_id =
        "group_" + QUuid::createUuid()
                       .toString(QUuid::WithoutBraces)
                       .left(12)
                       .toStdString();
    model_->add_layer(layer_id, "Group", lm::LayerType::Group);
    expand_all();
}

void NativeLayerTree::remove_current() {
    const auto layer_id = current_layer_id();
    if (layer_id.has_value()) {
        model_->remove_layer(*layer_id);
    }
    sync_action_state();
}

void NativeLayerTree::move_current(int delta) {
    const auto layer_id = current_layer_id();
    if (!layer_id.has_value()) {
        return;
    }
    const std::size_t current = model_->registry()->index_of(*layer_id);
    const long target = static_cast<long>(current) + delta;
    if (target < 0) {
        return;
    }
    model_->move_layer(*layer_id, static_cast<std::size_t>(target));
    sync_action_state();
}

void NativeLayerTree::zoom_current() {
    const auto layer_id = current_layer_id();
    if (layer_id.has_value()) {
        model_->request_zoom_to_layer(*layer_id);
    }
}

void NativeLayerTree::properties_current() {
    const auto layer_id = current_layer_id();
    if (layer_id.has_value()) {
        emit properties_requested(QString::fromStdString(*layer_id));
    }
}

void NativeLayerTree::select_row_at(const QPoint& position) {
    const QModelIndex index = tree_->indexAt(position);
    if (index.isValid()) {
        tree_->setCurrentIndex(index);
    }
}

QMenu* NativeLayerTree::build_context_menu() {
    auto* menu = new QMenu(this);
    menu->addAction(add_layer_action_);
    menu->addAction(add_group_action_);
    menu->addSeparator();
    menu->addAction(zoom_action_);
    menu->addAction(properties_action_);
    menu->addSeparator();
    menu->addAction(move_up_action_);
    menu->addAction(move_down_action_);
    menu->addAction(remove_action_);
    const auto layer_id = current_layer_id();
    if (layer_id.has_value()) {
        menu->addSeparator();
        const QString id = QString::fromStdString(*layer_id);
        menu->addAction(
            pwb::ui_widgets::tinted_map_icon(
                QStringLiteral("tree-export")),
            QStringLiteral("导出图层"), this,
            [this, id]() { emit export_layer_requested(id); });
    }
    return menu;
}

bool NativeLayerTree::set_active_layer(
    const std::optional<std::string>& layer_id) {
    if (!model_->set_active_layer(layer_id)) {
        return false;
    }
    if (layer_id.has_value()) {
        const QModelIndex index = model_->index_for_id(*layer_id);
        if (index.isValid()) {
            tree_->setCurrentIndex(index);
            tree_->scrollTo(index);
        }
    } else {
        tree_->clearSelection();
    }
    return true;
}

void NativeLayerTree::expand_all() { tree_->expandAll(); }

}  // namespace pwb::ui_canvas
