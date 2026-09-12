"""V11 goal §21 结构性能测试。

原则（与 11-performance 目标一致）：断言**结构性代理指标**，不做脆弱的
墙钟微基准；仅在结构代理不可能处给宽松墙钟上限（100k ``set_rows`` < 10s，
真实预算是交互级 ~100ms，10s 只拦 O(N²) 级回退）。

覆盖：

1. **表虚拟化**：``ObjectTableModel`` 100k 行 —— rowCount / 中段取值 /
   零 QTableWidgetItem；同键 ``set_rows`` 差分（零 modelReset）+
   ``StableSelection`` 跨刷新保键；
2. **首绘有界**：QTableView + 100k 模型 show 后仅按可视区取值
   （列取值函数调用数 < 2000，非 100k）；
3. **reconcile 零重建**：10k 键第二次同步（同键集）新建项 = 0、
   项身份保留；
4. **选择总线去重**：``publish_well_selection`` 同 (well, source) 重复
   发布恰好 1 次 ``selection_changed``；
5. **任务面板零重建**：``TaskPanelBase.update_state`` 同任务 id 二次驱动
   行项身份不变（id() 相等）；
6. **AsyncQuery latest-only**：连续 3 次快速 submit 仅最新回调投递；
   ``shutdown(0)`` 后迟到回调全部拒绝；
7. **注册表淘汰**：终态操作记录数 ≤ ``_MAX_TERMINAL``（FIFO）。
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QTableView, QTableWidgetItem

from paleo_workbench.ui.modelview import (
    AsyncQuery,
    ColumnSpec,
    ObjectTableModel,
    StableSelection,
    bind_table_defaults,
    reconcile_widget_items,
)
from paleo_workbench.ui.operations import OperationRegistry, OperationState
from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel
from paleo_workbench.ui.view_coordination import ViewCoordinationController
from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
from paleo_workbench.viz.selection_context import SelectionContext


# -- 工具 -------------------------------------------------------------------------


@pytest.fixture
def counting_table_items(monkeypatch):
    """计数 QTableWidgetItem 构造（虚拟化面应为 0）。"""
    created = {"n": 0}
    real = QTableWidgetItem

    class _CountingItem(real):
        def __init__(self, *args):
            super().__init__(*args)
            created["n"] += 1

    monkeypatch.setattr(
        "PySide6.QtWidgets.QTableWidgetItem", _CountingItem
    )
    return created


def _row(i: int) -> SimpleNamespace:
    return SimpleNamespace(id=f"k{i:06d}", name=f"W{i}", value=i)


def _model(n: int = 0) -> ObjectTableModel:
    columns = [
        ColumnSpec("id", "ID", value=lambda r: r.id),
        ColumnSpec("name", "名称", value=lambda r: r.name),
        ColumnSpec("value", "数值", value=lambda r: r.value),
    ]
    model = ObjectTableModel(columns, key_of=lambda r: r.id)
    if n:
        model.set_rows([_row(i) for i in range(n)])
    return model


# -- 1. 表虚拟化：100k 行 -----------------------------------------------------------


def test_object_table_model_100k_rows_structural(qtbot, counting_table_items):
    model = _model()
    rows = [_row(i) for i in range(100_000)]

    started = time.perf_counter()
    model.set_rows(rows)
    elapsed = time.perf_counter() - started

    assert model.rowCount() == 100_000
    assert len(model) == 100_000
    # 虚拟模型：零 item-per-cell 分配。
    assert counting_table_items["n"] == 0
    # 宽松墙钟（结构代理无法覆盖的总回退拦截）：真实预算 ~100ms。
    assert elapsed < 10.0, f"set_rows 100k 耗时 {elapsed:.2f}s"

    # 中段行按需取值。
    mid = model.index(50_000, 0)
    assert model.data(mid) == "k050000"
    assert model.data(model.index(50_000, 1)) == "W50000"
    assert model.data(model.index(50_000, 2)) == "50000"
    # 键查询。
    assert model.row_for_key("k050000") is rows[50_000]
    assert model.index_for_key("k099999").row() == 99_999
    assert model.all_keys()[0] == "k000000"


def test_set_rows_same_keys_differential_no_reset(qtbot, monkeypatch):
    model = _model(200)
    view = QTableView()
    qtbot.addWidget(view)
    bind_table_defaults(view)
    view.setModel(model)
    view.resize(640, 400)
    view.show()

    # 选中 k000007。
    target = model.index_for_key("k000007")
    assert target.isValid()
    view.selectionModel().select(
        target,
        QItemSelectionModel.SelectionFlag.Select
        | QItemSelectionModel.SelectionFlag.Rows,
    )

    # 计数 beginResetModel（同键差分路径必须为 0）。
    resets = {"n": 0}
    real_begin = ObjectTableModel.beginResetModel

    def _counting_begin(self):
        resets["n"] += 1
        real_begin(self)

    monkeypatch.setattr(ObjectTableModel, "beginResetModel", _counting_begin)

    # 同键集合、全新对象：dataChanged 路径，选择保持。
    model.set_rows([_row(i) for i in range(200)])
    assert resets["n"] == 0
    assert view.model().rowCount() == 200
    selected_keys = [
        model.key_for_index(index)
        for index in view.selectionModel().selectedRows()
    ]
    assert "k000007" in selected_keys

    # StableSelection 跨同键刷新：捕获 → set_rows → 恢复，键仍命中。
    selection = StableSelection(view)
    keys = selection.capture()
    assert keys == ["k000007"]
    model.set_rows([_row(i) for i in range(200)])
    selection.restore(keys)
    assert [
        model.key_for_index(index)
        for index in view.selectionModel().selectedRows()
    ] == ["k000007"]
    assert resets["n"] == 0

    # 键集合变化（删行）：允许（且必须）整表重置。
    model.set_rows([_row(i) for i in range(100)])
    assert resets["n"] == 1
    assert view.model().rowCount() == 100


# -- 2. 首绘有界：可视区取值 ----------------------------------------------------------


def test_table_view_first_paint_bounded_to_viewport(qtbot):
    calls = {"n": 0}

    def _counted_id(row):
        calls["n"] += 1
        return row.id

    columns = [
        ColumnSpec("id", "ID", value=_counted_id),
        ColumnSpec("name", "名称", value=lambda r: r.name),
    ]
    model = ObjectTableModel(columns, key_of=lambda r: r.id)
    model.set_rows([_row(i) for i in range(100_000)])

    view = QTableView()
    qtbot.addWidget(view)
    bind_table_defaults(view)
    view.setModel(model)
    view.resize(900, 420)
    view.show()
    qtbot.wait(80)  # 布局 + 首帧绘制（等价 processEvents 稳定拍）

    # 视口有内容（取值发生过），且远小于全表：viewport-bounded。
    assert 0 < calls["n"] < 2_000, (
        f"首绘取值 {calls['n']} 次（应 ≈ 可视行数，非 100k）"
    )
    assert view.model().rowCount() == 100_000


# -- 3. reconcile 零重建 ------------------------------------------------------------


def test_reconcile_10k_keys_second_call_creates_nothing(qtbot):
    from PySide6.QtWidgets import QListWidget, QListWidgetItem

    widget = QListWidget()
    qtbot.addWidget(widget)
    created = {"n": 0}
    updated = {"n": 0}

    def make_item(key: str):
        created["n"] += 1
        return QListWidgetItem()

    def update_item(item, key: str):
        updated["n"] += 1
        item.setText(key)

    keys = [f"r{i:05d}" for i in range(10_000)]

    mapping = reconcile_widget_items(
        widget, keys, make_item=make_item, update_item=update_item
    )
    assert created["n"] == 10_000
    assert widget.count() == 10_000
    first_item = widget.item(0)
    assert mapping["r00000"] is first_item

    # 同键集第二次：零新建、零移除、项身份保留、原地刷新。
    updated["n"] = 0
    mapping2 = reconcile_widget_items(
        widget, keys, make_item=make_item, update_item=update_item
    )
    assert created["n"] == 10_000, "同键第二次同步不得新建项"
    assert updated["n"] == 10_000
    assert widget.count() == 10_000
    assert widget.item(0) is first_item
    assert [widget.item(i) for i in range(widget.count())] == [
        mapping[k] for k in keys
    ]
    assert all(
        mapping2[k] is mapping[k] for k in keys
    ), "同键二次同步必须原样返回既有项"


# -- 4. 选择总线：重复发布守卫 --------------------------------------------------------


def test_publish_well_selection_duplicate_guard(qtbot):
    context = SelectionContext()
    controller = ViewCoordinationController(context, CoordinateTransformHub())

    emissions: list[SelectionContext] = []
    context.selection_changed.connect(lambda ctx: emissions.append(ctx))

    # 同 (well, source) 二次发布：恰好 1 次 selection_changed。
    controller.publish_well_selection("A12", source=controller.SOURCE_WELL_LOG)
    controller.publish_well_selection("A12", source=controller.SOURCE_WELL_LOG)
    assert len(emissions) == 1

    # 换源 / 换井：各 +1（新信息不得被吞）。
    controller.publish_well_selection("A12", source=controller.SOURCE_MAP)
    assert len(emissions) == 2
    controller.publish_well_selection("B3", source=controller.SOURCE_MAP)
    assert len(emissions) == 3

    snapshot = context.snapshot()
    assert snapshot.active_well_id == "B3"
    assert snapshot.source_widget_id == controller.SOURCE_MAP


# -- 5. 任务面板：同 id 二次驱动零重建 -------------------------------------------------


def _tasks(*statuses: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=f"pred-{index}",
            name=f"任务 {index}",
            status=status,
            adapter_kind="xgboost",
            probability_summary={"mean_probability": 0.7},
            review_areas=[],
        )
        for index, status in enumerate(statuses)
    ]


def test_task_panel_update_state_zero_rebuild(qtbot):
    panel = PredictionTaskPanel()
    qtbot.addWidget(panel)

    panel.update_state(_tasks("pending", "running", "complete"), selected_index=1)
    assert panel.task_list.count() == 3
    before = [panel.task_list.item(i) for i in range(panel.task_list.count())]
    before_texts = [item.text() for item in before]
    assert any("运行中" in text for text in before_texts)

    # 同任务 id 二次驱动（状态推进 running → complete）：行对象身份不变。
    panel.update_state(_tasks("pending", "complete", "complete"), selected_index=1)
    after = [panel.task_list.item(i) for i in range(panel.task_list.count())]
    assert [id(item) for item in after] == [id(item) for item in before], (
        "同 id 任务刷新不得重建行项（选择/滚动会丢）"
    )
    assert panel.task_list.count() == 3
    # 内容原地刷新：不再有「运行中」行，第 2 行已是完成态。
    assert not any("运行中" in item.text() for item in after)
    assert "完成" in after[1].text()


# -- 6. AsyncQuery：latest-only + 迟到拒绝 --------------------------------------------


def test_async_query_latest_only_and_post_shutdown_rejection(qtbot):
    query = AsyncQuery()

    fired: list[object] = []

    # 3 次快速连续 submit（不泵事件）：仅最新 epoch 的回调允许投递。
    for tag in (1, 2, 3):
        query.submit(
            lambda tag=tag: tag,
            on_ready=lambda result, _fired=fired: _fired.append(result),
        )
    qtbot.waitUntil(lambda: fired == [3], timeout=5_000)
    assert fired == [3]

    # shutdown(0) 后：已在运行的查询完成也不再投递。
    started = threading.Event()

    def _slow():
        started.set()
        time.sleep(0.15)
        return "late"

    query.submit(_slow, on_ready=lambda result: fired.append(result))
    assert started.wait(2.0), "worker 未启动（测试前提失效）"
    query.shutdown(0)
    qtbot.wait(400)  # 泵事件：迟到 _CALL 若投递也应被 epoch/回调清除拒绝
    assert fired == [3], f"shutdown 后回调仍投递: {fired}"

    query.shutdown(0)


# -- 7. OperationRegistry：终态 FIFO 淘汰 ----------------------------------------------


def test_operation_registry_terminal_eviction():
    registry = OperationRegistry()
    max_terminal = registry._MAX_TERMINAL
    assert max_terminal > 0

    overflow = 20
    for index in range(max_terminal + overflow):
        op_id = registry.begin(f"evict-{index:03d}", f"批量操作 {index}")
        registry.finish(op_id, OperationState.COMPLETED)

    records = registry.records()
    assert len(records) <= max_terminal, (
        f"终态记录 {len(records)} 条，超过上限 {max_terminal}"
    )
    # FIFO：最早入列的终态记录被淘汰。
    assert registry.record("evict-000") is None
    assert registry.record(f"evict-{max_terminal + overflow - 1:03d}") is not None
    # 剩余记录全部终态。
    assert all(record.state.terminal for record in records)

    # 在途记录不参与淘汰。
    running_id = registry.begin("evict-running", "仍在运行")
    assert registry.record(running_id) is not None
    assert registry.record(running_id).state == OperationState.RUNNING

    # 会话清理：全部移除。
    registry.clear()
    assert registry.records() == []
    assert registry.record(running_id) is None
