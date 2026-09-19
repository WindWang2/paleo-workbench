#include <pwb/ui_map/map_layer_tree.hpp>

#include <QLabel>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <pwb/ui_map/item_reconcile.hpp>

namespace pwb::ui_map {

namespace {

// Roles carried on items (Python packs ("layer", key) / ("reference_layer",
// obj) tuples into Qt.UserRole; C++ stores the tag + key in two roles).
constexpr int kTagRole = Qt::UserRole;        // "doc"|"layer"|"reference"
constexpr int kKeyRole = Qt::UserRole + 1;    // layer key or document key
constexpr int kDocIndexRole = Qt::UserRole + 2;  // index into documents_

QString qstr(const std::string& s) {
    return QString::fromUtf8(s.data(), static_cast<qsizetype>(s.size()));
}

}  // namespace

MapLayerTree::MapLayerTree(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("MapLayerTree"));
    setMinimumWidth(220);

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(12, 12, 12, 12);  // PANEL_PADDING
    layout->setSpacing(8);                       // SPACE_2

    auto* title = new QLabel(QStringLiteral("图件与图层"), this);
    title->setObjectName(QStringLiteral("MapDockTitle"));
    layout->addWidget(title);

    tree_ = new QTreeWidget(this);
    tree_->setObjectName(QStringLiteral("MapLayerTreeWidget"));
    tree_->setHeaderHidden(true);
    tree_->setColumnCount(2);
    tree_->setRootIsDecorated(true);
    layout->addWidget(tree_, 1);

    for (const char* key : kLayerKeys) {
        layer_locked_[key] = false;
        layer_visible_[key] = true;
    }

    connect(tree_, &QTreeWidget::currentItemChanged, this,
            [this](QTreeWidgetItem* current, QTreeWidgetItem*) {
                on_current_item_changed(current);
            });
    connect(tree_, &QTreeWidget::itemChanged, this,
            [this](QTreeWidgetItem* item, int column) {
                on_item_changed(item, column);
            });

    rebuild_tree();
}

void MapLayerTree::set_documents(const std::vector<Json>& documents) {
    documents_ = documents;
    rebuild_tree();
}

void MapLayerTree::set_active_document(const Json* document) {
    active_document_ = document;
    rebuild_tree();
    if (document == nullptr) {
        return;
    }
    // Select + expand the matching document row (key-stable lookup —
    // identity tags resolve through the populated documents_ vector).
    const std::string wanted_key = document_key(
        *document, identity_of(*document));
    for (QTreeWidgetItem* item : doc_items_) {
        if (item->data(0, kKeyRole).toString().toStdString() ==
            wanted_key) {
            tree_->setCurrentItem(item);
            item->setExpanded(true);
            break;
        }
    }
}

void MapLayerTree::set_layer_locked(const std::string& layer_key,
                                    bool locked) {
    const auto it = layer_locked_.find(layer_key);
    if (it == layer_locked_.end() || it->second == locked) {
        return;
    }
    it->second = locked;
    const auto item_it = layer_items_.find(layer_key);
    if (item_it != layer_items_.end() && item_it->second != nullptr) {
        suppress_item_changed_ = true;
        item_it->second->setText(
            1, locked ? QStringLiteral("⊘") : QString());
        suppress_item_changed_ = false;
    }
    emit layer_lock_changed(qstr(layer_key), locked);
}

bool MapLayerTree::layer_is_visible(const std::string& layer_key) const {
    const auto it = layer_visible_.find(layer_key);
    return it == layer_visible_.end() || it->second;
}

bool MapLayerTree::layer_is_locked(const std::string& layer_key) const {
    const auto it = layer_locked_.find(layer_key);
    return it != layer_locked_.end() && it->second;
}

const void* MapLayerTree::identity_of(const Json& document) const {
    // The identity tag is the document's index inside documents_ (stable
    // across reconciles of the same set; position-keyed like Python id()
    // for a persisted object).
    for (std::size_t i = 0; i < documents_.size(); ++i) {
        if (documents_[i] == document) {
            return reinterpret_cast<const void*>(i + 1);
        }
    }
    return nullptr;
}

void MapLayerTree::rebuild_tree() {
    suppress_item_changed_ = true;
    const bool was_blocked = tree_->signalsBlocked();
    tree_->blockSignals(true);
    const auto items = reconcile_tree_items(
        tree_, {kRootKey},
        [](const std::string&) {
            auto* root = new QTreeWidgetItem(
                QStringList{QStringLiteral("图件")});
            root->setFlags(root->flags() & ~Qt::ItemIsSelectable);
            return root;
        },
        [](QTreeWidgetItem* item, const std::string&) {
            if (item->text(0) != QStringLiteral("图件")) {
                item->setText(0, QStringLiteral("图件"));
            }
            item->setExpanded(true);
        });
    QTreeWidgetItem* root = items.at(kRootKey);

    std::vector<std::string> doc_keys;
    doc_keys.reserve(documents_.size());
    for (std::size_t i = 0; i < documents_.size(); ++i) {
        doc_keys.push_back(document_key(
            documents_[i], reinterpret_cast<const void*>(i + 1)));
    }
    const auto doc_map = reconcile_tree_items(
        tree_, doc_keys,
        [](const std::string&) {
            auto* item = new QTreeWidgetItem(
                QStringList{QStringLiteral("未命名图件"), QString()});
            item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
            return item;
        },
        [this](QTreeWidgetItem* item, const std::string& key) {
            const Json* doc = nullptr;
            for (std::size_t i = 0; i < documents_.size(); ++i) {
                if (document_key(
                        documents_[i],
                        reinterpret_cast<const void*>(i + 1)) == key) {
                    doc = &documents_[i];
                    break;
                }
            }
            const std::string name =
                doc != nullptr
                    ? field_value_str(*doc, "name", "未命名图件")
                    : std::string("未命名图件");
            const QString qname = qstr(name.empty() ? "未命名图件" : name);
            if (item->text(0) != qname) {
                item->setText(0, qname);
            }
            item->setData(0, kTagRole, QStringLiteral("doc"));
            item->setData(0, kKeyRole, qstr(key));
        },
        root);
    doc_items_.clear();
    doc_items_.reserve(documents_.size());
    for (const std::string& key : doc_keys) {
        doc_items_.push_back(doc_map.at(key));
    }

    // The active document (or the last one as the fallback) carries the
    // layer subtree; every other document's children are stripped.
    QTreeWidgetItem* populated_item = nullptr;
    const Json* populated_doc = nullptr;
    for (std::size_t i = 0; i < documents_.size(); ++i) {
        if (active_document_ != nullptr &&
            documents_[i] == *active_document_) {
            reconcile_document_children(doc_items_[i], documents_[i]);
            populated_item = doc_items_[i];
            populated_doc = &documents_[i];
        }
    }
    if (active_document_ == nullptr && !doc_items_.empty()) {
        reconcile_document_children(doc_items_.back(), documents_.back());
        populated_item = doc_items_.back();
        populated_doc = &documents_.back();
    }
    for (std::size_t i = 0; i < doc_items_.size(); ++i) {
        if (doc_items_[i] != populated_item) {
            reconcile_tree_items(
                tree_, {},
                [](const std::string&) { return new QTreeWidgetItem(); },
                [](QTreeWidgetItem*, const std::string&) {},
                doc_items_[i]);
        }
    }
    populated_document_ = populated_doc;
    tree_->blockSignals(was_blocked);
    suppress_item_changed_ = false;
}

void MapLayerTree::reconcile_document_children(QTreeWidgetItem* parent,
                                               const Json& document) {
    populated_document_ = &document;
    const Json ref_layers =
        field_value(document, "reference_layers", Json::array());
    const bool has_refs = ref_layers.is_array() && !ref_layers.empty();
    std::vector<std::string> child_keys;
    for (const char* key : kLayerKeys) {
        child_keys.push_back(std::string("layer:") + key);
    }
    if (has_refs) {
        child_keys.push_back(kRefGroupKey);
    }
    const bool first_population = parent->childCount() == 0;
    const auto items = reconcile_tree_items(
        tree_, child_keys,
        [](const std::string& key) {
            if (key == kRefGroupKey) {
                auto* group = new QTreeWidgetItem(
                    QStringList{QStringLiteral("参考图层"), QString()});
                group->setFlags(Qt::ItemIsEnabled);
                return group;
            }
            auto* item = new QTreeWidgetItem(QStringList{QString(), QString()});
            item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsUserCheckable |
                           Qt::ItemIsSelectable);
            return item;
        },
        [this](QTreeWidgetItem* item, const std::string& key) {
            if (key == kRefGroupKey) {
                if (item->text(0) != QStringLiteral("参考图层")) {
                    item->setText(0, QStringLiteral("参考图层"));
                }
                return;
            }
            const std::string layer_key = key.substr(6);  // "layer:" prefix
            const auto& labels = layer_labels();
            const auto it = labels.find(layer_key);
            const QString label =
                qstr(it != labels.end() ? it->second : layer_key);
            if (item->text(0) != label) {
                item->setText(0, label);
            }
            item->setData(0, kTagRole, QStringLiteral("layer"));
            item->setData(0, kKeyRole, qstr(layer_key));
            item->setCheckState(0, layer_is_visible(layer_key)
                                       ? Qt::Checked
                                       : Qt::Unchecked);
            const QString mark =
                layer_is_locked(layer_key) ? QStringLiteral("⊘")
                                           : QString();
            if (item->text(1) != mark) {
                item->setText(1, mark);
            }
        },
        parent);
    layer_items_.clear();
    for (const char* key : kLayerKeys) {
        layer_items_[key] = items.at(std::string("layer:") + key);
    }
    // Only the first population expands (switching the active document or
    // the initial bind); same-key refresh keeps the user's collapse state.
    if (first_population) {
        parent->setExpanded(true);
    }
    if (!has_refs) {
        return;
    }
    QTreeWidgetItem* ref_group = items.at(kRefGroupKey);
    const bool ref_first = ref_group->childCount() == 0;
    std::vector<std::string> ref_keys;
    for (std::size_t i = 0; i < ref_layers.size(); ++i) {
        ref_keys.push_back(reference_layer_key(
            ref_layers.at(i), reinterpret_cast<const void*>(i + 1)));
    }
    reconcile_tree_items(
        tree_, ref_keys,
        [](const std::string&) {
            auto* item = new QTreeWidgetItem(QStringList{QString(), QString()});
            item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
            return item;
        },
        [this, &ref_layers](QTreeWidgetItem* item, const std::string& key) {
            const Json* layer = nullptr;
            for (std::size_t i = 0; i < ref_layers.size(); ++i) {
                if (reference_layer_key(
                        ref_layers.at(i),
                        reinterpret_cast<const void*>(i + 1)) == key) {
                    layer = &ref_layers.at(i);
                    break;
                }
            }
            std::string name =
                layer != nullptr
                    ? field_value_str(*layer, "name", "未命名参考图层")
                    : std::string("未命名参考图层");
            const std::string status =
                layer != nullptr ? field_value_str(*layer, "status", "")
                                 : std::string();
            if (status == "offline") {
                name += " (离线)";
            } else if (status == "failed") {
                name += " (失败)";
            }
            const QString qname = qstr(name);
            if (item->text(0) != qname) {
                item->setText(0, qname);
            }
            item->setData(0, kTagRole, QStringLiteral("reference"));
        },
        ref_group);
    if (ref_first) {
        ref_group->setExpanded(true);
    }
}

void MapLayerTree::on_current_item_changed(QTreeWidgetItem* current) {
    if (current == nullptr) {
        return;
    }
    const QString tag = current->data(0, kTagRole).toString();
    if (tag != QLatin1String("doc")) {
        // Layer / reference rows never change the active document.
        return;
    }
    const std::string key =
        current->data(0, kKeyRole).toString().toStdString();
    const Json* doc = nullptr;
    for (std::size_t i = 0; i < documents_.size(); ++i) {
        if (document_key(documents_[i],
                         reinterpret_cast<const void*>(i + 1)) == key) {
            doc = &documents_[i];
            break;
        }
    }
    if (doc == nullptr) {
        return;
    }
    if (active_document_ == nullptr || *doc != *active_document_) {
        active_document_ = doc;
        rebuild_tree();
        for (QTreeWidgetItem* item : doc_items_) {
            if (item->data(0, kKeyRole).toString().toStdString() == key) {
                tree_->blockSignals(true);
                tree_->setCurrentItem(item);
                item->setExpanded(true);
                tree_->blockSignals(false);
                break;
            }
        }
        emit document_selected(*doc);
    }
}

void MapLayerTree::on_item_changed(QTreeWidgetItem* item, int column) {
    if (suppress_item_changed_ || item == nullptr) {
        return;
    }
    if (item->data(0, kTagRole).toString() != QLatin1String("layer")) {
        return;
    }
    const std::string layer_key =
        item->data(0, kKeyRole).toString().toStdString();
    if (column == 0) {
        const bool visible = item->checkState(0) == Qt::Checked;
        if (layer_visible_[layer_key] != visible) {
            layer_visible_[layer_key] = visible;
            emit layer_visibility_changed(qstr(layer_key), visible);
        }
    }
}

std::vector<std::string> MapLayerTree::document_keys() const {
    std::vector<std::string> keys;
    for (QTreeWidgetItem* item : doc_items_) {
        keys.push_back(item->data(0, kKeyRole).toString().toStdString());
    }
    return keys;
}

std::vector<std::string> MapLayerTree::layer_item_keys() const {
    // Canonical LAYER_KEYS order (Python tuple order) — not the std::map
    // storage order.
    std::vector<std::string> keys;
    keys.reserve(layer_items_.size());
    for (const char* key : kLayerKeys) {
        if (layer_items_.find(key) != layer_items_.end()) {
            keys.emplace_back(key);
        }
    }
    return keys;
}

}  // namespace pwb::ui_map
