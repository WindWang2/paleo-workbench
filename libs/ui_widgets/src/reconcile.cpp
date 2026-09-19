#include "pwb/ui_widgets/reconcile.hpp"

#include <set>

namespace pwb::ui_widgets {
namespace {

// Dedupe preserving first occurrence (review P2-10: duplicated keys
// would otherwise let same-key extra items live outside the differ).
std::vector<QString> deduped_keys(const std::vector<QString>& keys) {
    std::set<QString> seen;
    std::vector<QString> out;
    out.reserve(keys.size());
    for (const QString& key : keys) {
        // Python `if k is not None` — empty string is a valid key there
        // (str key space); keep it here too.
        if (seen.insert(key).second) {
            out.push_back(key);
        }
    }
    return out;
}

int tree_row_of(QTreeWidgetItem* container, QTreeWidgetItem* item) {
    for (int i = 0; i < container->childCount(); ++i) {
        if (container->child(i) == item) return i;
    }
    return -1;
}

QString tree_item_key(QTreeWidgetItem* item) {
    return item->data(0, kReconcileKeyRole).toString();
}

bool tree_item_has_key(QTreeWidgetItem* item) {
    const QVariant v = item->data(0, kReconcileKeyRole);
    return v.isValid() && !v.isNull();
}

QString list_item_key(QListWidgetItem* item) {
    return item->data(kReconcileKeyRole).toString();
}

bool list_item_has_key(QListWidgetItem* item) {
    const QVariant v = item->data(kReconcileKeyRole);
    return v.isValid() && !v.isNull();
}

}  // namespace

QString item_key(QTreeWidgetItem* item) {
    return item == nullptr ? QString() : tree_item_key(item);
}

QString item_key(QListWidgetItem* item) {
    return item == nullptr ? QString() : list_item_key(item);
}

std::map<QString, QTreeWidgetItem*> reconcile_widget_items(
    QTreeWidget* widget,
    const std::vector<QString>& keys,
    const std::function<QTreeWidgetItem*(const QString&)>& make_item,
    const std::function<void(QTreeWidgetItem*, const QString&)>& update_item,
    QTreeWidgetItem* parent_item) {
    QTreeWidgetItem* container = parent_item != nullptr
                                     ? parent_item
                                     : widget->invisibleRootItem();
    std::vector<QTreeWidgetItem*> existing;
    existing.reserve(size_t(container->childCount()));
    for (int i = 0; i < container->childCount(); ++i) {
        existing.push_back(container->child(i));
    }

    std::map<QString, QTreeWidgetItem*> by_key;
    for (QTreeWidgetItem* item : existing) {
        // Python `key is not None` — keyless items never enter by_key
        // (they get removed in step 1 below).
        if (tree_item_has_key(item)) {
            const QString key = tree_item_key(item);
            if (by_key.find(key) == by_key.end()) {
                by_key[key] = item;
            }
        }
    }

    const std::vector<QString> target_keys = deduped_keys(keys);
    const std::set<QString> wanted(target_keys.begin(), target_keys.end());

    // 1) Remove vanished keys. Python removes only items whose key is
    //    None or not in wanted — items with NO stored key are removed
    //    too (key None not in wanted). Items with keys still wanted but
    //    losing the by_key race (duplicates) survive — frozen quirk.
    //    Removed items lose all references in Python (GC frees them) ->
    //    delete here.
    for (QTreeWidgetItem* item : existing) {
        const QString key = tree_item_key(item);
        if (!tree_item_has_key(item) ||
            wanted.find(key) == wanted.end()) {
            container->removeChild(item);
            delete item;
            by_key.erase(key);
        }
    }

    // 2) Add missing keys (item enters the container first, then the
    //    caller refreshes its content).
    for (const QString& key : target_keys) {
        if (by_key.find(key) == by_key.end()) {
            QTreeWidgetItem* item = make_item(key);
            item->setData(0, kReconcileKeyRole, key);
            if (parent_item != nullptr) {
                parent_item->addChild(item);
            } else {
                widget->addTopLevelItem(item);
            }
            by_key[key] = item;
        }
    }

    // 3) Refresh content (zero structural ops when the key order is
    //    unchanged).
    for (const QString& key : target_keys) {
        update_item(by_key[key], key);
    }

    // 4) Order alignment (take/insert only when out of order — keeps
    //    selection and expand state).
    std::vector<QString> current_keys;
    current_keys.reserve(size_t(container->childCount()));
    for (int i = 0; i < container->childCount(); ++i) {
        current_keys.push_back(tree_item_key(container->child(i)));
    }
    if (current_keys != target_keys) {
        for (int position = 0; position < int(target_keys.size());
             ++position) {
            QTreeWidgetItem* item = by_key[target_keys[size_t(position)]];
            const int row = tree_row_of(container, item);
            if (row != position && row >= 0) {
                QTreeWidgetItem* child = container->takeChild(row);
                container->insertChild(position, child);
            }
        }
    }
    return by_key;
}

std::map<QString, QListWidgetItem*> reconcile_widget_items(
    QListWidget* widget,
    const std::vector<QString>& keys,
    const std::function<QListWidgetItem*(const QString&)>& make_item,
    const std::function<void(QListWidgetItem*, const QString&)>& update_item) {
    std::vector<QListWidgetItem*> existing;
    existing.reserve(size_t(widget->count()));
    for (int i = 0; i < widget->count(); ++i) {
        existing.push_back(widget->item(i));
    }

    std::map<QString, QListWidgetItem*> by_key;
    for (QListWidgetItem* item : existing) {
        if (list_item_has_key(item)) {
            const QString key = list_item_key(item);
            if (by_key.find(key) == by_key.end()) {
                by_key[key] = item;
            }
        }
    }

    const std::vector<QString> target_keys = deduped_keys(keys);
    const std::set<QString> wanted(target_keys.begin(), target_keys.end());

    // 1) Remove vanished keys (same rules as the tree path).
    for (QListWidgetItem* item : existing) {
        const QString key = list_item_key(item);
        if (!list_item_has_key(item) ||
            wanted.find(key) == wanted.end()) {
            delete widget->takeItem(widget->row(item));
            by_key.erase(key);
        }
    }

    // 2) Add missing keys.
    for (const QString& key : target_keys) {
        if (by_key.find(key) == by_key.end()) {
            QListWidgetItem* item = make_item(key);
            item->setData(kReconcileKeyRole, key);
            widget->addItem(item);
            by_key[key] = item;
        }
    }

    // 3) Refresh content.
    for (const QString& key : target_keys) {
        update_item(by_key[key], key);
    }

    // 4) Order alignment.
    std::vector<QString> current_keys;
    current_keys.reserve(size_t(widget->count()));
    for (int i = 0; i < widget->count(); ++i) {
        current_keys.push_back(list_item_key(widget->item(i)));
    }
    if (current_keys != target_keys) {
        for (int position = 0; position < int(target_keys.size());
             ++position) {
            QListWidgetItem* item = by_key[target_keys[size_t(position)]];
            const int row = widget->row(item);
            if (row != position && row >= 0) {
                widget->takeItem(row);
                widget->insertItem(position, item);
            }
        }
    }
    return by_key;
}

}  // namespace pwb::ui_widgets
