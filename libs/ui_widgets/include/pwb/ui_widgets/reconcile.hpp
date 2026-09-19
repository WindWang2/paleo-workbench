#pragma once

// UI-02 — keyed reconcile for QTreeWidget/QListWidget (kill
// clear+rebuild), ported from paleo_workbench/ui/modelview/reconcile.py.
//
// Contract (01-ui-audit D2 ⑮):
//  - caller supplies the TARGET key sequence (ordered, stable business
//    keys) plus make_item(key)/update_item(item, key) callbacks;
//  - returns key -> item map; surviving items keep their object
//    identity (expand/selection/scroll/custom data preserved);
//  - removed keys are taken, new keys appended, order realigned only
//    when the current order differs;
//  - explicitly NOT: pagination, filtering, sorting (model-layer jobs).

#include <QListWidget>
#include <QListWidgetItem>
#include <QString>
#include <QTreeWidget>
#include <QTreeWidgetItem>

#include <functional>
#include <map>
#include <vector>

namespace pwb::ui_widgets {

// Key-role segment reserved for the differ (0x10D6 — same value as the
// Python _KEY_ROLE so item keys are interchangeable).
inline constexpr int kReconcileKeyRole = Qt::UserRole + 0x10D6;

// Read the key reconcile_widget_items wrote (page-side lookup).
QString item_key(QTreeWidgetItem* item);
QString item_key(QListWidgetItem* item);

// Sync the children of `widget` (or `parent_item`, nullptr = top level)
// to `keys`. Duplicate target keys dedupe preserving first occurrence
// (review P2-10); items whose key is absent from the target are removed.
std::map<QString, QTreeWidgetItem*> reconcile_widget_items(
    QTreeWidget* widget,
    const std::vector<QString>& keys,
    const std::function<QTreeWidgetItem*(const QString& key)>& make_item,
    const std::function<void(QTreeWidgetItem* item, const QString& key)>&
        update_item,
    QTreeWidgetItem* parent_item = nullptr);

std::map<QString, QListWidgetItem*> reconcile_widget_items(
    QListWidget* widget,
    const std::vector<QString>& keys,
    const std::function<QListWidgetItem*(const QString& key)>& make_item,
    const std::function<void(QListWidgetItem* item, const QString& key)>&
        update_item);

}  // namespace pwb::ui_widgets
