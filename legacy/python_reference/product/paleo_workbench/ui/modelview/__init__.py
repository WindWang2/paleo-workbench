"""V11 共享 Model/View 基础层（goal §8）。

动机（01-ui-audit D2）：页面级表格/树/列表仍大量使用 item-per-cell 的
QTableWidget/QTreeWidget/QListWidget 全量重建模式。旗舰面（Data 资产表、
属性表、任务中心、explorer）已经各自实现了正确的虚拟/差分模型，但模式
没有被抽成可复用组件，导致 15 个次级面板各自复制全量重建。

本包只做**表现层基础设施**，不含任何业务规则（不触碰 catalog 语义 /
QGIS 行为）。三个组件：

* :mod:`object_table` —— 行为对象的虚拟表模型 + 稳定键选择适配器
  （100k 行零 QTableWidgetItem；模式取自 ``composite_attribute_table``
  与 ``paged_asset_model`` 的已验证实现）。
* :mod:`async_query` —— GUI 线程契约（goal §9）的通用异步查询：
  epoch + latest-only + 迟到拒绝 + 关闭即停，基于 OwnedWorkerJob。
* :mod:`reconcile` —— QTreeWidget/QListWidget 的按键差分同步
  （模式取自 ``workstation/explorer._reconcile_children`` 与
  ``stratigraphy_correlation_page._sync_well_list``），消除 clear+rebuild。

选型规则（goal §8 分类）：小而固定（<100 行、静态）继续 widget；
中大数据或频繁重建的表面迁移到本包组件。
"""
from paleo_workbench.ui.modelview.async_query import AsyncQuery
from paleo_workbench.ui.modelview.object_table import (
    ColumnSpec,
    ObjectTableModel,
    StableSelection,
    bind_table_defaults,
)
from paleo_workbench.ui.modelview.reconcile import reconcile_widget_items

__all__ = [
    "AsyncQuery",
    "ColumnSpec",
    "ObjectTableModel",
    "StableSelection",
    "bind_table_defaults",
    "reconcile_widget_items",
]
