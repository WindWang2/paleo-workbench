"""Dock Framework V2 — declarative descriptors + resize policy (V9).

Dock identity, default geometry and floatability live here as **data**, not as
scattered ``_add_dock(...)`` call sites in the shell. The shell consumes
:class:`DockRegistry` at construction; nothing else in the codebase may
hardcode dock identity.

Resize authority (audit B-3): ``QMainWindow.resizeDocks`` is legal only for
(a) first-run / explicit layout reset and (b) *grow-only* affordances via
:func:`ensure_dock_usable` — never after a preset apply, never to shrink a
dock the user has arranged.

This module is import-safe without QtWidgets for the data layer (tests import
the registry directly); the resize helpers import Qt lazily.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DockImportance(str, Enum):
    CORE = "core"            # mapping-critical chrome (nav, layers, inspector)
    SECONDARY = "secondary"  # workflow panels (stage, input, linked views)
    UTILITY = "utility"      # bottom-row utilities (agent, tasks, logs, console)


#: Dock areas by name — kept as plain strings so the data layer stays Qt-free.
AREA_LEFT = "left"
AREA_RIGHT = "right"
AREA_BOTTOM = "bottom"


@dataclass(frozen=True)
class DockDescriptor:
    """One workstation dock, described once.

    ``min_floating_size`` applies **only while floating** — a docked dock must
    never carry a structural minimum (audit B-1/B-2). ``preferred_size`` is a
    first-run/reset ``resizeDocks`` target, never applied on preset switches.
    """

    dock_id: str
    title: str
    preferred_area: str = AREA_LEFT
    importance: DockImportance = DockImportance.SECONDARY
    default_visible: bool = True
    #: False for GL-bearing content: reparenting a GL viewport between
    # top-levels is the documented EGL segfault class (qt_platform.py:44-83).
    can_float: bool = True
    can_tabify: bool = True
    min_floating_size: tuple[int, int] = (220, 160)
    preferred_size: tuple[int, int] | None = None
    #: Vertical split preferred height inside its area column (first-run only).
    preferred_height: int | None = None
    workflow_tags: tuple[str, ...] = ()
    context_tags: tuple[str, ...] = ()
    object_name: str = ""
    remark: str = ""

    def __post_init__(self) -> None:
        if not self.object_name:
            # Keep the historical objectName scheme so persisted layouts
            # (saveState bytes) keep resolving across the V8→V9 transition.
            object.__setattr__(self, "object_name", f"WorkstationDock_{self.title}")


#: Canonical workstation dock set. Order = canonical layout application order.
WORKSTATION_DOCKS: tuple[DockDescriptor, ...] = (
    DockDescriptor(
        dock_id="nav",
        title="资源管理器",
        preferred_area=AREA_LEFT,
        importance=DockImportance.CORE,
        default_visible=True,
        preferred_size=(280, 0),
        preferred_height=420,
        workflow_tags=("always",),
        remark="rail + explorer",
    ),
    DockDescriptor(
        dock_id="mapping_stage",
        title="编图阶段",
        preferred_area=AREA_LEFT,
        importance=DockImportance.SECONDARY,
        # Prototype 左栏下部 = 每工作区 WorkflowPanel；阶段面板保留为
        # 按需 dock（面板菜单/预设可再开）。
        default_visible=False,
        preferred_size=(280, 0),
        preferred_height=280,
        workflow_tags=("mapping",),
    ),
    DockDescriptor(
        dock_id="inspector",
        title="检查器",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.CORE,
        default_visible=True,
        preferred_size=(300, 0),
        workflow_tags=("always",),
    ),
    DockDescriptor(
        dock_id="composite_layer",
        title="图层管理",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.CORE,
        default_visible=True,
        preferred_size=(300, 0),
        workflow_tags=("mapping",),
    ),
    DockDescriptor(
        dock_id="facies_palette",
        title="相带画刷",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        # Prototype 右栏按需工具：默认隐藏，stage/工作区 profile 抬升。
        default_visible=False,
        preferred_size=(240, 0),
        workflow_tags=("mapping",),
        remark="M2 相带调色板 + 吸色管 + 数字键装备",
    ),
    DockDescriptor(
        dock_id="hub",
        title="功能页",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        # Hosts the whole page stack incl. the 3D GL page — never float.
        can_float=False,
        workflow_tags=("navigation",),
    ),
    DockDescriptor(
        dock_id="composite_input",
        title="输入与结果",
        # Prototype 右栏标签组的一员（单因素/输入清单）；stage2 profile
        # 控制显隐，与 图层管理/检查器 共 tab。
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_size=(280, 0),
        workflow_tags=("mapping", "review"),
    ),
    DockDescriptor(
        # ws1 右栏「对比」页 —— 真实联动解释对照工作区。
        dock_id="predict_compare",
        title="对比",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_size=(300, 0),
        workflow_tags=("prediction", "review"),
    ),
    DockDescriptor(
        # ws2 右栏「约束」页 —— 宿主把窗口级 ConstraintPanel 收编进
        # 此 dock（adopt_dock）；未收编时保持隐藏（无 factory）。
        dock_id="constraint_panel",
        title="约束",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_size=(300, 0),
        workflow_tags=("mapping", "constraint"),
    ),
    DockDescriptor(
        # ws2 右栏「参考」页 —— 参考图层清单（LayerManagerPanel 第二
        # 实例：勾选/不透明度同一交互面）。
        dock_id="reference_maps",
        title="参考",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_size=(300, 0),
        workflow_tags=("mapping", "constraint"),
    ),
    DockDescriptor(
        # ws3 右栏「图件整饰」页 —— MapChromePanel（图名/图例/指北针/
        # 比例尺/标题栏 勾选，写回 map_chrome 文档节）。
        dock_id="map_decor",
        title="图件整饰",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_size=(300, 0),
        workflow_tags=("mapping",),
    ),
    DockDescriptor(
        # ws3 右栏「版式输出」页 —— LayoutComposePanel（模板/纸张/导出）。
        dock_id="layout_output",
        title="版式输出",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_size=(300, 0),
        workflow_tags=("mapping",),
    ),
    # ------------------------------------------------------------------
    # 底部「阶段/预览行」（dock 嵌套 row0 —— 任务|日志 工具条之上）：
    # 每格独立 dock，可单独悬浮/停靠/tab 化；navigate_workspace 按
    # 工作区投影成员集合，非成员整组隐藏后该行塌陷。
    # ------------------------------------------------------------------
    DockDescriptor(
        # ws0 数据管理底签：数据预览|版本历史|关联关系。
        dock_id="data_preview",
        title="数据预览",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=240,
        workflow_tags=("data",),
    ),
    DockDescriptor(
        dock_id="data_history",
        title="版本历史",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=240,
        workflow_tags=("data",),
    ),
    DockDescriptor(
        dock_id="data_relations",
        title="关联关系",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=240,
        workflow_tags=("data",),
    ),
    DockDescriptor(
        # ws1 智能预测底签：井震两联|预测任务|地震预测。
        dock_id="pair_link",
        title="井震两联",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=300,
        workflow_tags=("prediction", "interpretation"),
    ),
    DockDescriptor(
        dock_id="predict_task",
        title="预测任务",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=300,
        workflow_tags=("prediction",),
    ),
    DockDescriptor(
        dock_id="seismic_predict",
        title="地震预测",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=300,
        workflow_tags=("prediction", "seismic"),
    ),
    DockDescriptor(
        # ws2 约束与单因素底签：连井剖面|数据制备|地层对比|层序格架。
        # 连井剖面 = 窗口级 VizBCrossWellDock 经 adopt_dock 收编。
        dock_id="crosswell",
        title="连井剖面",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=300,
        workflow_tags=("constraint", "interpretation"),
    ),
    DockDescriptor(
        dock_id="data_prep",
        title="数据制备",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=300,
        workflow_tags=("constraint",),
    ),
    DockDescriptor(
        dock_id="strat_compare",
        title="地层对比",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=300,
        workflow_tags=("constraint", "interpretation"),
    ),
    DockDescriptor(
        dock_id="seq_frame",
        title="层序格架",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=300,
        workflow_tags=("constraint",),
    ),
    DockDescriptor(
        # ws3 综合编图底签：单因素参考缩略图带（更矮的一条）。
        dock_id="factor_refs",
        title="单因素参考",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=170,
        workflow_tags=("mapping",),
    ),
    DockDescriptor(
        # ws0 数据管理右列：数据属性(上)/数据血缘(下) —— 竖向二分，
        # 不并入右栏 tab 组（原型两片同显）。
        dock_id="data_props",
        title="数据属性",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_size=(300, 0),
        workflow_tags=("data",),
    ),
    DockDescriptor(
        dock_id="data_lineage",
        title="数据血缘",
        preferred_area=AREA_RIGHT,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_size=(300, 0),
        workflow_tags=("data",),
    ),
    DockDescriptor(
        dock_id="agent",
        title="Agent",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.UTILITY,
        default_visible=False,
        preferred_height=245,
        workflow_tags=("assistant",),
    ),
    DockDescriptor(
        dock_id="tasks",
        title="任务中心",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.UTILITY,
        # Prototype 底部常驻条（任务|日志 tabs）——默认可见。
        preferred_height=140,
        workflow_tags=("background",),
    ),
    DockDescriptor(
        dock_id="logs",
        title="日志",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.UTILITY,
        preferred_height=140,
        workflow_tags=("diagnostics",),
    ),
    DockDescriptor(
        # 底部常驻条的第三页（任务|日志|验证记录 —— prototype 底条）。
        dock_id="verify_records",
        title="验证记录",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.UTILITY,
        preferred_height=140,
        workflow_tags=("diagnostics", "review"),
    ),
    DockDescriptor(
        # 单因素统计（CONV-16 FactorStatsDock）——宿主经 adopt_dock 收编
        # 进底条 tab 组；stage2 profile 的 window.factor_stats 键照常
        # 抬升同一对象。未收编时隐藏（占位护栏）。
        dock_id="factor_stats",
        title="单因素统计",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.UTILITY,
        default_visible=False,
        preferred_height=140,
        workflow_tags=("constraint", "diagnostics"),
    ),
    DockDescriptor(
        dock_id="console",
        title="控制台",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.UTILITY,
        default_visible=False,
        preferred_height=200,
        workflow_tags=("diagnostics",),
    ),
    DockDescriptor(
        dock_id="composite_linked",
        title="联动视图",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        preferred_height=200,
        workflow_tags=("mapping", "interpretation"),
    ),
    DockDescriptor(
        dock_id="well",
        title="测井轨道",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        # GL track canvas inside — floating reparents the GL context.
        can_float=False,
        preferred_height=200,
        workflow_tags=("well", "interpretation"),
    ),
    DockDescriptor(
        dock_id="seismic",
        title="地震剖面",
        preferred_area=AREA_BOTTOM,
        importance=DockImportance.SECONDARY,
        default_visible=False,
        can_float=False,
        preferred_height=200,
        workflow_tags=("seismic", "interpretation"),
    ),
)


class DockRegistry:
    """Immutable lookup over the descriptor set (data-only, Qt-free)."""

    def __init__(self, descriptors: tuple[DockDescriptor, ...]) -> None:
        self._by_id: dict[str, DockDescriptor] = {d.dock_id: d for d in descriptors}
        if len(self._by_id) != len(descriptors):
            raise ValueError("duplicate dock_id in descriptor set")
        self._descriptors = descriptors

    def descriptors(self) -> tuple[DockDescriptor, ...]:
        return self._descriptors

    def ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    def get(self, dock_id: str) -> DockDescriptor | None:
        return self._by_id.get(dock_id)

    def require(self, dock_id: str) -> DockDescriptor:
        descriptor = self._by_id.get(dock_id)
        if descriptor is None:
            raise KeyError(f"unknown dock_id: {dock_id!r}")
        return descriptor

    def by_tag(self, tag: str) -> tuple[DockDescriptor, ...]:
        return tuple(d for d in self._descriptors if tag in d.workflow_tags)


workstation_dock_registry = DockRegistry(WORKSTATION_DOCKS)


def ensure_dock_usable(host, dock, *, minimum: int, vertical: bool) -> bool:
    """Grow-only programmatic resize (audit B-3 fix).

    ``QMainWindow.resizeDocks`` from action affordances (e.g. opening the
    Agent panel) may only *grow* a dock that is currently smaller than the
    usability floor — it must never shrink or pin a size the user chose.
    Returns True when a resize was issued.
    """
    if dock is None or dock.isFloating() or not dock.isVisible():
        return False
    current = dock.height() if vertical else dock.width()
    if current >= minimum:
        return False
    from PySide6.QtCore import Qt

    orientation = (
        Qt.Orientation.Vertical if vertical else Qt.Orientation.Horizontal
    )
    host.resizeDocks([dock], [minimum], orientation)
    return True


def apply_first_run_sizes(host, docks_by_id: dict[str, object]) -> None:
    """First-run / explicit-reset sizing from registry ``preferred_size``.

    Replaces the hardcoded ``resizeDocks`` block (shell.py B-3): sizes come
    from descriptors, and this function must only be called on first run or
    when the user explicitly resets the layout — never on preset apply.
    """
    from PySide6.QtCore import Qt

    horizontal = Qt.Orientation.Horizontal
    vertical = Qt.Orientation.Vertical

    def _dock(dock_id: str):
        return docks_by_id.get(dock_id)

    def _widths(pairs: list[tuple[str, int]]):
        host.resizeDocks(
            [_dock(i) for i, _ in pairs], [w for _, w in pairs], horizontal
        )

    def _heights(pairs: list[tuple[str, int]]):
        host.resizeDocks(
            [_dock(i) for i, _ in pairs], [h for _, h in pairs], vertical
        )

    registry = workstation_dock_registry

    def _preferred_w(dock_id: str, fallback: int) -> int:
        size = registry.get(dock_id).preferred_size if registry.get(dock_id) else None
        return (size[0] if size and size[0] else fallback) or fallback

    def _preferred_h(dock_id: str, fallback: int) -> int:
        descriptor = registry.get(dock_id)
        return descriptor.preferred_height if descriptor and descriptor.preferred_height else fallback

    _widths([("nav", _preferred_w("nav", 280))])
    _widths([
        ("mapping_stage", _preferred_w("mapping_stage", 280)),
        ("composite_input", _preferred_w("composite_input", 280)),
    ])
    _heights([
        ("nav", _preferred_h("nav", 420)),
        ("mapping_stage", _preferred_h("mapping_stage", 280)),
    ])
    _widths([
        ("inspector", _preferred_w("inspector", 300)),
        ("composite_layer", _preferred_w("composite_layer", 300)),
    ])
    _heights([
        ("agent", _preferred_h("agent", 200)),
        ("tasks", _preferred_h("tasks", 200)),
        ("composite_linked", _preferred_h("composite_linked", 200)),
    ])


class ViewportClass(str, Enum):
    """Logical window-width classes (V9 §8).

    Thresholds are in *logical* pixels (device-independent); a 1366-wide
    panel at 125% DPI reports ~1093 logical px and must classify compact.
    """

    COMPACT = "compact"      # < 1100  — 1366@125%, small laptops
    NORMAL = "normal"        # 1100-1599
    WIDE = "wide"            # 1600-2199 — 1080p class
    ULTRAWIDE = "ultrawide"  # >= 2200 — 1440p+, 4K


VIEWPORT_COMPACT_MAX = 1099
VIEWPORT_WIDE_MIN = 1600
VIEWPORT_ULTRAWIDE_MIN = 2200

#: Responsive inspector policy thresholds (window width, hysteresis band).
#: With V9 floors (nav≈230 + inspector 220 + central 320 ≈ 770) only truly
#: narrow windows need the inspector to fold away.
INSPECTOR_HIDE_BELOW = 1100
INSPECTOR_RESTORE_ABOVE = 1200

#: App-bar command input minimum width per viewport class (compact shrinks
#: the floor to free top-bar space; normal restores it).
COMMAND_INPUT_FLOOR_COMPACT = 220
COMMAND_INPUT_FLOOR_NORMAL = 300


def classify_viewport(width: int) -> ViewportClass:
    if width <= VIEWPORT_COMPACT_MAX:
        return ViewportClass.COMPACT
    if width >= VIEWPORT_ULTRAWIDE_MIN:
        return ViewportClass.ULTRAWIDE
    if width >= VIEWPORT_WIDE_MIN:
        return ViewportClass.WIDE
    return ViewportClass.NORMAL
