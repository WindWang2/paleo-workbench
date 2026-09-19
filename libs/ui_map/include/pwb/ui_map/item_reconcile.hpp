#pragma once

// UI-05 — item_reconcile: C++ port of ui/modelview/reconcile.py's
// reconcile_widget_items — keyed diff sync for QTreeWidget/QListWidget
// child sets (V11 D2 ⑮: item identity, expanded state, selection and
// scroll position survive status refresh).
//
// Contract (Python parity):
//   * caller gives the ordered stable business keys + make/update
//     callbacks;
//   * returns {key -> item}; existing items with unchanged key order are
//     preserved untouched;
//   * vanished keys removed, missing keys appended, order realigned with
//     take/insert only when the sequence actually changed;
//   * duplicate target keys are deduped preserving first-seen order
//     (P2-10: same-key pairs must not both survive the diff).

#include <functional>
#include <map>
#include <string>
#include <vector>

class QListWidget;
class QListWidgetItem;
class QTreeWidget;
class QTreeWidgetItem;

namespace pwb::ui_map {

// The key role: Qt::UserRole + 0x10D6 — the "diff" segment (Python _KEY_ROLE).
inline constexpr int kItemKeyRole = 0x0100 + 0x10D6;  // Qt::UserRole is 0x0100

// Tree reconcile. parent_item == nullptr targets the tree's top level.
// Returns key -> item for every target key.
std::map<std::string, QTreeWidgetItem*> reconcile_tree_items(
    QTreeWidget* tree, const std::vector<std::string>& keys,
    const std::function<QTreeWidgetItem*(const std::string&)>& make_item,
    const std::function<void(QTreeWidgetItem*, const std::string&)>&
        update_item,
    QTreeWidgetItem* parent_item = nullptr);

// List reconcile (top-level only — QListWidget has no hierarchy).
std::map<std::string, QListWidgetItem*> reconcile_list_items(
    QListWidget* list, const std::vector<std::string>& keys,
    const std::function<QListWidgetItem*(const std::string&)>& make_item,
    const std::function<void(QListWidgetItem*, const std::string&)>&
        update_item);

}  // namespace pwb::ui_map
