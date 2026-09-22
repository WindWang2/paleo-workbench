"""V11 goal §8 Model/View 迁移（数据侧表面）结构契约测试。

覆盖 01-ui-audit D2 ①③⑤⑧⑨⑩⑬ 迁移后的不变量：

* **结构规模**：井点表面（rank-1 风险）在 100k 行下零 QTableWidgetItem
  分配、``set_rows`` 有界时间内完成、中段行经 ``model.data()`` 取值；
* **差分重置**：同一键集合换新对象 → 不发 modelReset（dataChanged 路径），
  StableSelection 跨刷新保选择；
* **reconcile**：可视化总览资产清单键集不变时项对象身份保留；
* **搜索去抖**：textChanged 只重启定时器，停顿 200ms 后重载恰好一次；
* **目录健康 / 拓扑 / 资源表面**：N 行填充 → 模型 rowCount N、宿主内零
  item-per-cell widget（QTableWidget/QTableWidgetItem）。

conftest 已处理 offscreen QApplication（pytest-qt ``qtbot`` 常规用法）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QCoreApplication, QItemSelectionModel, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QTableView, QTableWidget

from paleo_workbench.catalog.audit import AuditIssue, AuditReport
from paleo_workbench.ui import style
from paleo_workbench.ui.pages.catalog_health_dialog import CatalogHealthDialog
from paleo_workbench.ui.pages.map_topology_issue_panel import MapTopologyIssuePanel
from paleo_workbench.ui.pages.tag_widgets import TagManagerDialog
from paleo_workbench.ui.pages.visualization_summary_panel import (
    VisualizationSummaryPanel,
)
from paleo_workbench.ui.pages.well_table_panel import WellTablePanel


# -- helpers -------------------------------------------------------------------


@dataclass
class _FakeRow:
    """轻量 WellTableRow 替身（10 万行构造不吃 pydantic 验证预算）。"""

    well_id: str
    name: str
    x: float
    y: float
    z: float | None = None
    H_s: float | None = None
    H_t: float | None = None
    R_s: float | None = None
    q: float = 1.0
    b_i: float = 1.0
    qc_flag: str = "ok"
    qc_z_star: float | None = None


def _big_well_table(n: int) -> SimpleNamespace:
    rows = [
        _FakeRow(
            well_id=f"w{i}",
            name=f"W{i}",
            x=float(i % 1000),
            y=float(i % 500),
            z=1000.0 + (i % 37),
            H_s=10.0,
            H_t=40.0,
            R_s=0.25,
            qc_flag="outlier" if i % 997 == 0 else "ok",
        )
        for i in range(n)
    ]
    return SimpleNamespace(
        id="wtable-scale",
        name="Scale",
        target_horizon="H1",
        factor_type="砂地比",
        rows=rows,
    )


def _hex(color) -> str:
    return color.name().lstrip("#").lower()


def _token(token_name: str) -> str:
    return style.palette()[token_name].lstrip("#").lower()


def _select_row(panel: WellTablePanel, key: str) -> None:
    index = panel._model.index_for_key(key)
    assert index.isValid()
    panel.table.selectionModel().select(
        index,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )


@pytest.fixture
def counting_table_items(monkeypatch):
    """计数本测试期间构造的 QTableWidgetItem（迁移面应为 0）。"""
    import PySide6.QtWidgets as widgets

    counter = SimpleNamespace(count=0)
    real = widgets.QTableWidgetItem

    class _CountingItem(real):
        def __init__(self, *args, **kwargs):
            counter.count += 1
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(widgets, "QTableWidgetItem", _CountingItem)
    return counter


def _process_events(ms: int) -> None:
    """等待 ms 毫秒并泵事件（定时器去抖触发的驱动方式）。"""
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)


# -- 结构规模：井点表面 100k 行 ----------------------------------------------------


def test_well_table_panel_100k_rows_virtualized(qtbot, counting_table_items):
    """100k 行：QTableView + 模型 rowCount；零 item 分配；有界时间；中段可取值。"""
    panel = WellTablePanel()
    qtbot.addWidget(panel)

    started = time.perf_counter()
    panel.update_from_well_table(_big_well_table(100_000))
    elapsed = time.perf_counter() - started

    assert isinstance(panel.table, QTableView)
    assert not isinstance(panel.table, QTableWidget)
    assert panel.table.rowCount() == 100_000
    assert counting_table_items.count == 0, "井点表面仍按格分配 QTableWidgetItem"
    assert elapsed < 5.0, f"set_rows 100k 行耗时 {elapsed:.2f}s（>5s 预算）"

    # 中段行经模型取值（虚拟化 = 按需求值，无需真实滚动）。
    mid = 50_000
    assert panel._model.data(panel._model.index(mid, 0)) == f"W{mid}"
    # x 列走 _fmt：整数值去掉尾零。
    assert panel._model.data(panel._model.index(mid, 1)) == f"{mid % 1000}"


def test_well_table_panel_columns_and_qc_tokens(qtbot):
    """11 列齐全（顺序/标题不变）+ QC 列 token 前景（ok→SUCCESS、outlier→WARNING）。"""
    panel = WellTablePanel()
    qtbot.addWidget(panel)
    panel.update_from_well_table(_big_well_table(20))

    model = panel._model
    assert model.columnCount() == 11
    assert model.headerData(0, Qt.Orientation.Horizontal) == "井名"
    assert model.headerData(9, Qt.Orientation.Horizontal) == "QC"
    assert model.headerData(10, Qt.Orientation.Horizontal) == "z*"

    # i % 997 == 0 → 第 0 行是 outlier，其余 ok。
    ok_color = model.data(model.index(1, 9), Qt.ItemDataRole.ForegroundRole)
    outlier_color = model.data(model.index(0, 9), Qt.ItemDataRole.ForegroundRole)
    assert model.data(model.index(1, 9)) == "ok"
    assert model.data(model.index(0, 9)) == "outlier"
    assert _hex(ok_color) == _token("SUCCESS")
    assert _hex(outlier_color) == _token("WARNING")


def test_well_table_panel_empty_state(qtbot):
    panel = WellTablePanel()
    qtbot.addWidget(panel)
    panel.update_from_well_table(None)
    assert panel.table.isHidden()
    assert not panel.empty_label.isHidden()
    assert panel.table.rowCount() == 0


# -- set_rows 差分：同键新对象不发 modelReset ---------------------------------------


def test_set_rows_same_keys_no_model_reset(qtbot):
    panel = WellTablePanel()
    qtbot.addWidget(panel)
    panel.update_from_well_table(_big_well_table(200))

    resets: list[int] = []
    panel._model.modelReset.connect(lambda: resets.append(1))

    # 同键集合、全新对象：应走 dataChanged 路径（不发 modelReset）。
    panel.update_from_well_table(_big_well_table(200))
    assert resets == []
    assert panel.table.rowCount() == 200

    # 键集合变化（删行）：允许 modelReset。
    panel.update_from_well_table(_big_well_table(100))
    assert resets == [1]
    assert panel.table.rowCount() == 100


def test_stable_selection_preserved_across_refresh(qtbot):
    panel = WellTablePanel()
    qtbot.addWidget(panel)
    panel.update_from_well_table(_big_well_table(50))
    _select_row(panel, "w7")

    # 同键全量刷新（新对象）后，well_id=w7 仍被选中。
    panel.update_from_well_table(_big_well_table(50))
    selected_keys = [
        panel._model.key_for_index(idx)
        for idx in panel.table.selectionModel().selectedRows()
    ]
    assert "w7" in selected_keys


# -- reconcile：可视化总览清单项身份保留 ---------------------------------------------


def _viz_resource(i: int, name: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"r{i}",
        name=name or f"res-{i}.las",
        type="well_log",
        format="las",
    )


def test_visualization_summary_reconcile_preserves_item_identity(qtbot):
    panel = VisualizationSummaryPanel()
    qtbot.addWidget(panel)

    # 2 口 LAS 井 → 2 资源项 + 1 虚拟「连井剖面」条目（固定键）。
    panel.update_state([_viz_resource(1), _viz_resource(2)], [], [])
    assert panel.asset_list.count() == 3
    before = [panel.asset_list.item(i) for i in range(panel.asset_list.count())]

    # 同键集合（内容未变）：项对象身份不变（含虚拟连井条目）。
    panel.update_state([_viz_resource(1), _viz_resource(2)], [], [])
    after = [panel.asset_list.item(i) for i in range(panel.asset_list.count())]
    assert [id(item) for item in before] == [id(item) for item in after]

    # 名称变更仍走 update_item 原地刷新（不换项）。
    panel.update_state([_viz_resource(1, name="renamed.las"), _viz_resource(2)], [], [])
    assert panel.asset_list.item(0) is before[0]
    assert panel.asset_list.item(0).text().endswith("renamed.las")

    # 删到 1 口井：虚拟连井条目消失，剩余资源项身份不变。
    panel.update_state([_viz_resource(2)], [], [])
    assert panel.asset_list.count() == 1
    assert panel.asset_list.item(0) is before[1]


# -- 标签管理：搜索 200ms 去抖 -------------------------------------------------------


class _FakeTagService:
    """只支撑 tag_usage / search_tags 的桩（无需磁盘目录）。"""

    def __init__(self) -> None:
        self.usage_calls = 0
        self.search_calls = 0

    def tag_usage(self):
        self.usage_calls += 1
        return {
            "重点井": {"name": "重点井", "assets": 1, "versions": 0},
            "探井": {"name": "探井", "assets": 0, "versions": 0},
        }

    def search_tags(self, text: str):
        self.search_calls += 1
        return [SimpleNamespace(name=n) for n in ("重点井",) if text in n]

    def list_tags(self):
        return []


def test_tag_manager_search_debounced(qtbot):
    service = _FakeTagService()
    dlg = TagManagerDialog(service_provider=lambda: service)
    qtbot.addWidget(dlg)
    assert dlg.table.rowCount() == 2  # 初次全量加载（构造期，非去抖路径）

    baseline_usage = service.usage_calls
    baseline_search = service.search_calls

    # 连续击键：立即重载 NOT called（去抖窗口内只重启定时器）。
    dlg.search_input.setText("重")
    dlg.search_input.setText("重点")
    QCoreApplication.processEvents()
    assert service.usage_calls == baseline_usage
    assert service.search_calls == baseline_search
    assert dlg.table.rowCount() == 2  # 仍是未过滤的全表

    # 停顿超过去抖窗口：恰好重载一次，过滤生效。
    _process_events(dlg._SEARCH_DEBOUNCE_MS + 100)
    assert dlg.table.rowCount() == 1
    assert dlg.table.item(0, 0).text() == "重点井"
    assert service.usage_calls == baseline_usage + 1
    assert service.search_calls == baseline_search + 1


# -- 目录健康 / 拓扑问题面板：模型化填充 ---------------------------------------------


def _report(n: int, severity: str = "high") -> AuditReport:
    return AuditReport(
        issues=[
            AuditIssue(kind=f"kind_{i}", severity=severity, ref_id=f"ref-{i}", detail="d")
            for i in range(n)
        ],
        checked={"assets": 3, "versions": 3, "runs": 2, "tags": 1},
    )


def test_catalog_health_issue_table_virtualized(qtbot, counting_table_items):
    dlg = CatalogHealthDialog(None, service_provider=lambda: None)
    qtbot.addWidget(dlg)

    assert isinstance(dlg.issues_table, QTableView)
    assert not isinstance(dlg.issues_table, QTableWidget)
    assert not dlg.findChildren(QTableWidget)

    dlg.update_report(_report(25))
    assert dlg.issues_table.rowCount() == 25
    assert dlg._model.data(dlg._model.index(12, 1)) == "kind_12"
    assert dlg._model.data(dlg._model.index(0, 2)) == "ref-0"
    assert counting_table_items.count == 0

    # 无问题：空态覆盖出现，行数归零，摘要含问题计数。
    dlg.update_report(AuditReport(checked={}))
    assert dlg.issues_table.rowCount() == 0
    assert not dlg._empty_state.isHidden()
    assert "问题 0 项" in dlg.summary_label.text()


def test_catalog_health_severity_tokens(qtbot):
    dlg = CatalogHealthDialog(None, service_provider=lambda: None)
    qtbot.addWidget(dlg)
    dlg.update_report(_report(2, severity="high"))
    color = dlg._model.data(dlg._model.index(0, 0), Qt.ItemDataRole.ForegroundRole)
    assert color is not None
    assert _hex(color) == _token("ERROR_RED")


def test_map_topology_issue_panel_virtualized(qtbot, counting_table_items):
    panel = MapTopologyIssuePanel()
    qtbot.addWidget(panel)

    assert isinstance(panel.table, QTableView)
    assert not isinstance(panel.table, QTableWidget)
    assert not panel.findChildren(QTableWidget)

    issues = [
        {"feature_id": f"f{i}", "message": f"自相交 {i}", "severity": "error"}
        for i in range(40)
    ]
    panel.set_issues(issues)
    assert panel.table.rowCount() == 40
    assert panel.table.item(21, 0).text() == "f21"
    assert panel.table.item(21, 1).text() == "自相交 21"
    assert counting_table_items.count == 0

    # 空态：无问题时覆盖出现。
    panel.set_issues([])
    assert panel.table.rowCount() == 0
    assert not panel._empty_state.isHidden()


def test_map_topology_locate_still_emitted(qtbot):
    """迁移后激活路径（双击/Enter）仍按 feature_id 发 locate_requested。"""
    panel = MapTopologyIssuePanel()
    qtbot.addWidget(panel)
    panel.set_issues([{"feature_id": "f1", "message": "m", "severity": "error"}])

    seen: list[str] = []
    panel.locate_requested.connect(seen.append)

    panel.table.itemDoubleClicked.emit(panel.table.item(0, 0))
    assert seen == ["f1"]

    panel.table.setCurrentCell(0, 0)
    press = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(panel.table, press)
    assert seen == ["f1", "f1"]


# -- 资源表（迁移后 widget 断言兼容层仍成立）----------------------------------------


def test_resource_table_virtualized(qtbot, counting_table_items):
    from paleo_workbench.ui.pages.resource_table import ResourceTable

    widget = ResourceTable()
    qtbot.addWidget(widget)
    assert isinstance(widget.table, QTableView)
    assert not isinstance(widget.table, QTableWidget)

    resources = [
        SimpleNamespace(
            name=f"a{i}.las",
            type="well_log",
            format="las",
            status="parsed",
            path=f"/data/a{i}.las",
            id=f"r{i}",
        )
        for i in range(30)
    ]
    widget.update_resources(resources)
    assert widget.table.rowCount() == 30
    assert widget.table.columnCount() == 5
    assert widget.table.item(15, 0).text() == "a15.las"
    assert widget.table.item(0, 1).text() == "测井数据"
    assert counting_table_items.count == 0

    widget.update_resources([])
    assert widget.table.rowCount() == 0
    assert not widget._empty_state.isHidden()
