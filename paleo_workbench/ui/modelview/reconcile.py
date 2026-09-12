"""QTreeWidget/QListWidget 按键差分同步（消灭 clear+rebuild）。

模式取自两处已验证实现：``workstation/explorer._reconcile_children``
（标准项树键控差分）与 ``stratigraphy_correlation_page._sync_well_list``
（万井级列表增量复用）。V11 把它抽成通用工具，供仍保留 widget 形态
的小中型表面（图层树、文档列表、参考层清单等，01-ui-audit D2 ⑮）使用。

契约：

* 调用方给出**目标键序列**（有序、稳定业务键）与两个回调：
  ``make_item(key) -> item``（新建）和 ``update_item(item, key)``（刷新）；
* 返回 ``dict[key, item]``；已存在且键序不变的项对象**原样保留**
  （展开态/选择/滚动/自定义数据不丢）；
* 移除消失键、追加新增键、按目标顺序重排（仅当顺序变化时 take/insert）；
* 明确不做的：分页、过滤、排序——这些属于模型层职责。
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem

_KEY_ROLE = Qt.ItemDataRole.UserRole + 0x10D6  # D666 → “差分”专用段，避免与页面其它 UserRole 混用


def _item_key(item: QTreeWidgetItem | QListWidgetItem) -> str | None:
    return item.data(0, _KEY_ROLE) if isinstance(item, QTreeWidgetItem) else item.data(_KEY_ROLE)


def _set_item_key(item: QTreeWidgetItem | QListWidgetItem, key: str) -> None:
    if isinstance(item, QTreeWidgetItem):
        item.setData(0, _KEY_ROLE, key)
    else:
        item.setData(_KEY_ROLE, key)


def reconcile_widget_items(
    widget: QTreeWidget | QListWidget,
    keys: Sequence[str],
    *,
    make_item: Callable[[str], QTreeWidgetItem | QListWidgetItem],
    update_item: Callable[[QTreeWidgetItem | QListWidgetItem, str], None],
    parent_item: QTreeWidgetItem | None = None,
) -> dict[str, QTreeWidgetItem | QListWidgetItem]:
    """把 widget（或某父项）的子项集合同步为目标键序列。

    ``parent_item`` 仅对 QTreeWidget 有意义（None = 顶层）。
    """
    if isinstance(widget, QTreeWidget):
        container = parent_item if parent_item is not None else widget.invisibleRootItem()
        existing: list[QTreeWidgetItem] = [container.child(i) for i in range(container.childCount())]
    else:
        existing = [widget.item(i) for i in range(widget.count())]

    by_key: dict[str, QTreeWidgetItem | QListWidgetItem] = {}
    for item in existing:
        key = _item_key(item)
        if key is not None and key not in by_key:
            by_key[key] = item

    target_keys = [k for k in keys if k is not None]
    # 重复键去重（保序）：重复键会让同键两项都存活于差分之外（评审 P2-10）。
    seen: set[str] = set()
    deduped: list[str] = []
    for key in target_keys:
        if key not in seen:
            seen.add(key)
            deduped.append(key)
    target_keys = deduped
    wanted = set(target_keys)

    # 1) 移除消失键
    for item in existing:
        key = _item_key(item)
        if key is None or key not in wanted:
            if isinstance(widget, QTreeWidget):
                container.removeChild(item)  # type: ignore[union-attr]
            else:
                widget.takeItem(widget.row(item))
            by_key.pop(key, None)

    # 2) 新增缺失键（新项先入容器，再交调用方刷新内容）
    for key in target_keys:
        if key not in by_key:
            item = make_item(key)
            _set_item_key(item, key)
            if isinstance(widget, QTreeWidget):
                if parent_item is not None:
                    parent_item.addChild(item)
                else:
                    widget.addTopLevelItem(item)
            else:
                widget.addItem(item)
            by_key[key] = item

    # 3) 刷新内容（键序未变时零结构操作）
    for key in target_keys:
        update_item(by_key[key], key)

    # 4) 顺序对齐（只在失序时 take/insert，保选择与展开态）
    current_keys = []
    if isinstance(widget, QTreeWidget):
        current_keys = [
            _item_key(container.child(i)) for i in range(container.childCount())
        ]
    else:
        current_keys = [_item_key(widget.item(i)) for i in range(widget.count())]
    if current_keys != target_keys:
        for position, key in enumerate(target_keys):
            item = by_key[key]
            if isinstance(widget, QTreeWidget):
                row = _tree_row_of(container, item)  # type: ignore[union-attr]
                if row != position:
                    child = container.takeChild(row)  # type: ignore[union-attr]
                    container.insertChild(position, child)  # type: ignore[union-attr]
            else:
                row = widget.row(item)  # type: ignore[call-arg]
                if row != position:
                    widget.takeItem(row)
                    widget.insertItem(position, item)

    return by_key


def _tree_row_of(container: QTreeWidgetItem, item: QTreeWidgetItem) -> int:
    for i in range(container.childCount()):
        if container.child(i) is item:
            return i
    return -1


def item_key(item: QTreeWidgetItem | QListWidgetItem) -> str | None:
    """读取 :func:`reconcile_widget_items` 写入的键（页面侧查询用）。"""
    return _item_key(item)


__all__ = ["reconcile_widget_items", "item_key"]
