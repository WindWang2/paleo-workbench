# 连井对比 P1 性能优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除连井对比多井缩放/平移卡顿，加速 LAS 加载（C++ LOD 注入、缓存级联失效修复、LAS C++ 解析、离屏绘制跳过）。

**Architecture:** 引擎侧（`geo-viz-engine/`）做可注入 downsample 钩子、`set_depth_range` 无操作守卫、离屏绘制跳过；workbench 侧（`paleo_workbench/`）启动时注入 C++ `minmax_downsample`，LAS 加载切换到 `fast_las_parse_data` 快速通道并保留 `load_las_preview` 保底。引擎默认行为完全不变（向后兼容）。

**Tech Stack:** PySide6 / Qt（offscreen 测试）、NumPy、pybind11 C++ 扩展 `well_log_core`（已构建）、pytest。

**Spec:** `docs/superpowers/specs/2026-07-21-cross-well-correlation-optimization-design.md`

## Global Constraints

- 不制造 `geoviz` → `paleo_workbench` 反向依赖：引擎侧只做通用钩子，C++ 注入由 workbench 完成。
- 引擎所有改动默认行为不变；现有测试不得修改（只能新增）。
- 所有命令使用项目 venv：仓库根下为 `.venv/bin/python`（geo-viz-engine 的命令从其子目录执行时写作 `../.venv/bin/python`）。
- Qt 测试需要 `QT_QPA_PLATFORM=offscreen` 与 QApplication fixture（见各任务测试代码，自包含）。
- 两个独立 git 仓库：引擎改动在 `geo-viz-engine/` 内提交，workbench 改动在仓库根提交。
- 遵循 TDD：先写失败测试，再实现。

---

### Task 1: 引擎可注入 downsample 钩子

**Files:**
- Create: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/downsample.py`
- Modify: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/curve_track.py:89-112`（`_downsample` 方法）
- Test: `geo-viz-engine/packages/geoviz_well_log/tests/test_downsample.py`

**Interfaces:**
- Produces（后续任务依赖）:
  - `geoviz_well_log.renderer.downsample.numpy_minmax_downsample(depths: list[float], values: list[float], pixel_height: int) -> tuple[list[float], list[float]]` — 引擎默认实现（即当前 `CurveTrack._downsample` 逻辑原样搬迁）。
  - `geoviz_well_log.renderer.downsample.get_downsample_provider() -> Callable[[list, list, int], tuple[list, list]]`
  - `geoviz_well_log.renderer.downsample.set_downsample_provider(fn: Callable | None) -> None` — 传 `None` 恢复默认。

- [ ] **Step 1: 写失败测试**

创建 `geo-viz-engine/packages/geoviz_well_log/tests/test_downsample.py`：

```python
"""Tests for the injectable curve downsample provider."""
from __future__ import annotations

from geoviz_well_log.renderer.downsample import (
    get_downsample_provider,
    numpy_minmax_downsample,
    set_downsample_provider,
)


def _sample(n: int = 1000):
    depths = [float(i) for i in range(n)]
    values = [float((i * 37) % 101) for i in range(n)]
    return depths, values


def test_default_provider_is_numpy_impl():
    assert get_downsample_provider() is numpy_minmax_downsample


def test_numpy_downsample_preserves_extrema_and_order():
    depths, values = _sample()
    out_d, out_v = numpy_minmax_downsample(depths, values, 50)
    assert len(out_d) == len(out_v)
    assert len(out_d) <= 2 * 50 + 2
    assert max(out_v) == max(values)
    assert min(out_v) == min(values)
    # Depth order non-decreasing (no zigzag)
    assert all(b >= a for a, b in zip(out_d, out_d[1:]))


def test_numpy_downsample_passthrough_when_small():
    depths, values = _sample(40)
    out_d, out_v = numpy_minmax_downsample(depths, values, 50)
    assert out_d == depths
    assert out_v == values


def test_set_and_reset_provider():
    calls = []

    def fake(depths, values, pixel_height):
        calls.append(pixel_height)
        return depths[:2], values[:2]

    set_downsample_provider(fake)
    try:
        assert get_downsample_provider() is fake
        out_d, out_v = get_downsample_provider()([1.0, 2.0, 3.0], [4.0, 5.0, 6.0], 10)
        assert out_d == [1.0, 2.0]
        assert calls == [10]
    finally:
        set_downsample_provider(None)
    assert get_downsample_provider() is numpy_minmax_downsample


def test_curve_track_delegates_to_provider():
    """CurveTrack._downsample must route through the module provider."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    from geoviz_well_log.models import CurveData
    from geoviz_well_log.renderer.curve_track import CurveTrack

    curve = CurveData(
        name="GR", unit="API",
        depth=[float(i) for i in range(10)],
        values=[float(i) for i in range(10)],
        display_range=(0.0, 10.0),
    )
    track = CurveTrack([curve])

    seen = []

    def spy(depths, values, pixel_height):
        seen.append((len(depths), pixel_height))
        return depths, values

    set_downsample_provider(spy)
    try:
        track._downsample([1.0, 2.0], [3.0, 4.0], 100)
    finally:
        set_downsample_provider(None)
    assert seen == [(2, 100)]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests/test_downsample.py -v
```

预期：FAIL（`ModuleNotFoundError: geoviz_well_log.renderer.downsample`）。

- [ ] **Step 3: 实现 downsample 模块**

创建 `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/downsample.py`：

```python
"""Injectable Min-Max LOD downsampling for curve rendering.

Default provider is the engine's NumPy implementation. Host applications
(e.g. paleo_workbench) may inject a C++-accelerated provider at startup via
``set_downsample_provider`` — the engine itself has no such dependency.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

DownsampleFn = Callable[
    [list[float], list[float], int], tuple[list[float], list[float]]
]


def numpy_minmax_downsample(
    depths: list[float], values: list[float], pixel_height: int
) -> tuple[list[float], list[float]]:
    """Min-max 2-points-per-bin downsampling (engine default)."""
    if len(depths) <= pixel_height * 2:
        return depths, values
    arr_v = np.array(values)
    step = max(1, len(arr_v) // pixel_height)
    result_d: list[float] = []
    result_v: list[float] = []
    for i in range(0, len(arr_v), step):
        chunk = arr_v[i:i + step]
        max_idx = i + int(np.argmax(chunk))
        min_idx = i + int(np.argmin(chunk))
        # Emit in depth order to avoid zigzag artifacts
        if max_idx <= min_idx:
            result_d.append(depths[max_idx])
            result_v.append(values[max_idx])
            result_d.append(depths[min_idx])
            result_v.append(values[min_idx])
        else:
            result_d.append(depths[min_idx])
            result_v.append(values[min_idx])
            result_d.append(depths[max_idx])
            result_v.append(values[max_idx])
    return result_d, result_v


_provider: DownsampleFn = numpy_minmax_downsample


def get_downsample_provider() -> DownsampleFn:
    return _provider


def set_downsample_provider(fn: DownsampleFn | None) -> None:
    """Install a custom downsample provider; ``None`` restores the default."""
    global _provider
    _provider = fn if fn is not None else numpy_minmax_downsample
```

- [ ] **Step 4: CurveTrack 改为委托给 provider**

在 `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/curve_track.py` 中：

文件顶部 import 区（第 12-14 行附近）加一行：

```python
from .downsample import get_downsample_provider
```

将 `_downsample` 方法（第 89-112 行）整体替换为：

```python
    def _downsample(self, depths: list[float], values: list[float],
                    pixel_height: int) -> tuple[list[float], list[float]]:
        return get_downsample_provider()(depths, values, pixel_height)
```

注意：替换后若 `numpy as np` 在该文件中仍被 `paint_content` 使用（是的，第 201-223 行用到），保留 `import numpy as np` 不动。

- [ ] **Step 5: 运行测试确认通过 + 引擎相关回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests/test_downsample.py -v
```

预期：5 passed。

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests tests/test_geoviz_well_log_preview.py tests/test_las_parser.py -q
```

预期：全绿。

- [ ] **Step 6: 提交（geo-viz-engine 仓库）**

```bash
cd geo-viz-engine && git add packages/geoviz_well_log/geoviz_well_log/renderer/downsample.py packages/geoviz_well_log/geoviz_well_log/renderer/curve_track.py packages/geoviz_well_log/tests/test_downsample.py && git commit -m "perf(well-log): injectable downsample provider for curve rendering"
```

---

### Task 2: workbench 启动时注入 C++ downsample

**Files:**
- Create: `paleo_workbench/viz/render_accel.py`
- Modify: `paleo_workbench/main.py`（在 `main()` 中创建 QApplication 之后、建窗口之前调用安装）
- Test: `tests/test_render_accel.py`

**Interfaces:**
- Consumes: Task 1 的 `set_downsample_provider` / `get_downsample_provider` / `numpy_minmax_downsample`；`paleo_workbench.viz.well_log_api.minmax_downsample(depth: np.ndarray, values: np.ndarray, target_pixels: int) -> tuple[np.ndarray, np.ndarray]`（已存在，C++ 优先、NumPy 保底）。
- Produces: `paleo_workbench.viz.render_accel.install_geoviz_acceleration() -> None`（幂等）。

先读 `paleo_workbench/main.py` 确认 `main()` 结构后再改。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_render_accel.py`：

```python
"""Tests for C++ downsample injection into the geoviz engine."""
from __future__ import annotations

import numpy as np

from geoviz_well_log.renderer.downsample import (
    get_downsample_provider,
    numpy_minmax_downsample,
    set_downsample_provider,
)

from paleo_workbench.viz.render_accel import install_geoviz_acceleration


def setup_function():
    set_downsample_provider(None)


def teardown_function():
    set_downsample_provider(None)


def test_install_replaces_provider():
    assert get_downsample_provider() is numpy_minmax_downsample
    install_geoviz_acceleration()
    assert get_downsample_provider() is not numpy_minmax_downsample


def test_install_is_idempotent():
    install_geoviz_acceleration()
    first = get_downsample_provider()
    install_geoviz_acceleration()
    assert get_downsample_provider() is first


def test_injected_provider_preserves_extrema_and_order():
    install_geoviz_acceleration()
    provider = get_downsample_provider()
    n = 5000
    depths = [float(i) * 0.125 for i in range(n)]
    rng = np.random.default_rng(42)
    values = (rng.random(n) * 100).tolist()
    out_d, out_v = provider(depths, values, 200)
    assert len(out_d) == len(out_v)
    assert len(out_d) <= 2 * 200 + 4
    assert max(out_v) == max(values)
    assert min(out_v) == min(values)
    assert all(b >= a for a, b in zip(out_d, out_d[1:]))


def test_injected_provider_passthrough_when_small():
    install_geoviz_acceleration()
    provider = get_downsample_provider()
    out_d, out_v = provider([1.0, 2.0], [3.0, 4.0], 100)
    assert list(out_d) == [1.0, 2.0]
    assert list(out_v) == [3.0, 4.0]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_render_accel.py -v
```

预期：FAIL（`ModuleNotFoundError: paleo_workbench.viz.render_accel`）。

- [ ] **Step 3: 实现注入模块**

创建 `paleo_workbench/viz/render_accel.py`：

```python
"""Install C++-accelerated render hooks into the geoviz engine.

Called once at application startup. The engine side
(``geoviz_well_log.renderer.downsample``) defines the hook point; this module
is the only place that knows about the workbench's C++ backend, keeping the
engine free of reverse dependencies.
"""
from __future__ import annotations

import numpy as np

from paleo_workbench.viz.well_log_api import minmax_downsample

_installed_provider = None


def _cpp_minmax_provider(
    depths: list[float], values: list[float], pixel_height: int
) -> tuple[list[float], list[float]]:
    if len(depths) <= pixel_height * 2:
        return depths, values
    d = np.asarray(depths, dtype=np.float32)
    v = np.asarray(values, dtype=np.float32)
    out_d, out_v = minmax_downsample(d, v, int(pixel_height))
    return out_d.tolist(), out_v.tolist()


def install_geoviz_acceleration() -> None:
    """Inject the C++ min-max downsample provider into geoviz (idempotent)."""
    global _installed_provider
    if _installed_provider is not None:
        return
    from geoviz_well_log.renderer.downsample import set_downsample_provider

    set_downsample_provider(_cpp_minmax_provider)
    _installed_provider = _cpp_minmax_provider
```

注意：`minmax_downsample` 的 C++/NumPy 保底语义与引擎默认实现一致（min/max 保真、深度有序、每 bin 最多 2 点），满足测试断言。

- [ ] **Step 4: 接入启动流程**

读 `paleo_workbench/main.py`，在 `main()` 中 `QApplication(sys.argv)` 之后、创建主窗口之前插入：

```python
    from paleo_workbench.viz.render_accel import install_geoviz_acceleration
    install_geoviz_acceleration()
```

（若文件顶部已有该 import 位置的集中 import 区风格，遵循现有文件风格放置 import。）

- [ ] **Step 5: 运行测试确认通过 + workbench 回归**

```bash
.venv/bin/python -m pytest tests/test_render_accel.py -v
```

预期：4 passed。

```bash
.venv/bin/python -m pytest tests -q
```

预期：全量全绿（基线 1130+）。

- [ ] **Step 6: 提交（仓库根）**

```bash
git add paleo_workbench/viz/render_accel.py paleo_workbench/main.py tests/test_render_accel.py && git commit -m "perf(viz): inject C++ minmax downsample into geoviz curve rendering at startup"
```

---

### Task 3: `set_depth_range` 无操作守卫（修复缓存级联失效）

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/canvas.py:122-127`（`set_depth_range`）
- Test: `geo-viz-engine/packages/geoviz_well_log/tests/test_canvas_depth_guard.py`

**Interfaces:**
- Consumes: 无（独立改动）。
- Produces: 行为契约——`WellLogCanvas.set_depth_range(top, bottom)` 在与当前范围相同（容差 1e-9）时不失效缓存、不发信号、不触发 update。

背景：`QPainterSyncManager._on_range_changed` 对**所有** canvas（含信号发起者）调用 `set_depth_range`；发起者会被二次失效整幅 QPixmap 缓存。无操作守卫消除该冗余。

- [ ] **Step 1: 写失败测试**

创建 `geo-viz-engine/packages/geoviz_well_log/tests/test_canvas_depth_guard.py`：

```python
"""WellLogCanvas.set_depth_range no-op guard tests."""
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
        depth=[float(i) for i in range(100)],
        values=[float(i) for i in range(100)],
        display_range=(0.0, 100.0),
    )
    canvas = WellLogCanvas()
    canvas.add_track(CurveTrack([curve]))
    return canvas


def test_identical_range_is_noop(qapp):
    canvas = _make_canvas()
    canvas.set_depth_range(2000.0, 3000.0)
    canvas._cache_dirty = False

    emissions = []
    canvas.depth_range_changed.connect(lambda t, b: emissions.append((t, b)))
    canvas.set_depth_range(2000.0, 3000.0)

    assert emissions == []
    assert canvas._cache_dirty is False


def test_changed_range_invalidates_and_emits(qapp):
    canvas = _make_canvas()
    canvas.set_depth_range(2000.0, 3000.0)
    canvas._cache_dirty = False

    emissions = []
    canvas.depth_range_changed.connect(lambda t, b: emissions.append((t, b)))
    canvas.set_depth_range(2100.0, 3000.0)

    assert emissions == [(2100.0, 3000.0)]
    assert canvas._cache_dirty is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests/test_canvas_depth_guard.py -v
```

预期：`test_identical_range_is_noop` FAIL（当前实现总会 emit 并置脏）。

- [ ] **Step 3: 实现守卫**

将 `canvas.py` 的 `set_depth_range`（第 122-127 行）替换为：

```python
    def set_depth_range(self, top: float, bottom: float):
        if self.tracks:
            cur_top = self.tracks[0].depth_top
            cur_bottom = self.tracks[0].depth_bottom
            if abs(top - cur_top) < 1e-9 and abs(bottom - cur_bottom) < 1e-9:
                return  # no-op: avoid cascade cache invalidation across wells
        self._depth_span = bottom - top
        self._coordinator.set_depth_range(top, bottom)
        self._cache_dirty = True
        self.depth_range_changed.emit(top, bottom)
        self.update()
```

- [ ] **Step 4: 运行测试确认通过 + 引擎回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests -q
```

预期：全绿（含新 2 个测试）。

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest tests/test_qpainter_widget.py tests/test_well_log_ui.py -q
```

预期：全绿（若这两个文件不存在，改用 `../.venv/bin/python -m pytest tests -q -k "well_log or qpainter or cross_well"`）。

- [ ] **Step 5: 提交（geo-viz-engine 仓库）**

```bash
cd geo-viz-engine && git add packages/geoviz_well_log/geoviz_well_log/renderer/canvas.py packages/geoviz_well_log/tests/test_canvas_depth_guard.py && git commit -m "perf(well-log): skip no-op set_depth_range to stop cache cascade invalidation"
```

---

### Task 4: LAS 加载切换 C++ 快速通道

**Files:**
- Modify: `paleo_workbench/viz/well_log_load.py`
- Test: `tests/test_well_log_load_fast.py`

**Interfaces:**
- Consumes: `paleo_workbench.viz.well_log_api.fast_las_parse_data(content: str) -> tuple[tuple[str, ...], np.ndarray]`（已存在）；`geoviz.inspect_las_file(path)` → `LASPreviewHeader(well_name, null_value, depth_index, curves, row_count, ...)`，其 `non_depth_curves` 属性返回非深度曲线（`LASCurveHeader(index, mnemonic, unit, description)`）；`geoviz_well_log.las_preview.curve_data_from_arrays(header: LASCurveHeader, depth: np.ndarray, values: np.ndarray) -> CurveData`。
- Produces: `load_well_log_from_path(path)` 行为不变（签名与返回类型不变），LAS 走快速通道、失败自动回退 `load_las_preview`；XML 路径不动。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_well_log_load_fast.py`：

```python
"""Tests for the C++ fast LAS loading channel in well_log_load."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from paleo_workbench.viz.well_log_load import load_well_log_from_path

SAMPLE_LAS = """~VERSION INFORMATION
 VERS .                 2.0 : CWLS LOG ASCII STANDARD -VERSION 2.0
 WRAP .                  NO : ONE LINE PER DEPTH STEP
~WELL INFORMATION
 WELL.             WELL-01 : WELL NAME
 STRT.M             2000.00 : START DEPTH
 STOP.M             2005.00 : STOP DEPTH
 STEP.M                1.00 : STEP
 NULL.              -999.25 : NULL VALUE
~CURVE INFORMATION
 DEPT  .M                   : DEPTH
 GR    .API                 : GAMMA RAY
 DT    .US/M                : ACOUSTIC TRANSIT TIME
~ASCII
 2000.00   45.2   220.0
 2001.00   52.1   -999.25
 2002.00   61.8   215.4
 2003.00   -999.25 210.1
 2004.00   75.3   205.0
 2005.00   80.0   200.0
"""


def _write_las(tmp_path: Path) -> Path:
    path = tmp_path / "well.las"
    path.write_text(SAMPLE_LAS, encoding="utf-8")
    return path


def test_fast_channel_loads_curves_with_units(tmp_path: Path):
    path = _write_las(tmp_path)
    data = load_well_log_from_path(str(path))
    assert data is not None
    assert data.well_name == "WELL-01"
    by_name = {c.name: c for c in data.curves}
    assert set(by_name) == {"GR", "DT"}
    assert by_name["GR"].unit == "API"
    assert by_name["DT"].unit == "US/M"
    assert data.top_depth == 2000.0
    assert data.bottom_depth == 2005.0
    assert len(by_name["GR"].depth) == 6


def test_fast_channel_null_values_become_nan(tmp_path: Path):
    path = _write_las(tmp_path)
    data = load_well_log_from_path(str(path))
    by_name = {c.name: c for c in data.curves}
    assert np.isnan(by_name["DT"].values[1])
    assert np.isnan(by_name["GR"].values[3])
    assert by_name["GR"].values[0] == 45.2


def test_fallback_when_fast_channel_raises(tmp_path: Path, monkeypatch):
    path = _write_las(tmp_path)
    import paleo_workbench.viz.well_log_load as mod

    def _boom(content):
        raise RuntimeError("cpp broken")

    monkeypatch.setattr(mod, "fast_las_parse_data", _boom)
    data = load_well_log_from_path(str(path))
    # Falls back to engine load_las_preview — still loads
    assert data is not None
    assert data.well_name == "WELL-01"
    assert {c.name for c in data.curves} == {"GR", "DT"}
```

注意第三个测试要求 `well_log_load.py` 在**模块顶部** `from paleo_workbench.viz.well_log_api import fast_las_parse_data`（而非函数内 import），monkeypatch 才能生效。

- [ ] **Step 2: 运行测试确认前两个失败**

```bash
.venv/bin/python -m pytest tests/test_well_log_load_fast.py -v
```

预期：`test_fast_channel_null_values_become_nan` FAIL（当前 `load_las_preview` 通道不保 NaN 语义/或行为不同），至少有一个测试失败。若 `test_fast_channel_loads_curves_with_units` 恰好通过（旧通道也能加载），属正常——以 NaN 与 fallback 测试为 RED 依据。

- [ ] **Step 3: 实现快速通道**

将 `paleo_workbench/viz/well_log_load.py` 整体替换为：

```python
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from paleo_workbench.viz.well_log_api import fast_las_parse_data

# Align bounds with geo-viz-engine WellLogPreviewBackend defaults.
MAX_CURVES = 30
MAX_SAMPLES = 100_000


def _load_las_fast(file_path: Path) -> Any | None:
    """Fast LAS channel: engine header parse + C++ data-block parse.

    Returns ``None`` on any inconsistency so the caller can fall back to the
    engine's bounded ``load_las_preview``.
    """
    from geoviz import inspect_las_file
    from geoviz_well_log.las_preview import curve_data_from_arrays

    header = inspect_las_file(str(file_path))
    selected = header.non_depth_curves[:MAX_CURVES]
    if not selected:
        return None
    content = file_path.read_text(encoding="utf-8", errors="replace")
    _headers, arr = fast_las_parse_data(content)
    if arr.ndim != 2 or arr.shape[0] < 2:
        return None
    max_index = max(item.index for item in selected + (header.curves[header.depth_index],))
    if arr.shape[1] <= max_index:
        return None

    depth = arr[:, header.depth_index].astype(np.float64)
    valid = np.isfinite(depth)
    if int(valid.sum()) < 2:
        return None
    arr = arr[valid]
    depth = depth[valid]

    n = len(depth)
    stride = max(1, math.ceil(n / MAX_SAMPLES))
    idx = np.arange(0, n, stride)
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    depth_s = depth[idx]

    from geoviz import WellLogData

    curves = [
        curve_data_from_arrays(item, depth_s, arr[idx, item.index].astype(np.float64))
        for item in selected
    ]
    return WellLogData(
        well_name=header.well_name or file_path.stem,
        top_depth=float(np.nanmin(depth_s)),
        bottom_depth=float(np.nanmax(depth_s)),
        curves=curves,
    )


def load_well_log_from_path(path: str) -> Any | None:
    """Return engine ``WellLogData``; LAS prefers the C++ fast channel.

    Supports both LAS and XML well log files. Falls back to the engine's
    bounded preview loader whenever the fast channel cannot handle a file.
    """
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        from geoviz import load_las_preview, load_xml_preview
    except Exception:
        return None

    try:
        if file_path.suffix.lower() == ".xml":
            return load_xml_preview(
                str(file_path),
                max_curves=MAX_CURVES,
                max_samples=MAX_SAMPLES,
            )
        try:
            fast = _load_las_fast(file_path)
        except Exception:
            fast = None
        if fast is not None:
            return fast
        return load_las_preview(
            str(file_path),
            max_curves=MAX_CURVES,
            max_samples=MAX_SAMPLES,
        )
    except Exception:
        return None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_well_log_load_fast.py tests/test_viz_adapter.py -v
```

预期：全绿。

- [ ] **Step 5: workbench 全量回归**

```bash
.venv/bin/python -m pytest tests -q
```

预期：全绿。

- [ ] **Step 6: 提交（仓库根）**

```bash
git add paleo_workbench/viz/well_log_load.py tests/test_well_log_load_fast.py && git commit -m "perf(viz): route LAS loading through C++ fast_las_parse_data with engine fallback"
```

---

### Task 5: 离屏绘制跳过 + 最终回归与文档

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/canvas.py:200-219`（`paintEvent`）
- Test: `geo-viz-engine/packages/geoviz_well_log/tests/test_canvas_offscreen_skip.py`
- Modify: `task_plan.md`（追加 Phase 11 记录）

**Interfaces:**
- Consumes: 无。
- Produces: 行为契约——canvas 完全不可见（滚动出视口）时 `paintEvent` 直接返回且保持 `_cache_dirty` 不变，可见后一次性重绘。

- [ ] **Step 1: 写失败测试**

创建 `geo-viz-engine/packages/geoviz_well_log/tests/test_canvas_offscreen_skip.py`：

```python
"""Off-screen WellLogCanvas skips rasterization until visible."""
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
        depth=[float(i) for i in range(100)],
        values=[float(i) for i in range(100)],
        display_range=(0.0, 100.0),
    )
    canvas = WellLogCanvas()
    canvas.add_track(CurveTrack([curve]))
    return canvas


def test_hidden_canvas_skips_repaint(qapp):
    canvas = _make_canvas()  # never shown -> visibleRegion empty
    canvas.set_depth_range(2000.0, 3000.0)
    assert canvas._cache_dirty is True
    canvas.repaint()  # synchronous paint; should early-return while hidden
    qapp.processEvents()
    assert canvas._cache_dirty is True  # deferred, not rasterized
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests/test_canvas_offscreen_skip.py -v
```

预期：FAIL（当前隐藏时也会重栅格化，`_cache_dirty` 变 False）。

- [ ] **Step 3: 实现跳过逻辑**

在 `canvas.py` 的 `paintEvent`（第 200 行）方法体最前面加：

```python
    def paintEvent(self, event):
        if self.visibleRegion().isEmpty():
            return  # off-screen in scroll area: defer rasterization
        dpr = self.devicePixelRatioF()
        ...
```

（即只在原方法体首行之前插入 guard，其余代码不动。）

- [ ] **Step 4: 运行测试确认通过 + 引擎回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests -q
```

预期：全绿。

- [ ] **Step 5: 双仓库全量回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests tests/test_las_parser.py tests/test_geoviz_well_log_preview.py -q
```

```bash
.venv/bin/python -m pytest tests -q
```

预期：两边全绿。

- [ ] **Step 6: 更新 task_plan.md**

在 `task_plan.md` Phase 10 之后追加：

```markdown
### Phase 11: 连井对比 P1 性能优化

- [x] 引擎曲线渲染接入可注入 downsample 钩子，启动时注入 C++ `minmax_downsample`
- [x] 修复 `set_depth_range` 无操作导致的全井缓存级联失效
- [x] LAS 加载切换 C++ `fast_las_parse_data` 快速通道（保留引擎保底回退）
- [x] 离屏 canvas 跳过栅格化（QScrollArea 视口外延迟重绘）
- **Status:** complete
```

- [ ] **Step 7: 提交（两个仓库）**

```bash
cd geo-viz-engine && git add packages/geoviz_well_log/geoviz_well_log/renderer/canvas.py packages/geoviz_well_log/tests/test_canvas_offscreen_skip.py && git commit -m "perf(well-log): skip rasterization for off-screen canvases in scroll viewport"
```

```bash
git add task_plan.md && git commit -m "docs(plan): record phase 11 cross-well P1 performance optimization"
```

---

## Self-Review 记录

- **Spec 覆盖**：P1 四项（C++ LOD 注入 → Task 1+2；缓存级联 → Task 3；LAS C++ → Task 4；视口裁剪 → Task 5）全部有对应任务。P2/P3 不在本计划范围（后续单独计划）。
- **占位符扫描**：无 TBD/TODO；所有代码步骤含完整代码。
- **类型一致性**：`set_downsample_provider(fn | None)`、`get_downsample_provider()`、`numpy_minmax_downsample` 在 Task 1 定义，Task 2 消费一致；`fast_las_parse_data` 签名与 `well_log_api.py` 现状一致；`curve_data_from_arrays(header, depth, values)` 与引擎 `las_preview.py:307` 一致；`header.depth_index` / `non_depth_curves` / `LASCurveHeader.index` 与 `las_preview.py:14-33` 一致。
