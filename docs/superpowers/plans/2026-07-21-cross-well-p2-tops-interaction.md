# 连井对比 P2 井分层接入 + 对比交互实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把工程中的井分层数据接入连井对比视图（分层顶线 + 同名层自动连线），并把引擎已有的 DTW/拾取/撤销等对比交互暴露到地层对比页面 UI。

**Architecture:** workbench 侧新增 WellTops 解析器（`resources/` 层）与工作流函数（`workflow/` 层），页面加载剖面后按井名匹配注入引擎 `FormationTopsModel` 与 `set_formation_data`；引擎侧补三个小 API（`set_well_spacing`、`set_tops_visible`、`set_track_visible_by_label`）并经 `geoviz` facade 导出 `FormationTop`；页面中栏加工具条承载全部交互。

**Tech Stack:** PySide6 / Qt（offscreen + pytest-qt）、geoviz CrossWell 引擎、pytest。

**Spec:** `docs/superpowers/specs/2026-07-21-cross-well-correlation-optimization-design.md`（P2 部分）

## Global Constraints

- workbench 生产代码只允许 `from geoviz import ...`（分层守卫 `tests/test_geoviz_package_independence.py`）；新公共 API 名加入该测试的 `GEOVIZ_PUBLIC_FACADE` 白名单是既定流程，允许修改此文件，其他现有测试不得修改。
- 引擎所有改动默认行为不变（间距默认 150、顶线默认显示）。
- 不制造 geoviz → paleo_workbench 反向依赖。
- 两个独立 git 仓库：引擎改动在 `geo-viz-engine/` 提交，workbench 改动在仓库根提交（含子模块 gitlink 联动）。
- 所有命令使用项目 venv：仓库根 `.venv/bin/python`；geo-viz-engine 内 `../.venv/bin/python`。
- 遵循 TDD：先写失败测试，再实现。

**已确认的领域事实（实现者无需再调研）：**
- 井分层文件为 SMI WellTops `.dat`：`#` 开头的注释/表头行 + 空白分隔列 `WellName Name MD X Y Z TVD Time(ms)`（样例 `data/井分层/DC.dat`，CRLF）。
- `CrossWellHost.widget` 是 `CrossWellCanvas`（属性：`tops_model`、`picks_model`、`pick_mode`、`active_formation`、`snap_type`、`propagate_pick_via_dtw(ref_well, ref_depth, formation, band_radius=None, progress_callback=None)`）；`CrossWellHost.inner` 是 `CrossWellWidget`（`set_formation_data`、`auto_link()`、`toggle_manual_link()`、`_canvases`、`_manual_link_active`）。
- `FormationTopsModel.add_top(FormationTop(well_name, formation_name, depth_m))`；`formation_names()`；`save_csv(path)`；`clear()`。
- `HorizonPicksModel`：`add_pick(formation, well, depth, source="manual") -> pick_id`、`undo()`/`redo()`、`all_picks()`（`HorizonPick.formation_name`、`.connected_wells()`、`.depth_for_well(w)`）、`clear()`。
- `geoviz` facade 已导出 `IntervalItem`、`CrossWellCanvas`；**未**导出 `FormationTop`（Task 3 添加）。

---

### Task 1: WellTops 分层文件解析器

**Files:**
- Create: `paleo_workbench/resources/well_tops_parser.py`
- Test: `tests/test_well_tops_parser.py`

**Interfaces:**
- Consumes: 无。
- Produces（Task 2 依赖）:
  - `paleo_workbench.resources.well_tops_parser.WellTop` — frozen dataclass，字段 `well_name: str`、`top_name: str`、`md: float`、`tvd: float | None = None`。
  - `paleo_workbench.resources.well_tops_parser.parse_well_tops(path: str | Path) -> list[WellTop]`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_well_tops_parser.py`：

```python
"""Tests for the SMI WellTops (.dat) parser."""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.resources.well_tops_parser import parse_well_tops

SAMPLE = (
    "#WellTops File From SMI\r\n"
    "#WellName    Name         MD           X            Y            Z            TVD          Time(ms)    \r\n"
    "A1           X            850.000      5288.670     8219.940     -850.000     850.000      -99999.000  \r\n"
    "A1           C1           1164.000     5288.670     8219.940     -1164.000    1164.000     -99999.000  \r\n"
    "A10          D21          1482.000     10499.930    11460.655    -1430.278    1430.278     -99999.000  \r\n"
)


def test_parse_basic_rows(tmp_path: Path):
    path = tmp_path / "DC.dat"
    path.write_text(SAMPLE, encoding="utf-8")
    tops = parse_well_tops(path)
    assert len(tops) == 3
    assert tops[0].well_name == "A1"
    assert tops[0].top_name == "X"
    assert tops[0].md == 850.0
    assert tops[0].tvd == 850.0
    assert tops[2].well_name == "A10"
    assert tops[2].tvd == 1430.278


def test_parse_skips_garbage_rows(tmp_path: Path):
    path = tmp_path / "bad.dat"
    path.write_text(
        "# comment\n\nshort row\nA1 BAD_DEPTH notanumber 1 2 3 4 5\nA1 C1 1164.0 0 0 0 1164.0 0\n",
        encoding="utf-8",
    )
    tops = parse_well_tops(path)
    assert len(tops) == 1
    assert tops[0].top_name == "C1"


def test_parse_missing_tvd_yields_none(tmp_path: Path):
    path = tmp_path / "short.dat"
    path.write_text("A1 C1 1164.0\n", encoding="utf-8")
    tops = parse_well_tops(path)
    assert len(tops) == 1
    assert tops[0].tvd is None


def test_parse_empty_file(tmp_path: Path):
    path = tmp_path / "empty.dat"
    path.write_text("# only comments\n", encoding="utf-8")
    assert parse_well_tops(path) == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_well_tops_parser.py -v
```

预期：FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现解析器**

创建 `paleo_workbench/resources/well_tops_parser.py`：

```python
"""Parser for SMI WellTops .dat files (井分层)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WellTop:
    well_name: str
    top_name: str
    md: float
    tvd: float | None = None


def parse_well_tops(path: str | Path) -> list[WellTop]:
    """Parse an SMI WellTops .dat file into WellTop rows.

    Format: ``#`` comment/header lines, then whitespace-separated columns
    ``WellName Name MD X Y Z TVD Time(ms)``. Tolerant of CRLF, blank lines
    and short/garbage rows (skipped).
    """
    tops: list[WellTop] = []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = stripped.split()
        if len(tokens) < 3:
            continue
        try:
            md = float(tokens[2])
        except ValueError:
            continue
        tvd = None
        if len(tokens) >= 7:
            try:
                tvd = float(tokens[6])
            except ValueError:
                tvd = None
        tops.append(WellTop(well_name=tokens[0], top_name=tokens[1], md=md, tvd=tvd))
    return tops
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_well_tops_parser.py -v
```

预期：4 passed。

- [ ] **Step 5: 提交（仓库根）**

```bash
git add paleo_workbench/resources/well_tops_parser.py tests/test_well_tops_parser.py && git commit -m "feat(resources): add SMI WellTops parser for well stratification data"
```

---

### Task 2: 工作流分层数据接入函数

**Files:**
- Modify: `paleo_workbench/workflow/stratigraphy_correlation.py`（文件末尾追加）
- Test: `tests/test_stratigraphy_correlation_tops.py`

**Interfaces:**
- Consumes: Task 1 的 `parse_well_tops` / `WellTop`。
- Produces（Task 4 依赖）:
  - `load_well_tops(project: ProjectDocument) -> tuple[dict[str, list[tuple[str, float]]], list[str]]` — 返回 `({井名: [(分层名, 深度MD)], 按深度排序}, 警告列表)`。
  - `match_tops_to_wells(tops_by_well: dict[str, list[tuple[str, float]]], well_names: list[str]) -> tuple[dict[str, list[tuple[str, float]]], list[str]]` — 精确匹配后大小写不敏感兜底；返回 `({剖面井名: tops}, 未匹配的分层井名)`。
  - `tops_to_intervals(tops: list[tuple[str, float]]) -> list[IntervalItem]` — 第 i 个区间跨 tops[i]..tops[i+1]；最后一个分层复用前一个厚度（仅一个分层时默认 10.0 m）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_stratigraphy_correlation_tops.py`：

```python
"""Tests for well-tops workflow helpers in stratigraphy_correlation."""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.workflow.stratigraphy_correlation import (
    load_well_tops,
    match_tops_to_wells,
    tops_to_intervals,
)

DAT = (
    "#WellTops File From SMI\n"
    "A1 C1 1164.0 0 0 0 1164.0 0\n"
    "A1 X 850.0 0 0 0 850.0 0\n"
    "A2 C1 1200.0 0 0 0 1200.0 0\n"
    "GHOST C1 1300.0 0 0 0 1300.0 0\n"
)


def _project_with_dat(tmp_path: Path) -> ProjectDocument:
    path = tmp_path / "DC.dat"
    path.write_text(DAT, encoding="utf-8")
    project = ProjectDocument.new("T")
    project.resources.append(
        ResourceItem(name="DC.dat", path=str(path), type="well_stratification", format="dat")
    )
    return project


def test_load_well_tops_groups_and_sorts(tmp_path: Path):
    project = _project_with_dat(tmp_path)
    tops, warnings = load_well_tops(project)
    assert warnings == []
    assert set(tops) == {"A1", "A2", "GHOST"}
    # Sorted by depth: X(850) before C1(1164)
    assert tops["A1"] == [("X", 850.0), ("C1", 1164.0)]


def test_load_well_tops_missing_file_warns():
    project = ProjectDocument.new("T")
    project.resources.append(
        ResourceItem(name="gone.dat", path="/no/such/gone.dat", type="well_stratification", format="dat")
    )
    tops, warnings = load_well_tops(project)
    assert tops == {}
    assert len(warnings) == 1


def test_match_tops_to_wells_exact_and_case_insensitive():
    tops_by_well = {"A1": [("X", 850.0)], "a2": [("C1", 1200.0)], "GHOST": [("C1", 1.0)]}
    matched, unmatched = match_tops_to_wells(tops_by_well, ["A1", "A2"])
    assert set(matched) == {"A1", "A2"}
    assert matched["A2"] == [("C1", 1200.0)]
    assert unmatched == ["GHOST"]


def test_tops_to_intervals_spans_and_last_thickness():
    intervals = tops_to_intervals([("X", 850.0), ("C1", 1164.0), ("D1", 1482.0)])
    assert [(iv.top, iv.bottom, iv.name) for iv in intervals] == [
        (850.0, 1164.0, "X"),
        (1164.0, 1482.0, "C1"),
        (1482.0, 1800.0, "D1"),  # last reuses previous thickness (318.0)
    ]


def test_tops_to_intervals_single_top_default_thickness():
    intervals = tops_to_intervals([("X", 850.0)])
    assert [(iv.top, iv.bottom, iv.name)] == [(850.0, 860.0, "X")]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_stratigraphy_correlation_tops.py -v
```

预期：FAIL（`ImportError: cannot import name 'load_well_tops'`）。

- [ ] **Step 3: 实现工作流函数**

在 `paleo_workbench/workflow/stratigraphy_correlation.py` 末尾追加（文件顶部 import 区加 `from paleo_workbench.resources.well_tops_parser import parse_well_tops`）：

```python
def load_well_tops(project: ProjectDocument) -> tuple[dict[str, list[tuple[str, float]]], list[str]]:
    """Load 井分层 tops from well_stratification resources.

    Returns ({well_name: [(top_name, depth_md)] sorted by depth}, warnings).
    """
    tops_by_well: dict[str, list[tuple[str, float]]] = {}
    warnings: list[str] = []
    resources = [r for r in project.resources if r.type == "well_stratification"]
    for resource in resources:
        path = Path(resource.path)
        if not path.is_file():
            warnings.append(f"分层文件不存在: {resource.name}")
            continue
        try:
            rows = parse_well_tops(path)
        except Exception as exc:
            warnings.append(f"分层解析失败 {resource.name}: {exc.__class__.__name__}")
            continue
        for row in rows:
            tops_by_well.setdefault(row.well_name, []).append((row.top_name, row.md))
    for well in tops_by_well:
        tops_by_well[well].sort(key=lambda t: t[1])
    return tops_by_well, warnings


def match_tops_to_wells(
    tops_by_well: dict[str, list[tuple[str, float]]],
    well_names: list[str],
) -> tuple[dict[str, list[tuple[str, float]]], list[str]]:
    """Match tops well names to section well names (exact, then case-insensitive).

    Returns ({section_well_name: tops}, unmatched_top_well_names).
    """
    lookup: dict[str, str] = {}
    for name in well_names:
        lookup[name] = name
        lookup.setdefault(name.upper(), name)
    matched: dict[str, list[tuple[str, float]]] = {}
    unmatched: list[str] = []
    for top_well, tops in tops_by_well.items():
        target = lookup.get(top_well) or lookup.get(top_well.upper())
        if target is None:
            unmatched.append(top_well)
        else:
            matched[target] = tops
    return matched, unmatched


def tops_to_intervals(tops: list[tuple[str, float]]) -> list[Any]:
    """Convert [(name, depth)] tops into IntervalItems for auto_link.

    Interval i spans tops[i]..tops[i+1]; the last top reuses the previous
    thickness (a single top gets a default 10.0 m thickness).
    """
    from geoviz import IntervalItem

    intervals: list[Any] = []
    for i, (name, depth) in enumerate(tops):
        if i + 1 < len(tops):
            bottom = tops[i + 1][1]
        elif i > 0:
            bottom = depth + (depth - tops[i - 1][1])
        else:
            bottom = depth + 10.0
        intervals.append(IntervalItem(top=float(depth), bottom=float(bottom), name=name))
    return intervals
```

- [ ] **Step 4: 运行测试确认通过 + 相关回归**

```bash
.venv/bin/python -m pytest tests/test_stratigraphy_correlation_tops.py tests/test_stratigraphy_correlation.py -v
```

预期：全绿（5 + 既有）。

- [ ] **Step 5: 提交（仓库根）**

```bash
git add paleo_workbench/workflow/stratigraphy_correlation.py tests/test_stratigraphy_correlation_tops.py && git commit -m "feat(workflow): load and match well tops for correlation section"
```

---

### Task 3: 引擎 API（井间距 / 顶线显隐 / 按标签轨道显隐 / FormationTop facade）

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/cross_well_widget.py`
- Modify: `geo-viz-engine/packages/geoviz_cross_well/geoviz_cross_well/canvas.py`
- Modify: `geo-viz-engine/geoviz/__init__.py`（facade 映射加一行）
- Test: `geo-viz-engine/packages/geoviz_well_log/tests/test_well_spacing.py`
- Test: `geo-viz-engine/packages/geoviz_cross_well/tests/test_tops_visibility.py`

**Interfaces:**
- Produces（Task 4 依赖）:
  - `CrossWellWidget.set_well_spacing(px: int) -> None` — 布局与 `export_composite` 共用；默认 150 不变。
  - `CrossWellWidget.set_track_visible_by_label(label: str, visible: bool) -> None` — 跨全部井按轨道标签显隐。
  - `CrossWellCanvas.set_tops_visible(visible: bool) -> None` — 控制分层顶虚线绘制；默认 True。
  - facade `from geoviz import FormationTop`。

- [ ] **Step 1: 写失败测试（间距 + 轨道显隐）**

创建 `geo-viz-engine/packages/geoviz_well_log/tests/test_well_spacing.py`：

```python
"""CrossWellWidget.set_well_spacing / set_track_visible_by_label tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_canvas():
    from geoviz_well_log.models import CurveData
    from geoviz_well_log.renderer.canvas import WellLogCanvas
    from geoviz_well_log.renderer.curve_track import CurveTrack

    curve = CurveData(
        name="GR", unit="API",
        depth=[float(i) for i in range(10)],
        values=[float(i) for i in range(10)],
        display_range=(0.0, 10.0),
    )
    canvas = WellLogCanvas()
    canvas.add_track(CurveTrack([curve], label="GR"))
    return canvas


def _make_widget(n: int = 2):
    from geoviz_well_log.cross_well_widget import CrossWellWidget

    widget = CrossWellWidget()
    for i in range(n):
        widget.add_canvas(_make_canvas(), f"W{i + 1}")
    return widget


def test_default_spacing_is_150(qapp):
    widget = _make_widget()
    assert widget._container_layout.spacing() == 150


def test_set_well_spacing_updates_layout_and_minimum_width(qapp):
    widget = _make_widget()
    widget.set_well_spacing(80)
    assert widget._container_layout.spacing() == 80
    margins = widget._container_layout.contentsMargins()
    expected = (
        margins.left() + margins.right()
        + sum(c.minimumWidth() for c in widget._canvases)
        + 80 * (len(widget._canvases) - 1)
    )
    assert widget.minimumWidth() == expected


def test_export_png_uses_current_spacing(qapp, tmp_path):
    widget = _make_widget()
    widget.resize(800, 600)
    for c in widget._canvases:
        c.resize(200, 600)
    widget.set_well_spacing(50)
    out = tmp_path / "x.png"
    widget.export_composite(str(out), fmt="png")
    from PySide6.QtGui import QImage

    img = QImage(str(out))
    expected_w = sum(c.width() for c in widget._canvases) + 50 * (len(widget._canvases) - 1)
    assert img.width() == expected_w


def test_set_track_visible_by_label(qapp):
    widget = _make_widget()
    widget.set_track_visible_by_label("GR", False)
    for canvas in widget._canvases:
        assert canvas.tracks[0]._visible is False
    widget.set_track_visible_by_label("GR", True)
    for canvas in widget._canvases:
        assert canvas.tracks[0]._visible is True
```

- [ ] **Step 2: 写失败测试（顶线显隐）**

创建 `geo-viz-engine/packages/geoviz_cross_well/tests/test_tops_visibility.py`：

```python
"""CrossWellCanvas.set_tops_visible tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_tops_visible_default_true(qapp):
    from geoviz_cross_well.canvas import CrossWellCanvas

    canvas = CrossWellCanvas()
    assert canvas._overlay._tops_visible is True


def test_set_tops_visible_toggles_overlay(qapp):
    from geoviz_cross_well.canvas import CrossWellCanvas

    canvas = CrossWellCanvas()
    canvas.set_tops_visible(False)
    assert canvas._overlay._tops_visible is False
    canvas.set_tops_visible(True)
    assert canvas._overlay._tops_visible is True
```

- [ ] **Step 3: 运行测试确认失败**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests/test_well_spacing.py packages/geoviz_cross_well/tests/test_tops_visibility.py -v
```

预期：FAIL（`AttributeError: set_well_spacing` / `set_tops_visible` / `set_track_visible_by_label`）。

- [ ] **Step 4: 实现引擎改动**

**4a. `cross_well_widget.py`**：
- `__init__` 中 `self._container_layout.setSpacing(150)`（第 43 行）前加 `self._well_spacing = 150`，并把该行改为 `self._container_layout.setSpacing(self._well_spacing)`。
- `set_track_visible` 方法（第 181-185 行）后追加：

```python
    def set_well_spacing(self, px: int):
        """Set inter-well spacing in pixels (layout and export share it)."""
        self._well_spacing = max(0, int(px))
        self._container_layout.setSpacing(self._well_spacing)
        self._update_minimum_width()
        self._overlay.update()

    def set_track_visible_by_label(self, label: str, visible: bool):
        """Show or hide tracks matching `label` across all canvases."""
        for canvas in self._canvases:
            for track in canvas.tracks:
                if (track.label or "") == label:
                    track._visible = visible
            canvas.update()
```

- `export_composite`（第 364 行）`spacing = 150` 改为 `spacing = self._well_spacing`；`_paint_composite`（第 406 行）同样改。

**4b. `geoviz_cross_well/canvas.py`**：
- `PickingOverlay.__init__` 加 `self._tops_visible = True`；新增方法：

```python
    def set_tops_visible(self, visible: bool):
        self._tops_visible = bool(visible)
        self.update()
```

- `_paint_tops` 方法体开头加 `if not self._tops_visible: return`。
- `CrossWellCanvas` 加方法（放在 `seismic_tie` property 之后）：

```python
    def set_tops_visible(self, visible: bool):
        self._overlay.set_tops_visible(visible)
```

**4c. facade** `geo-viz-engine/geoviz/__init__.py`：在 `_COMPATIBILITY_EXPORTS` 映射中按现有模式加一行：

```python
    "FormationTop": ("geoviz_cross_well.tops_model", "FormationTop"),
```

- [ ] **Step 5: 运行测试确认通过 + 引擎回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests packages/geoviz_cross_well/tests -q
```

预期：全绿（含新测试；若有失败先确认是否早于本任务——`git stash` 验证）。

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest tests/test_cross_well_export.py tests/test_cross_well_picking.py -q
```

预期：全绿。

- [ ] **Step 6: 提交（geo-viz-engine 仓库）**

```bash
cd geo-viz-engine && git add packages/geoviz_well_log/geoviz_well_log/cross_well_widget.py packages/geoviz_cross_well/geoviz_cross_well/canvas.py geoviz/__init__.py packages/geoviz_well_log/tests/test_well_spacing.py packages/geoviz_cross_well/tests/test_tops_visibility.py && git commit -m "feat(cross-well): well spacing, tops visibility, track-by-label APIs + FormationTop facade export"
```

---

### Task 4: 地层对比页面工具条与交互接线

**Files:**
- Modify: `paleo_workbench/ui/pages/stratigraphy_correlation_page.py`
- Modify: `tests/test_geoviz_package_independence.py`（`GEOVIZ_PUBLIC_FACADE` 加 `"FormationTop"`）
- Test: `tests/test_stratigraphy_correlation_ui.py`

**Interfaces:**
- Consumes: Task 2 的 `load_well_tops` / `match_tops_to_wells` / `tops_to_intervals`；Task 3 的 `set_well_spacing` / `set_tops_visible` / `set_track_visible_by_label` / facade `FormationTop`。
- Produces: 页面交互契约（工具条控件 objectName 与行为，见测试）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_stratigraphy_correlation_ui.py`：

```python
"""UI tests for the stratigraphy correlation toolbar and tops injection."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from geoviz import CurveData, WellLogData

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.stratigraphy_correlation_page import StratigraphyCorrelationPage

DAT = (
    "#WellTops File From SMI\n"
    "A1 X 850.0 0 0 0 850.0 0\n"
    "A1 C1 1164.0 0 0 0 1164.0 0\n"
    "A2 C1 1200.0 0 0 0 1200.0 0\n"
    "GHOST C1 1300.0 0 0 0 1300.0 0\n"
)


def _log(name: str) -> WellLogData:
    return WellLogData(
        well_name=name,
        top_depth=800.0,
        bottom_depth=1600.0,
        curves=[
            CurveData(
                name="GR", unit="API",
                depth=[float(d) for d in range(800, 1601, 10)],
                values=[float(d % 100) for d in range(800, 1601, 10)],
                display_range=(0.0, 100.0),
            )
        ],
    )


def _project(tmp_path: Path) -> ProjectDocument:
    dat = tmp_path / "DC.dat"
    dat.write_text(DAT, encoding="utf-8")
    project = ProjectDocument.new("UI")
    project.resources.extend(
        [
            ResourceItem(name="A1.las", path="/a1.las", type="well_log", format="las"),
            ResourceItem(name="A2.las", path="/a2.las", type="well_log", format="las"),
            ResourceItem(name="DC.dat", path=str(dat), type="well_stratification", format="dat"),
        ]
    )
    return project


def _load_page(qtbot, tmp_path, monkeypatch) -> StratigraphyCorrelationPage:
    import paleo_workbench.ui.pages.stratigraphy_correlation_page as mod

    monkeypatch.setattr(
        mod,
        "load_correlation_wells",
        lambda project, resource_ids=None, max_wells=8: (
            [_log("A1"), _log("A2")], ["A1", "A2"], [],
        ),
    )
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_project(_project(tmp_path))
    page.update_state()
    page.load_section()
    return page


def test_toolbar_defaults(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    assert page.browse_btn.isChecked()
    assert page.cross_host.widget.pick_mode is False
    assert page.snap_combo.currentData() == "none"
    assert page.tops_visible_box.isChecked()
    assert page.spacing_slider.value() == 150


def test_pick_mode_toggle(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.pick_btn.setChecked(True)
    assert page.cross_host.widget.pick_mode is True
    page.browse_btn.setChecked(True)
    assert page.cross_host.widget.pick_mode is False


def test_manual_link_toggle(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    assert page.cross_host.inner._manual_link_active is False
    page.link_btn.setChecked(True)
    assert page.cross_host.inner._manual_link_active is True
    page.browse_btn.setChecked(True)
    assert page.cross_host.inner._manual_link_active is False


def test_snap_and_spacing_controls(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.snap_combo.setCurrentIndex(1)
    assert page.cross_host.widget.snap_type == "max"
    page.spacing_slider.setValue(80)
    assert page.cross_host.inner._container_layout.spacing() == 80


def test_tops_visibility_toggle(qtbot):
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.tops_visible_box.setChecked(False)
    assert page.cross_host.widget._overlay._tops_visible is False


def test_load_injects_tops_and_formation_data(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    model = page.cross_host.widget.tops_model
    assert [t.formation_name for t in model.tops_for_well("A1")] == ["X", "C1"]
    assert [t.formation_name for t in model.tops_for_well("A2")] == ["C1"]
    # GHOST well not loaded -> not injected, no crash
    assert model.tops_for_well("GHOST") == []
    formation_data = page.cross_host.inner._formation_data
    assert "A1" in formation_data
    assert formation_data["A1"][0].name == "X"
    assert formation_data["A1"][0].top == 850.0
    assert formation_data["A1"][0].bottom == 1164.0
    # Formation combo populated from tops
    items = [page.formation_combo.itemText(i) for i in range(page.formation_combo.count())]
    assert set(items) == {"X", "C1"}
    # Track checklist populated from canvas track labels
    assert page.track_list.count() > 0


def test_track_checklist_toggles_all_wells(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    item = page.track_list.item(0)
    item.setCheckState(Qt.CheckState.Unchecked)
    label = item.text()
    for canvas in page.cross_host.inner._canvases:
        for track in canvas.tracks:
            if (track.label or "") == label:
                assert track._visible is False


def test_undo_redo_buttons(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    model = page.cross_host.widget.picks_model
    model.add_pick("C1", "A1", 1164.0)
    assert len(model.all_picks()) == 1
    page.undo_btn.click()
    assert model.all_picks() == []
    page.redo_btn.click()
    assert len(model.all_picks()) == 1


def test_clear_section_resets_models(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    page.cross_host.widget.picks_model.add_pick("C1", "A1", 1164.0)
    page.clear_section()
    assert page.cross_host.widget.tops_model.all_tops() == []
    assert page.cross_host.widget.picks_model.all_picks() == []
    assert page.track_list.count() == 0
    assert page.formation_combo.count() == 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_stratigraphy_correlation_ui.py -v
```

预期：FAIL（`AttributeError: 'StratigraphyCorrelationPage' object has no attribute 'browse_btn'` 等；`FormationTop` import 错误）。

- [ ] **Step 3: 实现页面改动**

**3a. `tests/test_geoviz_package_independence.py`**：`GEOVIZ_PUBLIC_FACADE` 白名单加 `"FormationTop"`（保持文件现有排序/结构）。

**3b. `paleo_workbench/ui/pages/stratigraphy_correlation_page.py`**：

Import 区更新：
- QtWidgets import 块加 `QButtonGroup, QCheckBox, QComboBox, QSlider`。
- 新增 `from geoviz import FormationTop`。
- workflow import 块改为同时导入 `load_well_tops, match_tops_to_wells, tops_to_intervals`。

`__init__` 中：
- 新增状态行 `self._manual_link_on = False`（放在 `self._loaded_names` 初始化附近）。
- 中栏 `center_layout.addWidget(self.status_label)` 之后、`self.scroll_area` 创建之前，插入工具条：

```python
        # Toolbar: correlation modes and engine interactions
        toolbar = QHBoxLayout()
        toolbar.setSpacing(tokens.SPACE_2)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.browse_btn = QPushButton("浏览")
        self.pick_btn = QPushButton("拾取")
        self.link_btn = QPushButton("连线")
        for btn in (self.browse_btn, self.pick_btn, self.link_btn):
            btn.setObjectName("SecondaryButton")
            btn.setCheckable(True)
            self.mode_group.addButton(btn)
            btn.toggled.connect(self._on_mode_changed)
            toolbar.addWidget(btn)
        self.browse_btn.setChecked(True)

        self.formation_combo = QComboBox()
        self.formation_combo.setEditable(True)
        self.formation_combo.setPlaceholderText("拾取层位")
        self.formation_combo.setMinimumWidth(110)
        self.formation_combo.currentTextChanged.connect(self._on_formation_changed)
        toolbar.addWidget(self.formation_combo)

        self.snap_combo = QComboBox()
        self.snap_combo.addItem("不吸附", "none")
        self.snap_combo.addItem("波峰", "max")
        self.snap_combo.addItem("波谷", "min")
        self.snap_combo.currentIndexChanged.connect(self._on_snap_changed)
        toolbar.addWidget(self.snap_combo)

        self.dtw_btn = QPushButton("DTW 传播")
        self.dtw_btn.setObjectName("SecondaryButton")
        self.dtw_btn.clicked.connect(self._run_dtw)
        toolbar.addWidget(self.dtw_btn)
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setObjectName("SecondaryButton")
        self.undo_btn.clicked.connect(self._undo_pick)
        toolbar.addWidget(self.undo_btn)
        self.redo_btn = QPushButton("重做")
        self.redo_btn.setObjectName("SecondaryButton")
        self.redo_btn.clicked.connect(self._redo_pick)
        toolbar.addWidget(self.redo_btn)
        self.auto_link_btn = QPushButton("自动连线")
        self.auto_link_btn.setObjectName("SecondaryButton")
        self.auto_link_btn.clicked.connect(self._run_auto_link)
        toolbar.addWidget(self.auto_link_btn)

        self.tops_visible_box = QCheckBox("分层顶线")
        self.tops_visible_box.setChecked(True)
        self.tops_visible_box.toggled.connect(self._on_tops_visible)
        toolbar.addWidget(self.tops_visible_box)

        toolbar.addWidget(QLabel("间距"))
        self.spacing_slider = QSlider(Qt.Orientation.Horizontal)
        self.spacing_slider.setRange(50, 300)
        self.spacing_slider.setValue(150)
        self.spacing_slider.setFixedWidth(90)
        self.spacing_slider.valueChanged.connect(self._on_spacing_changed)
        toolbar.addWidget(self.spacing_slider)
        toolbar.addStretch()
        center_layout.addLayout(toolbar)
```

- 右栏 `right.addStretch()` 之前插入轨道显隐区：

```python
        track_title = QLabel("轨道显隐")
        track_title.setObjectName("MapDockTitle")
        right.addWidget(track_title)
        self.track_list = QListWidget()
        self.track_list.setObjectName("WorkListWidget")
        self.track_list.itemChanged.connect(self._on_track_item_changed)
        right.addWidget(self.track_list)
```

- 右栏 `self.export_btn` 之后加：

```python
        self.export_tops_btn = QPushButton("导出分层顶 CSV")
        self.export_tops_btn.setObjectName("SecondaryButton")
        self.export_tops_btn.clicked.connect(self._export_tops)
        right.addWidget(self.export_tops_btn)
```

**3c. 新方法**（加在类内，`selected_resource_ids` 之后）：

```python
    def _on_mode_changed(self) -> None:
        canvas = self.cross_host.widget
        canvas.pick_mode = self.pick_btn.isChecked()
        want_link = self.link_btn.isChecked()
        if want_link != self._manual_link_on:
            self.cross_host.inner.toggle_manual_link()
            self._manual_link_on = want_link

    def _on_formation_changed(self, text: str) -> None:
        self.cross_host.widget.active_formation = text.strip() or None

    def _on_snap_changed(self) -> None:
        self.cross_host.widget.snap_type = self.snap_combo.currentData()

    def _on_tops_visible(self, checked: bool) -> None:
        self.cross_host.widget.set_tops_visible(checked)

    def _on_spacing_changed(self, value: int) -> None:
        self.cross_host.inner.set_well_spacing(value)

    def _undo_pick(self) -> None:
        self.cross_host.widget.picks_model.undo()

    def _redo_pick(self) -> None:
        self.cross_host.widget.picks_model.redo()

    def _run_auto_link(self) -> None:
        self.cross_host.inner.auto_link()
        self.status_label.setText("已按同名分层自动连线")

    def _run_dtw(self) -> None:
        canvas = self.cross_host.widget
        picks = canvas.picks_model.all_picks()
        if not picks:
            self.status_label.setText("请先在拾取模式下添加一个参考拾取点")
            return
        ref = picks[-1]
        wells = ref.connected_wells()
        if not wells:
            return
        ref_well = wells[0]
        ref_depth = ref.depth_for_well(ref_well)
        created = canvas.propagate_pick_via_dtw(ref_well, ref_depth, ref.formation_name)
        self.status_label.setText(
            f"DTW 已为层位 {ref.formation_name} 生成 {len(created)} 个建议拾取"
            "（点击接受 / 右键拒绝）"
        )

    def _on_track_item_changed(self, item: QListWidgetItem) -> None:
        visible = item.checkState() == Qt.CheckState.Checked
        self.cross_host.inner.set_track_visible_by_label(item.text(), visible)

    def _inject_well_tops(self, names: list[str]) -> list[str]:
        """Inject 井分层 tops into tops model + formation data. Returns notices."""
        canvas = self.cross_host.widget
        canvas.tops_model.clear()
        canvas.picks_model.clear()
        notices: list[str] = []
        if self._project is None:
            return notices
        tops_by_well, warnings = load_well_tops(self._project)
        notices.extend(warnings)
        matched, unmatched = match_tops_to_wells(tops_by_well, names)
        for well, tops in matched.items():
            for top_name, depth in tops:
                canvas.tops_model.add_top(FormationTop(well, top_name, depth))
            self.cross_host.inner.set_formation_data(well, tops_to_intervals(tops))
        if unmatched:
            notices.append("分层井未在剖面中: " + ", ".join(unmatched))
        self.formation_combo.clear()
        self.formation_combo.addItems(canvas.tops_model.formation_names())
        return notices

    def _refresh_track_list(self) -> None:
        self.track_list.blockSignals(True)
        self.track_list.clear()
        seen: list[str] = []
        for canvas in self.cross_host.inner._canvases:
            for track in canvas.tracks:
                label = track.label or ""
                if label and label not in seen:
                    seen.append(label)
        for label in seen:
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.track_list.addItem(item)
        self.track_list.blockSignals(False)

    def _export_tops(self) -> None:
        model = self.cross_host.widget.tops_model
        if not model.all_tops():
            QMessageBox.warning(self, "导出", "没有分层顶数据")
            return
        start_dir = default_export_dir(
            Path(self._project.meta.project_root) / "x.paleo.json"
            if self._project and self._project.meta.project_root not in ("", ".")
            else None
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出分层顶 CSV",
            str(start_dir / "well_tops.csv"),
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            model.save_csv(path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"{exc.__class__.__name__}: {exc}")
            return
        QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")
```

**3d. `load_section` 接线**：在 `ok = self.cross_host.apply(payload)` 之后加两行：

```python
        top_notices = self._inject_well_tops(names)
        self._refresh_track_list()
```

并把状态行 `msg = f"已加载 {len(names)} 口井"` 之后加：

```python
        if top_notices:
            msg += "；" + "；".join(top_notices[:2])
```

**3e. `clear_section` 扩展**：方法体在 `self.cross_host.clear()` 之后加：

```python
        canvas = self.cross_host.widget
        canvas.tops_model.clear()
        canvas.picks_model.clear()
        self.formation_combo.clear()
        self.track_list.clear()
```

- [ ] **Step 4: 运行测试确认通过 + 相关回归**

```bash
.venv/bin/python -m pytest tests/test_stratigraphy_correlation_ui.py tests/test_stratigraphy_correlation.py tests/test_stratigraphy_correlation_tops.py tests/test_geoviz_package_independence.py -v
```

预期：全绿。

- [ ] **Step 5: workbench 全量回归**

```bash
.venv/bin/python -m pytest tests -q
```

预期：全绿。

- [ ] **Step 6: 提交（仓库根，含子模块 gitlink）**

```bash
git add paleo_workbench/ui/pages/stratigraphy_correlation_page.py tests/test_stratigraphy_correlation_ui.py tests/test_geoviz_package_independence.py geo-viz-engine && git commit -m "feat(ui): correlation toolbar with pick/DTW/link modes, well tops injection, track visibility"
```

---

### Task 5: 最终回归与文档记录

**Files:**
- Modify: `task_plan.md`、`progress.md`

**Interfaces:**
- Consumes: Task 1-4 全部完成。
- Produces: 无代码产出。

- [ ] **Step 1: 双仓库全量回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests packages/geoviz_cross_well/tests tests/test_cross_well_export.py tests/test_cross_well_picking.py tests/test_las_parser.py -q
```

```bash
.venv/bin/python -m pytest tests -q
```

预期：两边全绿（引擎 `tests/test_geoviz_well_log_preview.py` 的 3 个失败为 P1 已确认的既有失败，不在本命令范围）。

- [ ] **Step 2: 真实数据冒烟（只读验证，不提交）**

```bash
.venv/bin/python -c "
from paleo_workbench.resources.well_tops_parser import parse_well_tops
tops = parse_well_tops('data/井分层/DC.dat')
wells = sorted({t.well_name for t in tops})
print(len(tops), 'tops,', len(wells), 'wells:', wells[:8])
"
```

预期：输出约 500+ tops、约 20 口井（A1、A10…）。

- [ ] **Step 3: 更新 task_plan.md 与 progress.md**

`task_plan.md` Phase 11 后追加：

```markdown
### Phase 12: 连井对比 P2 井分层接入 + 对比交互

- [x] 新增 SMI WellTops 解析器与工作流接入（`load_well_tops` / `match_tops_to_wells` / `tops_to_intervals`）
- [x] 引擎补 `set_well_spacing` / `set_tops_visible` / `set_track_visible_by_label` API 与 `FormationTop` facade 导出
- [x] 地层对比页工具条：浏览/拾取/连线模式、层位与吸附选择、DTW 传播、撤销/重做、自动连线、分层顶线开关、井间距滑杆、轨道显隐、分层顶 CSV 导出
- **Status:** complete
```

`progress.md` 追加对应一行 session 记录。

- [ ] **Step 4: 提交（仓库根）**

```bash
git add task_plan.md progress.md && git commit -m "docs(plan): record phase 12 cross-well tops integration and correlation UI"
```

---

## Self-Review 记录

- **Spec 覆盖**：P2 数据通道（解析器→Task 1；`load_well_tops`/双路注入→Task 2+4）；UI 交互（模式切换/DTW/撤销重做/自动连线/顶线开关/轨道显隐/井间距/导出 CSV→Task 4，引擎 API→Task 3）。spec 中"吸附类型"归入拾取模式 UI（snap_combo）。全部有任务对应。
- **占位符扫描**：无 TBD/TODO；所有代码步骤含完整代码与命令。
- **类型一致性**：`load_well_tops`/`match_tops_to_wells`/`tops_to_intervals` 签名在 Task 2 定义、Task 4 消费一致；`FormationTop(well_name, formation_name, depth_m)` 与引擎 `tops_model.py:33-37` 一致；`set_well_spacing`/`set_tops_visible`/`set_track_visible_by_label` 在 Task 3 定义、Task 4 消费一致；`HorizonPick.connected_wells()`/`depth_for_well()`/`formation_name` 与 `picks_model.py:12-37` 一致；`track.label` 与引擎 tooltip 代码 `getattr(track, "label", ...)` 用法一致。
- **范围说明**：spec 中"`CompositeVisualizationPanel` 按需同步受益"——其连井 tab 复用同一 `CrossWellHost`，自动获得引擎新 API 与 P1 性能收益，本计划不为其新增 UI（符合 spec 原文）。
