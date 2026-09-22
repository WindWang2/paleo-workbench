#include <pwb/ui_map/item_reconcile.hpp>

#include <QListWidget>
#include <QTreeWidget>

#include <set>

namespace pwb::ui_map {

namespace {

// Deduplicate the target key sequence (first-seen order, Python parity).
std::vector<std::string> dedupe(const std::vector<std::string>& keys) {
    std::vector<std::string> out;
    std::set<std::string> seen;
    for (const auto& key : keys) {
        if (seen.insert(key).second) {
            out.push_back(key);
        }
    }
    return out;
}

QString qkey(const std::string& key) {
    return QString::fromUtf8(key.data(), static_cast<qsizetype>(key.size()));
}

std::string tree_key(QTreeWidgetItem* item) {
    const QVariant value = item->data(0, kItemKeyRole);
    return value.isValid() ? value.toString().toStdString() : std::string();
}

std::string list_key(QListWidgetItem* item) {
    const QVariant value = item->data(kItemKeyRole);
    return value.isValid() ? value.toString().toStdString() : std::string();
}

}  // namespace

std::map<std::string, QTreeWidgetItem*> reconcile_tree_items(
    QTreeWidget* tree, const std::vector<std::string>& keys_in,
    const std::function<QTreeWidgetItem*(const std::string&)>& make_item,
    const std::function<void(QTreeWidgetItem*, const std::string&)>&
        update_item,
    QTreeWidgetItem* parent_item) {
    QTreeWidgetItem* container = parent_item != nullptr
                                     ? parent_item
                                     : tree->invisibleRootItem();
    std::vector<QTreeWidgetItem*> existing;
    existing.reserve(container->childCount());
    for (int i = 0; i < container->childCount(); ++i) {
        existing.push_back(container->child(i));
    }
    std::map<std::string, QTreeWidgetItem*> by_key;
    for (QTreeWidgetItem* item : existing) {
        const std::string key = tree_key(item);
        if (!key.empty() && by_key.find(key) == by_key.end()) {
            by_key[key] = item;
        }
    }
    const std::vector<std::string> target_keys = dedupe(keys_in);
    const std::set<std::string> wanted(target_keys.begin(),
                                       target_keys.end());

    // 1) Remove vanished keys.
    for (QTreeWidgetItem* item : existing) {
        const std::string key = tree_key(item);
        if (key.empty() || !wanted.count(key)) {
            container->removeChild(item);
            // R2-27: removeChild unparents but does NOT delete — removed
            // items leaked with their whole subtrees on every
            // active-document switch (the list variant deletes via
            // takeItem). QObject-style: heap QTreeWidgetItems need an
            // explicit delete once detached.
            delete item;
            by_key.erase(key);
        }
    }
    // 2) Append missing keys (items join before the caller refreshes them).
    for (const std::string& key : target_keys) {
        if (by_key.find(key) == by_key.end()) {
            QTreeWidgetItem* item = make_item(key);
            item->setData(0, kItemKeyRole, qkey(key));
            container->addChild(item);
            by_key[key] = item;
        }
    }
    // 3) Refresh contents (zero structural ops when the key order held).
    for (const std::string& key : target_keys) {
        update_item(by_key.at(key), key);
    }
    // 4) Realign order only when it drifted (take/insert keeps selection +
    //    expanded state).
    std::vector<std::string> current_keys;
    for (int i = 0; i < container->childCount(); ++i) {
        current_keys.push_back(tree_key(container->child(i)));
    }
    if (current_keys != target_keys) {
        for (std::size_t position = 0; position < target_keys.size();
             ++position) {
            QTreeWidgetItem* item = by_key.at(target_keys[position]);
            int row = -1;
            for (int i = 0; i < container->childCount(); ++i) {
                if (container->child(i) == item) {
                    row = i;
                    break;
                }
            }
            if (row >= 0 && row != static_cast<int>(position)) {
                QTreeWidgetItem* child = container->takeChild(row);
                container->insertChild(static_cast<int>(position), child);
            }
        }
    }
    std::map<std::string, QTreeWidgetItem*> result;
    for (const std::string& key : target_keys) {
        result[key] = by_key.at(key);
    }
    return result;
}

std::map<std::string, QListWidgetItem*> reconcile_list_items(
    QListWidget* list, const std::vector<std::string>& keys_in,
    const std::function<QListWidgetItem*(const std::string&)>& make_item,
    const std::function<void(QListWidgetItem*, const std::string&)>&
        update_item) {
    std::vector<QListWidgetItem*> existing;
    existing.reserve(list->count());
    for (int i = 0; i < list->count(); ++i) {
        existing.push_back(list->item(i));
    }
    std::map<std::string, QListWidgetItem*> by_key;
    for (QListWidgetItem* item : existing) {
        const std::string key = list_key(item);
        if (!key.empty() && by_key.find(key) == by_key.end()) {
            by_key[key] = item;
        }
    }
    const std::vector<std::string> target_keys = dedupe(keys_in);
    const std::set<std::string> wanted(target_keys.begin(),
                                       target_keys.end());

    for (QListWidgetItem* item : existing) {
        const std::string key = list_key(item);
        if (key.empty() || !wanted.count(key)) {
            delete list->takeItem(list->row(item));
            by_key.erase(key);
        }
    }
    for (const std::string& key : target_keys) {
        if (by_key.find(key) == by_key.end()) {
            QListWidgetItem* item = make_item(key);
            item->setData(kItemKeyRole, qkey(key));
            list->addItem(item);
            by_key[key] = item;
        }
    }
    for (const std::string& key : target_keys) {
        update_item(by_key.at(key), key);
    }
    std::vector<std::string> current_keys;
    for (int i = 0; i < list->count(); ++i) {
        current_keys.push_back(list_key(list->item(i)));
    }
    if (current_keys != target_keys) {
        for (std::size_t position = 0; position < target_keys.size();
             ++position) {
            QListWidgetItem* item = by_key.at(target_keys[position]);
            const int row = list->row(item);
            if (row >= 0 && row != static_cast<int>(position)) {
                QListWidgetItem* moved = list->takeItem(row);
                list->insertItem(static_cast<int>(position), moved);
            }
        }
    }
    std::map<std::string, QListWidgetItem*> result;
    for (const std::string& key : target_keys) {
        result[key] = by_key.at(key);
    }
    return result;
}

}  // namespace pwb::ui_map
