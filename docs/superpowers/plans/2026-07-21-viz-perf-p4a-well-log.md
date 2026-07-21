# P4 阶段 A 测井渲染通道性能实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除测井曲线渲染链路中的 Python list↔ndarray 封送开销（占该环节约 98%），修复表头 O(n) 扫描与 NaN bug、path cache 永不命中、预览 lasio 全文件读取、LAS C++ 解析器 GIL/效率问题。

**Architecture:** `CurveTrack` 内部全程 ndarray（`CurveData` 公共模型不动）；引擎 downsample 钩子协议升级为 ndarray 进 ndarray 出并迁移唯一注入方 `render_accel.py`；预览表格改用 C++ 解析；`well_log_core` LAS 解析器释放 GIL 并优化解析原语。

**Tech Stack:** PySide6/Qt（offscreen）、NumPy、pybind11（well_log_core）、pytest。

**Spec:** `docs/superpowers/specs/2026-07-21-viz-perf-hardening-design.md`（阶段 A）

## Global Constraints

- `CurveData` pydantic 公共模型（`depth`/`values: list[float]`）**不变**；ndarray 化只发生在 `CurveTrack` 内部。
- 渲染输出与现状逐点一致（抽稀结果、可见窗口、坐标映射），用等价测试锁定。
- workbench 生产代码只允许 `from geoviz import ...` facade 导入。
- 协议变更允许修改 P1 新建的 `test_downsample.py` 与 `test_render_accel.py`（同一协议的配套迁移），其他现有测试不得修改。
- 两个独立 git 仓库：引擎改动在 `geo-viz-engine/` 提交，workbench/native 改动在仓库根提交。
- 所有命令使用项目 venv：仓库根 `.venv/bin/python`；geo-viz-engine 内 `../.venv/bin/python`。
- 遵循 TDD：先写失败测试，再实现。
- Task 1（引擎协议变更）与 Task 2（workbench 迁移）之间存在一个跨仓库的瞬时不适配提交点，属计划内（同 P2 facade 模式）：Task 1 只跑引擎测试，workbench 全量在 Task 2 完成后恢复。

**现状关键事实（实现者无需再调研）：**
- 引擎 `geoviz_well_log/renderer/curve_track.py`：`_sorted_depths/_sorted_values` 为 `dict[str, list]`（构造于 `__init__` 第 48-57 行）；`_visible_data` 用 bisect（第 75-87 行）；`_downsample` 委托 `get_downsample_provider()`；`paint_header` 第 154-160 行每次重绘 `min(vals)/max(vals)` 全扫描；`paint_content` 第 181-237 行 path cache（精确浮点 key，交互不命中）+ 逐点 NaN 检查建 QPainterPath。
- 引擎 `geoviz_well_log/renderer/downsample.py`：`numpy_minmax_downsample(depths: list, values: list, pixel_height: int)` + `get/set_downsample_provider`。
- workbench `paleo_workbench/viz/render_accel.py`：`_cpp_minmax_provider(depths: list, values: list, pixel_height)` 转 float32 调 `well_log_api.minmax_downsample` 再 `.tolist()`。
- `well_log_api.minmax_downsample(depth: np.ndarray, values: np.ndarray, target_pixels: int)` 接收/返回 ndarray（C++ float32 或 NumPy 保底）。
- 调用方兼容已核查：`canvas.py::_extract_curve` 与 picking overlay 对 `_sorted_depths/_sorted_values` 只做 `np.asarray(...)`，ndarray 来源同样可用。
- 预览 `resources/preview_parsers/well_log_parsers.py:63-80`：用 `lasio.read` 读全文件只为前 100 行表格；`fast_las_parse_data` 已在第 10 行 import（死代码）。
- C++ `native/well_log_core/src/well_log_core.cpp:88-164`：`fast_las_parse_data` 逐行 `istringstream` + `stod`、`vector<vector<double>>` 中间结构、全程持 GIL。

---

### Task 1: 引擎 downsample 协议升级 + CurveTrack ndarray 化

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/downsample.py`（全文替换）
- Modify: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/curve_track.py`（`__init__` 排序缓存、`_visible_data`、`paint_header` 范围字符串、`paint_content` 缓存与路径构建）
- Modify: `geo-viz-engine/packages/geoviz_well_log/tests/test_downsample.py`（协议迁移，P1 新建文件，允许修改）
- Test: `geo-viz-engine/packages/geoviz_well_log/tests/test_curve_track_ndarray.py`

**Interfaces:**
- Consumes: 无。
- Produces（Task 2 依赖）:
  - 新 provider 协议：`Provider = Callable[[np.ndarray, np.ndarray, int], tuple[np.ndarray, np.ndarray]]`，参数为 (depths, values, pixel_height)，float64 进、float64 出。
  - `downsample.numpy_minmax_downsample(depths: np.ndarray, values: np.ndarray, pixel_height: int) -> tuple[np.ndarray, np.ndarray]`（引擎默认实现，语义与旧 list 版逐点一致）。
  - `CurveTrack._sorted_depths/_sorted_values` 变为 `dict[str, np.ndarray]`（float64）。

- [ ] **Step 1: 写失败测试（协议 + 等价性）**

创建 `geo-viz-engine/packages/geoviz_well_log/tests/test_curve_track_ndarray.py`：

```python
"""CurveTrack ndarray storage + rendering-equivalence tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _old_list_downsample(depths, values, pixel_height):
    """P1 list-based reference implementation (kept for parity checks)."""
    if len(depths) <= pixel_height * 2:
        return list(depths), list(values)
    arr_v = np.array(values)
    step = max(1, len(arr_v) // pixel_height)
    result_d, result_v = [], []
    for i in range(0, len(arr_v), step):
        chunk = arr_v[i:i + step]
        max_idx = i + int(np.argmax(chunk))
        min_idx = i + int(np.argmin(chunk))
        if max_idx <= min_idx:
            result_d.append(depths[max_idx]); result_v.append(values[max_idx])
            result_d.append(depths[min_idx]); result_v.append(values[min_idx])
        else:
            result_d.append(depths[min_idx]); result_v.append(values[min_idx])
            result_d.append(depths[max_idx]); result_v.append(values[max_idx])
    return result_d, result_v


def _make_track(n: int = 5000, with_nan: bool = False):
    from geoviz_well_log.models import CurveData
    from geoviz_well_log.renderer.curve_track import CurveTrack

    rng = np.random.default_rng(7)
    values = (rng.random(n) * 100).tolist()
    if with_nan:
        values[100] = float("nan")
        values[2500] = float("nan")
    curve = CurveData(
        name="GR", unit="API",
        depth=[float(i) * 0.125 for i in range(n)],
        values=values,
        display_range=(0.0, 100.0),
    )
    return CurveTrack([curve]), values


def test_sorted_storage_is_ndarray(qapp):
    track, _ = _make_track()
    assert isinstance(track._sorted_depths["GR"], np.ndarray)
    assert isinstance(track._sorted_values["GR"], np.ndarray)


def test_numpy_downsample_parity_with_list_reference():
    from geoviz_well_log.renderer.downsample import numpy_minmax_downsample

    n = 5000
    rng = np.random.default_rng(42)
    depths = np.arange(n, dtype=np.float64) * 0.125
    values = rng.random(n) * 100
    ref_d, ref_v = _old_list_downsample(depths.tolist(), values.tolist(), 200)
    out_d, out_v = numpy_minmax_downsample(depths, values, 200)
    assert isinstance(out_d, np.ndarray) and isinstance(out_v, np.ndarray)
    np.testing.assert_array_equal(out_d, np.array(ref_d))
    np.testing.assert_array_equal(out_v, np.array(ref_v))


def test_numpy_downsample_passthrough_when_small():
    from geoviz_well_log.renderer.downsample import numpy_minmax_downsample

    depths = np.array([1.0, 2.0, 3.0])
    values = np.array([4.0, 5.0, 6.0])
    out_d, out_v = numpy_minmax_downsample(depths, values, 100)
    np.testing.assert_array_equal(out_d, depths)
    np.testing.assert_array_equal(out_v, values)


def test_visible_data_matches_bisect_reference(qapp):
    track, _ = _make_track()
    track.depth_top = 100.0
    track.depth_bottom = 500.0
    depths, values = track._visible_data(track._curves[0])
    # Reference: old bisect logic on the same sorted arrays
    sd = track._sorted_depths["GR"]
    sv = track._sorted_values["GR"]
    import bisect

    margin = (500.0 - 100.0) * 0.05
    top, bottom = 100.0 - margin, 500.0 + margin
    start = max(0, bisect.bisect_left(sd.tolist(), top) - 1)
    end = min(len(sd), bisect.bisect_right(sd.tolist(), bottom) + 1)
    np.testing.assert_array_equal(depths, sd[start:end])
    np.testing.assert_array_equal(values, sv[start:end])


def test_header_range_uses_nan_safe_precomputed(qapp):
    track, _ = _make_track(with_nan=True)
    curve = track._curves[0]
    range_str = track._range_str_for(curve)
    vals = np.asarray(track._sorted_values["GR"], dtype=float)
    expected = f"{np.nanmin(vals):.1f}~{np.nanmax(vals):.1f} API".strip()
    assert range_str == expected
    assert "nan" not in range_str.lower()


def test_path_cache_hits_on_repeated_key(qapp):
    track, _ = _make_track()
    track.depth_top = 0.0
    track.depth_bottom = 625.0
    from PySide6.QtCore import QRectF

    rect = QRectF(0, 0, 150, 800)
    d1 = track._cached_downsampled(track._curves[0], rect)
    d2 = track._cached_downsampled(track._curves[0], rect)
    assert d1 is d2  # same cached arrays object on hit
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests/test_curve_track_ndarray.py -v
```

预期：FAIL（`AssertionError`：`_sorted_depths` 是 list；`numpy_minmax_downsample` 返回 list；`_range_str_for` / `_cached_downsampled` 不存在）。

- [ ] **Step 3: 实现 downsample.py 协议升级**

将 `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/downsample.py` 全文替换为：

```python
"""Injectable Min-Max LOD downsampling for curve rendering.

Provider protocol (ndarray in, ndarray out):
``provider(depths: np.ndarray, values: np.ndarray, pixel_height: int)``
-> ``(np.ndarray, np.ndarray)``.

Default provider is the engine's NumPy implementation. Host applications
(e.g. paleo_workbench) may inject a C++-accelerated provider at startup via
``set_downsample_provider`` — the engine itself has no such dependency.
"""
from __future__ import annotations

from typing import Callable

import numpy as np

DownsampleFn = Callable[
    [np.ndarray, np.ndarray, int], tuple[np.ndarray, np.ndarray]
]


def numpy_minmax_downsample(
    depths: np.ndarray, values: np.ndarray, pixel_height: int
) -> tuple[np.ndarray, np.ndarray]:
    """Min-max 2-points-per-bin downsampling (engine default, ndarray-native).

    Semantics are identical to the legacy list-based implementation:
    bins of ``step = len // pixel_height`` (last bin may be partial), each
    bin emits its min and max in index (depth) order.
    """
    depths = np.asarray(depths, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    n = len(depths)
    if n <= pixel_height * 2:
        return depths, values
    step = max(1, n // pixel_height)
    out_d: list[float] = []
    out_v: list[float] = []
    for i in range(0, n, step):
        chunk = values[i:i + step]
        max_idx = i + int(np.argmax(chunk))
        min_idx = i + int(np.argmin(chunk))
        lo, hi = (max_idx, min_idx) if max_idx < min_idx else (min_idx, max_idx)
        # Emit in index (depth) order to avoid zigzag artifacts
        out_d.append(depths[lo])
        out_v.append(values[lo])
        out_d.append(depths[hi])
        out_v.append(values[hi])
    return np.asarray(out_d, dtype=np.float64), np.asarray(out_v, dtype=np.float64)


_provider: DownsampleFn = numpy_minmax_downsample


def get_downsample_provider() -> DownsampleFn:
    return _provider


def set_downsample_provider(fn: DownsampleFn | None) -> None:
    """Install a custom downsample provider; ``None`` restores the default."""
    global _provider
    _provider = fn if fn is not None else numpy_minmax_downsample
```

注意：旧实现 `max_idx <= min_idx` 时先发 max——`lo/hi` 排序写法与之逐点等价（含 min==max 同点重复emit），parity 测试已锁定。

- [ ] **Step 4: CurveTrack ndarray 化**

对 `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/renderer/curve_track.py` 做以下修改：

**4a.** `__init__` 排序缓存（第 47-57 行附近）改为 ndarray，并预计算范围字符串：

```python
        self._curves = sanitized_curves
        self._log_scale = log_scale
        self._path_cache = {}
        self._downsampled_cache = {}
        # Store sorted ndarray copies — never mutate the original Pydantic models
        self._sorted_depths: dict[str, np.ndarray] = {}
        self._sorted_values: dict[str, np.ndarray] = {}
        self._range_strs: dict[str, str] = {}
        for c in self._curves:
            if c.depth != sorted(c.depth):
                pairs = sorted(zip(c.depth, c.values))
                self._sorted_depths[c.name] = np.asarray([p[0] for p in pairs], dtype=np.float64)
                self._sorted_values[c.name] = np.asarray([p[1] for p in pairs], dtype=np.float64)
            else:
                self._sorted_depths[c.name] = np.asarray(c.depth, dtype=np.float64)
                self._sorted_values[c.name] = np.asarray(c.values, dtype=np.float64)
            vals = self._sorted_values[c.name]
            if len(vals) and not np.all(np.isnan(vals)):
                vmin = float(np.nanmin(vals))
                vmax = float(np.nanmax(vals))
                self._range_strs[c.name] = f"{vmin:.1f}~{vmax:.1f} {c.unit}".strip()
            else:
                self._range_strs[c.name] = c.unit
```

**4b.** 新增范围字符串访问器（供 `paint_header` 与测试）：

```python
    def _range_str_for(self, curve: CurveData) -> str:
        return self._range_strs.get(curve.name, curve.unit)
```

`paint_header` 中（第 154-160 行）：

```python
            # Compute min/max from curve values
            vals = curve.values
            if vals:
                vmin = min(vals)
                vmax = max(vals)
                range_str = f"{vmin:.1f}~{vmax:.1f} {curve.unit}".strip()
            else:
                range_str = curve.unit
```

替换为：

```python
            range_str = self._range_str_for(curve)
```

**4c.** `_visible_data`（第 75-87 行）替换为 searchsorted 零拷贝视图：

```python
    def _visible_data(self, curve: CurveData) -> tuple[np.ndarray, np.ndarray]:
        depths = self._sorted_depths.get(curve.name)
        values = self._sorted_values.get(curve.name)
        if depths is None or values is None or len(depths) == 0:
            empty = np.empty(0, dtype=np.float64)
            return empty, empty
        margin = (self.depth_bottom - self.depth_top) * 0.05
        top = self.depth_top - margin
        bottom = self.depth_bottom + margin
        start = max(0, int(np.searchsorted(depths, top, side="left")) - 1)
        end = min(len(depths), int(np.searchsorted(depths, bottom, side="right")) + 1)
        return depths[start:end], values[start:end]
```

**4d.** 新增量化键抽稀缓存，并改写 `paint_content` 的缓存与路径段。新增方法：

```python
    def _cached_downsampled(self, curve: CurveData, rect: QRectF) -> tuple[np.ndarray, np.ndarray]:
        """Downsampled arrays cached on a quantized depth-window key."""
        pixel_height = max(1, int(rect.height()))
        span = max(1e-9, self.depth_bottom - self.depth_top)
        quantum = span / pixel_height
        key = (
            pixel_height,
            int(round(rect.width())),
            int(round(self.depth_top / quantum)),
            int(round(self.depth_bottom / quantum)),
        )
        cached = self._downsampled_cache.get(curve.name)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        depths, values = self._visible_data(curve)
        depths, values = self._downsample(depths, values, pixel_height)
        self._downsampled_cache[curve.name] = (key, depths, values)
        return depths, values
```

`paint_content` 中（第 180-241 行）将缓存块与路径构建替换为（移除旧 `_path_cache` 浮点 key 逻辑）：

```python
        pixel_height = max(1, int(rect.height()))

        for curve in self._curves:
            depths, values = self._cached_downsampled(curve, rect)
            if len(depths) < 2:
                continue

            # y coordinate calculation
            ys = rect.top() + (depths - self.depth_top) / (self.depth_bottom - self.depth_top) * rect.height()

            # x coordinate calculation based on display scale mode
            lo, hi = curve.display_range
            if self._log_scale:
                clipped_vals = np.clip(values, max(lo, 1e-10), None)
                log_lo = log10(max(lo, 1e-10))
                log_hi = log10(max(hi, 1e-10))
                if log_lo == log_hi:
                    xs = np.full_like(values, rect.left() + 0.5 * rect.width())
                else:
                    t_arr = (np.log10(clipped_vals) - log_lo) / (log_hi - log_lo)
                    xs = rect.left() + t_arr * rect.width()
            else:
                if hi == lo:
                    xs = np.full_like(values, rect.left() + 0.5 * rect.width())
                else:
                    t_arr = (values - lo) / (hi - lo)
                    xs = rect.left() + t_arr * rect.width()

            finite = np.isfinite(xs) & np.isfinite(ys)
            path = QPainterPath()
            first = True
            for x, y, ok in zip(xs, ys, finite):
                if not ok:
                    first = True
                    continue
                if first:
                    path.moveTo(float(x), float(y))
                    first = False
                else:
                    path.lineTo(float(x), float(y))

            painter.setPen(self._make_pen(curve))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
```

（`__init__` 中的 `self._path_cache = {}` 可一并删除；若其他代码引用 `self._path_cache` 则保留赋值但不再使用——以 grep 为准。）

- [ ] **Step 5: 迁移 test_downsample.py 到新协议**

将 `geo-viz-engine/packages/geoviz_well_log/tests/test_downsample.py` 全文替换为：

```python
"""Tests for the injectable curve downsample provider (ndarray protocol)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from geoviz_well_log.renderer.downsample import (
    get_downsample_provider,
    numpy_minmax_downsample,
    set_downsample_provider,
)


def _sample(n: int = 1000):
    depths = np.arange(n, dtype=np.float64)
    values = ((np.arange(n) * 37) % 101).astype(np.float64)
    return depths, values


def test_default_provider_is_numpy_impl():
    assert get_downsample_provider() is numpy_minmax_downsample


def test_numpy_downsample_preserves_extrema_and_order():
    depths, values = _sample()
    out_d, out_v = numpy_minmax_downsample(depths, values, 50)
    assert len(out_d) == len(out_v)
    assert len(out_d) <= 2 * 50 + 2
    assert out_v.max() == values.max()
    assert out_v.min() == values.min()
    assert np.all(np.diff(out_d) >= 0)


def test_numpy_downsample_passthrough_when_small():
    depths, values = _sample(40)
    out_d, out_v = numpy_minmax_downsample(depths, values, 50)
    np.testing.assert_array_equal(out_d, depths)
    np.testing.assert_array_equal(out_v, values)


def test_set_and_reset_provider():
    calls = []

    def fake(depths, values, pixel_height):
        calls.append(pixel_height)
        return depths[:2], values[:2]

    set_downsample_provider(fake)
    try:
        assert get_downsample_provider() is fake
        out_d, out_v = get_downsample_provider()(
            np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]), 10
        )
        np.testing.assert_array_equal(out_d, np.array([1.0, 2.0]))
        assert calls == [10]
    finally:
        set_downsample_provider(None)
    assert get_downsample_provider() is numpy_minmax_downsample


def test_curve_track_delegates_to_provider():
    """CurveTrack._downsample must route through the module provider."""
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
        seen.append((isinstance(depths, np.ndarray), pixel_height))
        return depths, values

    set_downsample_provider(spy)
    try:
        track._downsample(np.array([1.0, 2.0]), np.array([3.0, 4.0]), 100)
    finally:
        set_downsample_provider(None)
    assert seen == [(True, 100)]
```

- [ ] **Step 6: 运行测试确认通过 + 引擎回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests packages/geoviz_cross_well/tests -q
```

预期：全绿。

注意：此提交后 workbench 的 `render_accel.py` 旧 list provider 与新引擎不兼容（计划内瞬时状态），不要在此步跑 workbench 测试。

- [ ] **Step 7: 提交（geo-viz-engine 仓库）**

```bash
cd geo-viz-engine && git add packages/geoviz_well_log/geoviz_well_log/renderer/downsample.py packages/geoviz_well_log/geoviz_well_log/renderer/curve_track.py packages/geoviz_well_log/tests/test_downsample.py packages/geoviz_well_log/tests/test_curve_track_ndarray.py && git commit -m "perf(well-log): ndarray-native curve rendering with quantized downsample cache"
```

---

### Task 2: workbench provider 迁移 ndarray 协议

**Files:**
- Modify: `paleo_workbench/viz/render_accel.py`
- Modify: `tests/test_render_accel.py`（协议迁移，P1 新建文件，允许修改）

**Interfaces:**
- Consumes: Task 1 的 ndarray 协议；`well_log_api.minmax_downsample(depth: np.ndarray, values: np.ndarray, target_pixels: int) -> tuple[np.ndarray, np.ndarray]`。
- Produces: `_cpp_minmax_provider(depths: np.ndarray, values: np.ndarray, pixel_height: int) -> tuple[np.ndarray, np.ndarray]`（float32 转换在 C++ 边界完成，不再 list 往返）。

- [ ] **Step 1: 迁移测试到新协议**

将 `tests/test_render_accel.py` 全文替换为：

```python
"""Tests for C++ downsample injection into the geoviz engine (ndarray protocol)."""
from __future__ import annotations

import numpy as np

from geoviz_well_log.renderer.downsample import (
    get_downsample_provider,
    numpy_minmax_downsample,
    set_downsample_provider,
)

import paleo_workbench.viz.render_accel as render_accel
from paleo_workbench.viz.render_accel import install_geoviz_acceleration


def setup_function():
    set_downsample_provider(None)
    render_accel._installed_provider = None


def teardown_function():
    set_downsample_provider(None)
    render_accel._installed_provider = None


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
    depths = np.arange(n, dtype=np.float64) * 0.125
    rng = np.random.default_rng(42)
    values = rng.random(n) * 100
    out_d, out_v = provider(depths, values, 200)
    assert isinstance(out_d, np.ndarray) and isinstance(out_v, np.ndarray)
    assert len(out_d) == len(out_v)
    assert len(out_d) <= 2 * 200 + 4
    # Provider casts to float32 at the C++ boundary; extrema are selections
    # of the float32-cast inputs.
    values32 = values.astype(np.float32)
    assert out_v.max() == values32.max()
    assert out_v.min() == values32.min()
    assert np.all(np.diff(out_d) >= 0)


def test_injected_provider_passthrough_when_small():
    install_geoviz_acceleration()
    provider = get_downsample_provider()
    depths = np.array([1.0, 2.0])
    values = np.array([3.0, 4.0])
    out_d, out_v = provider(depths, values, 100)
    np.testing.assert_array_equal(out_d, depths)
    np.testing.assert_array_equal(out_v, values)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_render_accel.py -v
```

预期：FAIL（旧 `_cpp_minmax_provider` 对 ndarray 输入调 `len()` 后走 list 路径/返回 list，类型断言失败）。

- [ ] **Step 3: 迁移 render_accel.py**

将 `paleo_workbench/viz/render_accel.py` 中 `_cpp_minmax_provider` 替换为：

```python
def _cpp_minmax_provider(
    depths: np.ndarray, values: np.ndarray, pixel_height: int
) -> tuple[np.ndarray, np.ndarray]:
    if len(depths) <= pixel_height * 2:
        return depths, values
    d = np.asarray(depths, dtype=np.float32)
    v = np.asarray(values, dtype=np.float32)
    out_d, out_v = minmax_downsample(d, v, int(pixel_height))
    return np.asarray(out_d, dtype=np.float64), np.asarray(out_v, dtype=np.float64)
```

- [ ] **Step 4: 运行测试确认通过 + workbench 全量回归**

```bash
.venv/bin/python -m pytest tests/test_render_accel.py -v
```

预期：4 passed。

```bash
.venv/bin/python -m pytest tests -q
```

预期：全绿（基线 1153；已知 flake `test_project_lifecycle.py` 若仅全量中失败且单独跑通过，记录即可）。

- [ ] **Step 5: 提交（仓库根，含子模块 gitlink）**

```bash
git add paleo_workbench/viz/render_accel.py tests/test_render_accel.py geo-viz-engine && git commit -m "perf(viz): migrate injected downsample provider to ndarray protocol"
```

---

### Task 3: 预览解析器去 lasio

**Files:**
- Modify: `paleo_workbench/resources/preview_parsers/well_log_parsers.py:63-80`（data_rows 构建段）
- Test: `tests/test_well_log_preview_fast.py`

**Interfaces:**
- Consumes: `well_log_api.fast_las_parse_data(content, null_value)`（已 import 于该文件第 10 行）；同函数内已有的 `header = inspect_las_file(...)`（含 `curves`/`null_value`）。
- Produces: `PreviewResult.data_headers`/`data_rows` 行为不变（NaN 显示 "NaN"、数值格式 `f"{val:.4f}".rstrip('0').rstrip('.')`、上限 100 行），但不再使用 lasio。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_well_log_preview_fast.py`：

```python
"""LAS table preview must not use lasio (C++ fast channel instead)."""
from __future__ import annotations

import sys
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.preview_parsers.well_log_parsers import las_preview

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


class _Settings:
    table_max_rows = 100


def _resource(tmp_path: Path) -> ResourceItem:
    path = tmp_path / "well.las"
    path.write_text(SAMPLE_LAS, encoding="utf-8")
    return ResourceItem(name="well.las", path=str(path), type="well_log", format="las")


def test_preview_data_rows_without_lasio(tmp_path: Path, monkeypatch):
    # Forbid lasio entirely: preview must still produce the data table.
    monkeypatch.setitem(sys.modules, "lasio", None)
    result = las_preview(_resource(tmp_path), _Settings())
    assert result.data_headers == ("DEPT", "GR", "DT")
    assert len(result.data_rows) == 6
    assert result.data_rows[0] == ("2000", "45.2", "220")
    # NULL -> NaN display
    assert result.data_rows[1][2] == "NaN"
    assert result.data_rows[3][1] == "NaN"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_well_log_preview_fast.py -v
```

预期：FAIL（lasio 被禁后 `data_headers == ()` / `data_rows == ()`）。

- [ ] **Step 3: 实现替换**

将 `well_log_parsers.py` 第 61-80 行（`data_headers`/`data_rows` 构建段）替换为：

```python
    data_headers = ()
    data_rows = ()
    try:
        import numpy as np

        content = path.read_text(encoding="utf-8", errors="replace")
        _headers, arr = fast_las_parse_data(content, header.null_value)
        if arr.ndim == 2 and arr.shape[0] > 0:
            data_headers = tuple(c.mnemonic for c in curves[: arr.shape[1]])
            limit = min(arr.shape[0], 100)
            rows_list = []
            for i in range(limit):
                row_vals = []
                for val in arr[i]:
                    if np.isnan(val):
                        row_vals.append("NaN")
                    else:
                        row_vals.append(f"{val:.4f}".rstrip('0').rstrip('.'))
                rows_list.append(tuple(row_vals))
            data_rows = tuple(rows_list)
    except Exception:
        pass
```

注意 `arr.shape[1]` 与 `curves` 数量不一致时取 `curves[: arr.shape[1]]`（列数以数据为准，与旧 lasio 行为 `las.curves` 对齐到数据列一致）。`fast_las_parse_data` 第二参数：确认 wrapper 签名为 `(content, null_value=-999.0)`；`header.null_value` 来自 `inspect_las_file`。

- [ ] **Step 4: 运行测试确认通过 + 相关回归**

```bash
.venv/bin/python -m pytest tests/test_well_log_preview_fast.py tests/test_fallback_preview.py tests/test_geoviz_preview_provider.py -q
```

预期：全绿。

- [ ] **Step 5: 提交（仓库根）**

```bash
git add paleo_workbench/resources/preview_parsers/well_log_parsers.py tests/test_well_log_preview_fast.py && git commit -m "perf(preview): replace lasio full-file read with C++ fast channel for LAS table preview"
```

---

### Task 4: LAS C++ 解析器优化（GIL / 解析原语 / 双重解析）

**Files:**
- Modify: `native/well_log_core/src/well_log_core.cpp:88-164`（`fast_las_parse_data`）
- Modify: `paleo_workbench/viz/well_log_api.py`（wrapper 消除双重解析重试——若有）
- Test: `tests/test_well_log_cpp.py`、`tests/test_well_log_api.py`（既有 parity 测试，不得修改，必须保持全绿）
- Test: `tests/test_well_log_load_fast.py`（既有，保持全绿）

**Interfaces:**
- Consumes: 无。
- Produces: `fast_las_parse_data(content, null_value=-999.0)` 签名与返回**完全不变**（C++ 与 Python 保底数值等价由既有测试锁定）。

- [ ] **Step 1: 确认基线**

```bash
.venv/bin/python -m pytest tests/test_well_log_cpp.py tests/test_well_log_api.py tests/test_well_log_load_fast.py -q
```

预期：全绿（作为重构前的行为锁定）。记录 LAS 解析基线耗时供 Step 5 对比：

```bash
.venv/bin/python -c "
import time
from pathlib import Path
from paleo_workbench.viz.well_log_api import fast_las_parse_data, HAS_CPP_WELL_LOG
content = Path('data/井曲线/A1.Las').read_text(encoding='utf-8', errors='replace')
assert HAS_CPP_WELL_LOG
t0 = time.perf_counter()
for _ in range(20):
    fast_las_parse_data(content)
print(f'baseline cpp parse: {(time.perf_counter()-t0)/20*1000:.2f} ms/iter')
"
```

- [ ] **Step 2: 优化 C++ 实现**

重写 `well_log_core.cpp` 的 `fast_las_parse_data`（签名与 pybind 绑定不变）：

- 解析主循环（逐行扫描 + 数值解析写入 `std::vector<double>` flat 缓冲，记录行宽）放入 `py::gil_scoped_release` 块；`py::array`/`py::tuple` 构造在 GIL 持有时进行。
- 数值解析用 `std::from_chars`（`<charconv>`，double 支持需 GCC 11+/Clang 14+；先 `#if __cpp_lib_to_chars >= 201611L` 特性检测，不可用时回退 `strtod`）替换 `istringstream` + `stod`。
- `std::vector<std::vector<double>> rows` 改为 flat `std::vector<double>` + `std::vector<size_t> row_widths`（或直接两遍扫描：第一遍计行数/列数，第二遍直接写入输出数组），消除逐行堆分配。
- 保持既有语义逐点不变：`#` 注释跳过、`~A` 节头规则（空白分隔才算内联列名）、`<= -999.0 || == null_value || isnan` → NaN、非数值 token → NaN、短行补 NaN。

`strtod` 回退写法参考（每行）：

```cpp
const char* p = stripped.c_str();
const char* end = p + stripped.size();
while (p < end) {
    while (p < end && (*p == ' ' || *p == '\t')) ++p;
    if (p >= end) break;
    char* next = nullptr;
    double val = std::strtod(p, &next);
    if (next == p) {  // non-numeric token: skip token, emit NaN
        while (p < end && *p != ' ' && *p != '\t') ++p;
        row_buf.push_back(nan);
    } else {
        if (std::isnan(val) || val <= -999.0 || val == null_value) val = nan;
        row_buf.push_back(val);
        p = next;
    }
}
```

- [ ] **Step 3: wrapper 去双重解析**

读 `paleo_workbench/viz/well_log_api.py` 的 `fast_las_parse_data` wrapper：若存在 `try: well_log_core.fast_las_parse_data(content) except TypeError: well_log_core.fast_las_parse_data(content, null_value)` 形式的整文件二次解析，改为单次调用 `well_log_core.fast_las_parse_data(content, float(null_value))`（C++ 签名已有默认参数，直接双参数调用无需重试）。Python 保底路径不变。

- [ ] **Step 4: 重建扩展并运行 parity 测试**

```bash
.venv/bin/python -m pip install -e native/well_log_core --no-build-isolation -q
```

```bash
.venv/bin/python -m pytest tests/test_well_log_cpp.py tests/test_well_log_api.py tests/test_well_log_load_fast.py tests/test_viz_adapter.py -q
```

预期：全绿（parity 测试锁定 C++/Python 数值等价）。

- [ ] **Step 5: 记录提速数据 + 提交（仓库根）**

重跑 Step 1 的计时命令对比，把 before/after 写入提交信息或 progress.md（Task 5 统一记录亦可）。

```bash
git add native/well_log_core/src/well_log_core.cpp paleo_workbench/viz/well_log_api.py && git commit -m "perf(native): GIL release and from_chars/strtod fast paths in LAS parser"
```

---

### Task 5: 回归、性能基准与文档

**Files:**
- Modify: `task_plan.md`、`progress.md`

**Interfaces:**
- Consumes: Task 1-4 完成。
- Produces: 无代码产出。

- [ ] **Step 1: 双仓库全量回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests packages/geoviz_cross_well/tests -q
```

```bash
.venv/bin/python -m pytest tests -q
```

预期：全绿（flake 规则同前）。

- [ ] **Step 2: 记录性能基准（用 tests/perf 工具或简单计时脚本）**

记录并写入 `progress.md`：
- LAS 解析：Task 4 Step 1/5 的 before/after。
- 抽稀：C++ provider 与旧 list 路径的每曲线耗时对比（100k 点 → 2000px）。
- 表头：改造前后 8 井整幅重绘的 `paint_header` 占比（可用简单 timeit 脚本说明，不必新增持久测试文件）。

- [ ] **Step 3: 更新 task_plan.md 与 progress.md**

`task_plan.md` Phase 13 后追加：

```markdown
### Phase 14: 测井渲染通道性能加固（P4 阶段 A）

- [x] CurveTrack ndarray 化 + downsample 钩子协议升级（ndarray 进 ndarray 出）+ render_accel 迁移
- [x] 表头 min/max 预计算（修复 NaN `nan~nan` bug）+ path cache 量化键修复
- [x] LAS 表格预览去 lasio（C++ fast channel）
- [x] LAS C++ 解析器 GIL 释放 + from_chars/strtod + 去双重解析
- **Status:** complete
```

`progress.md` 追加对应 session 记录（含性能数字）。

- [ ] **Step 4: 提交（仓库根）**

```bash
git add task_plan.md progress.md && git commit -m "docs(plan): record phase 14 well-log rendering perf hardening"
```

---

## Self-Review 记录

- **Spec 覆盖**：阶段 A 五项（CurveTrack ndarray 化 → Task 1+2；表头缓存+NaN → Task 1 Step 4a/4b；path cache → Task 1 Step 4d；预览去 lasio → Task 3；LAS C++ 优化 → Task 4）全部有任务。阶段 B/C 按计划后续单独制定。
- **占位符扫描**：无 TBD/TODO；C++ 重写给出语义约束 + strtod 参考实现（from_chars 需特性检测，具体代码留给实现者但有明确验收：parity 测试全绿 + 语义清单逐点不变）。
- **类型一致性**：ndarray 协议签名在 Task 1 定义、Task 2 消费一致；`_range_str_for`/`_cached_downsampled` 测试与实现一致；`fast_las_parse_data(content, null_value)` 与 P1 终审修复后的签名一致。
- **等价性保障**：抽稀 parity（旧 list 参考实现内嵌测试）、visible_data bisect 参考对比、LAS 既有 parity 测试不得修改，三层锁定。
