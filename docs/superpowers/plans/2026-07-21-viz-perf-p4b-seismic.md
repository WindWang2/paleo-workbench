# P4 阶段 B 地震切片交互性能实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除地震切片交互的 GUI 线程磁盘读卡顿（每跳 10–100ms+），修复 `_on_jump` 三面板不一致 bug，3D 切片平面改为按轴更新，预览控件防抖与缓存缩放。

**Architecture:** geo-viz 新增长驻 `SliceReadWorker`（QThread，自有 segyio 句柄，最新优先队列 + 邻域预取），`SeismicView` 缓存未命中时改为异步请求-回投；`_pending_slice` 从单槽改为按轴字典（修复 `_on_jump` 覆盖）；`renderer_3d` 抽出按轴平面更新；workbench 预览控件加防抖与 NumPy 色表。

**Tech Stack:** PySide6/Qt（QThread、offscreen + pytest-qt）、segyio、NumPy、pytest。

**Spec:** `docs/superpowers/specs/2026-07-21-viz-perf-hardening-design.md`（阶段 B）

## Global Constraints

- segyio 文件句柄**不可跨线程共享**：worker 必须在线程内自建/自用 `SeismicLoader`（克隆 `SegyLoadWorker` 的 own-loader 模式）。
- 引擎所有改动默认行为不变（demo 模式、缓存命中路径、既有 API 签名）。
- 现有测试不得修改（只能新增）。
- 两个独立 git 仓库：引擎改动在 `geo-viz-engine/` 提交，workbench 改动在仓库根提交（含子模块 gitlink 联动）。
- 所有命令使用项目 venv：仓库根 `.venv/bin/python`；geo-viz-engine 内 `../.venv/bin/python`。
- 遵循 TDD：先写失败测试，再实现。

**勘察确认的修正（覆盖 spec 与此前评审的过时假设）：**
- 切片缓存 `RamSliceCache`（`packages/geoviz_seismic/geoviz_seismic/cache.py`）**已是** 512MB 字节上限 + 计数双限 LRU 且 `threading.RLock` 线程安全——spec 的"字节上限缓存"项已满足，本计划只做预取联动，不改缓存。
- `read_timeslice` 的逐 inline 回退循环：切片读取移入 worker 后冻结已消除（worker 时间不影响 UI），**算法本身不再改动**（segyio `depth_slice` 主路径同为全道扫描，收益小风险高）——这是与 spec 措辞的计划内偏差，目标（消除 UI 冻结）由 worker 达成。
- `preloader.py` 仅为 58 行的 DragTracker/generation-token 辅助类，未接线，本计划的 worker 不复用它（避免过度设计）。
- `_update_slice_planes` 实际位于 `renderer_3d.py:1434-1460`；`_apply_pending_slice` 位于 `seismic_view.py:939-998`；`_on_jump` 位于 `seismic_view.py:1321-1341`。
- 引擎地震测试在 `geo-viz-engine/tests/`（无包内 tests 目录）；worker 单测模式：`worker.run()` 同步调用 + monkeypatch `workers.SeismicLoader`；view 级测试：`QObject` 版 FakeWorker（见 `tests/test_seismic_workers.py`）；SEGY 数据 fixture：`small_segy_path`（`tests/conftest.py:47-75`）。
- `tests/test_seismic_view.py` 对 `pyvistaqt` 不可用的环境会 skip（`_pyvista_qt_available` 探测）——view 级新测试沿用同一 skip 守卫。

---

### Task 1: SliceReadWorker（引擎）

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/workers.py`（末尾追加）
- Test: `geo-viz-engine/tests/test_slice_read_worker.py`

**Interfaces:**
- Consumes: `SeismicLoader`（同模块已 import）、`_WorkerCancellationToken` 模式参考。
- Produces（Task 2 依赖）:
  - `workers.SliceReadWorker(QThread)`：
    - 信号 `slice_ready = Signal(str, int, object, int)` — (slice_type, actual_pos, ndarray, generation)，用户请求结果。
    - 信号 `prefetch_ready = Signal(str, int, object, int)` — 邻域预取结果。
    - `set_volume(path: str, generation: int) -> None` — 切换数据卷（下次循环生效，丢弃队列）。
    - `request(slice_type: str, actual_pos: int, generation: int) -> None` — 最新优先（同 slice_type 的旧请求被替换）。
    - `stop() -> None` — 置停并唤醒，`wait()` 结束线程。
    - 预取：每次成功读取后自动读同 slice_type 的 ±1、±2 邻位（界内且不在队列/最近结果中），发 `prefetch_ready`。
  - slice_type ∈ `{"inline", "crossline", "time"}`，读取分别走 `read_inline/read_crossline/read_timeslice`。

- [ ] **Step 1: 写失败测试**

创建 `geo-viz-engine/tests/test_slice_read_worker.py`：

```python
"""SliceReadWorker: latest-wins queue, own loader, prefetch, generation guard."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_worker_reads_and_prefetches(qapp, small_segy_path, qtbot):
    from geoviz_seismic.workers import SliceReadWorker
    from geoviz_seismic.loader import SeismicLoader

    loader = SeismicLoader(str(small_segy_path))
    meta = loader.inspect()
    mid_il = meta.iline_start + (meta.n_inlines // 2) * meta.iline_step
    loader.close()

    worker = SliceReadWorker()
    results = []
    prefetches = []
    worker.slice_ready.connect(lambda *a: results.append(a))
    worker.prefetch_ready.connect(lambda *a: prefetches.append(a))
    worker.start()
    try:
        worker.set_volume(str(small_segy_path), 1)
        worker.request("inline", mid_il, 1)
        qtbot.waitUntil(lambda: len(results) == 1, timeout=10000)
        qtbot.waitUntil(lambda: len(prefetches) >= 2, timeout=10000)
    finally:
        worker.stop()

    stype, pos, data, gen = results[0]
    assert stype == "inline"
    assert pos == mid_il
    assert gen == 1
    assert isinstance(data, np.ndarray)
    assert data.shape == (meta.n_crosslines, meta.n_samples)
    # Prefetch positions are neighbours of mid_il within bounds
    pref_positions = {p[1] for p in prefetches}
    assert mid_il not in pref_positions
    assert all(abs(p - mid_il) <= 2 * meta.iline_step for p in pref_positions)


def test_worker_latest_wins(qapp, small_segy_path, qtbot):
    from geoviz_seismic.workers import SliceReadWorker
    from geoviz_seismic.loader import SeismicLoader

    loader = SeismicLoader(str(small_segy_path))
    meta = loader.inspect()
    il0 = meta.iline_start
    il1 = il0 + meta.iline_step
    il2 = il1 + meta.iline_step
    loader.close()

    worker = SliceReadWorker()
    results = []
    worker.slice_ready.connect(lambda *a: results.append(a))
    # Queue requests BEFORE starting the thread: older same-type ones are dropped
    worker.set_volume(str(small_segy_path), 1)
    worker.request("inline", il0, 1)
    worker.request("inline", il1, 1)
    worker.request("inline", il2, 1)
    worker.start()
    try:
        qtbot.waitUntil(lambda: len(results) >= 1, timeout=10000)
    finally:
        worker.stop()
    # Only the latest inline request survives
    assert [r[1] for r in results] == [il2]


def test_worker_stale_generation_dropped(qapp, small_segy_path, qtbot):
    from geoviz_seismic.workers import SliceReadWorker
    from geoviz_seismic.loader import SeismicLoader

    loader = SeismicLoader(str(small_segy_path))
    meta = loader.inspect()
    mid_il = meta.iline_start + (meta.n_inlines // 2) * meta.iline_step
    loader.close()

    worker = SliceReadWorker()
    results = []
    worker.slice_ready.connect(lambda *a: results.append(a))
    worker.set_volume(str(small_segy_path), 5)
    worker.request("inline", mid_il, 4)  # stale generation vs volume's 5
    worker.start()
    try:
        qtbot.wait(300)
    finally:
        worker.stop()
    assert results == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest tests/test_slice_read_worker.py -v
```

预期：FAIL（`ImportError: cannot import name 'SliceReadWorker'`）。

- [ ] **Step 3: 实现 SliceReadWorker**

在 `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/workers.py` 末尾追加：

```python
class SliceReadWorker(QThread):
    """Long-lived background slice reader with a latest-wins queue and prefetch.

    Owns its own SeismicLoader inside the worker thread (segyio handles are
    not thread-safe). GUI thread submits requests; results come back via
    signals. Prefetch results use a separate signal so the view can cache
    them without refreshing panels.
    """

    slice_ready = Signal(str, int, object, int)    # type, actual_pos, ndarray, generation
    prefetch_ready = Signal(str, int, object, int)  # type, actual_pos, ndarray, generation

    _PREFETCH_OFFSETS = (1, -1, 2, -2)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._requests: dict[str, tuple[int, int]] = {}  # slice_type -> (actual_pos, generation)
        self._volume_path: str | None = None
        self._volume_generation = 0
        self._volume_dirty = False
        self._stop = False

    # --- GUI-thread API ---

    def set_volume(self, path: str, generation: int) -> None:
        with QMutexLocker(self._mutex):
            self._volume_path = path
            self._volume_generation = int(generation)
            self._volume_dirty = True
            self._requests.clear()
        self._cond.wakeAll()

    def request(self, slice_type: str, actual_pos: int, generation: int) -> None:
        with QMutexLocker(self._mutex):
            # Latest wins: replace any queued request of the same slice type
            self._requests[slice_type] = (int(actual_pos), int(generation))
        self._cond.wakeAll()

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stop = True
        self._cond.wakeAll()
        self.wait(5000)

    # --- worker thread ---

    def _take_next(self) -> tuple[str, int, int] | None:
        with QMutexLocker(self._mutex):
            if not self._requests:
                return None
            slice_type = next(iter(self._requests))
            pos, generation = self._requests.pop(slice_type)
            return slice_type, pos, generation

    def _current_volume(self) -> tuple[str | None, int, bool]:
        with QMutexLocker(self._mutex):
            dirty = self._volume_dirty
            self._volume_dirty = False
            return self._volume_path, self._volume_generation, dirty

    def run(self):
        from .loader import SeismicLoader

        loader = None
        loader_path = None
        try:
            while True:
                with QMutexLocker(self._mutex):
                    if self._stop:
                        return
                    if not self._requests and not self._volume_dirty:
                        self._cond.wait(self._mutex)
                        if self._stop:
                            return
                path, generation, dirty = self._current_volume()
                if dirty:
                    if loader is not None:
                        loader.close()
                        loader = None
                    loader_path = None
                if path is None:
                    continue
                if loader is None:
                    loader = SeismicLoader(path)
                    loader_path = path
                item = self._take_next()
                if item is None:
                    continue
                slice_type, pos, gen = item
                if gen != generation:
                    continue  # stale request from a previous volume
                try:
                    data, meta, step = self._read(loader, slice_type, pos)
                except Exception:
                    continue
                self.slice_ready.emit(slice_type, pos, data, gen)
                self._prefetch(loader, meta, slice_type, pos, step, gen)
        finally:
            if loader is not None:
                loader.close()

    @staticmethod
    def _read(loader, slice_type: str, pos: int):
        meta = loader.inspect()
        if slice_type == "inline":
            return loader.read_inline(pos), meta, meta.iline_step
        if slice_type == "crossline":
            return loader.read_crossline(pos), meta, meta.xline_step
        return loader.read_timeslice(pos), meta, 1

    def _prefetch(self, loader, meta, slice_type: str, pos: int, step: int, gen: int) -> None:
        bounds = {
            "inline": (meta.iline_start, meta.iline_start + (meta.n_inlines - 1) * meta.iline_step),
            "crossline": (meta.xline_start, meta.xline_start + (meta.n_crosslines - 1) * meta.xline_step),
            "time": (0, meta.n_samples - 1),
        }
        lo, hi = bounds[slice_type]
        for off in self._PREFETCH_OFFSETS:
            if self.isInterruptionRequested():
                return
            neighbor = pos + off * step
            if not (lo <= neighbor <= hi):
                continue
            with QMutexLocker(self._mutex):
                if slice_type in self._requests:
                    return  # user request pending: prefetch later
            try:
                data, _, _ = self._read(loader, slice_type, neighbor)
            except Exception:
                continue
            self.prefetch_ready.emit(slice_type, neighbor, data, gen)
```

`workers.py` 顶部 import 区需补充 `from PySide6.QtCore import QMutex, QMutexLocker, QWaitCondition`（保留既有 QThread/Signal import）。

- [ ] **Step 4: 运行测试确认通过**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest tests/test_slice_read_worker.py tests/test_seismic_workers.py -q
```

预期：全绿。

- [ ] **Step 5: 提交（geo-viz-engine 仓库）**

```bash
cd geo-viz-engine && git add packages/geoviz_seismic/geoviz_seismic/workers.py tests/test_slice_read_worker.py && git commit -m "feat(seismic): long-lived SliceReadWorker with latest-wins queue and neighbor prefetch"
```

---

### Task 2: renderer_3d 按轴平面更新

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/renderer_3d.py`（`_create_slice_planes`、`_update_slice_planes`）
- Test: `geo-viz-engine/tests/test_renderer_3d_per_axis.py`

**Interfaces:**
- Consumes: 无。
- Produces（Task 3 依赖）:
  - `SeismicRenderer3D._update_slice_planes_for(axes: set[str] | None = None)` — `None` 或全集合 = 全量重建（现状）；否则只重建指定轴（`"inline"`/`"crossline"`/`"time"`，任意切片 `"arbitrary"` 只在全量或显式包含时重建）。
  - 既有 `_update_slice_planes()` 保留为 `_update_slice_planes_for(None)` 的兼容别名。

- [ ] **Step 1: 写失败测试**

创建 `geo-viz-engine/tests/test_renderer_3d_per_axis.py`：

```python
"""Per-axis slice-plane update tests for SeismicRenderer3D."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pyvista = pytest.importorskip("pyvista")
pytest.importorskip("pyvistaqt")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_renderer(qtbot):
    from geoviz_seismic.renderer_3d import SeismicRenderer3D

    r = SeismicRenderer3D()
    qtbot.addWidget(r)
    vol = np.random.default_rng(3).random((8, 9, 10)).astype(np.float32)
    r.load_volume(vol) if hasattr(r, "load_volume") else None
    if not getattr(r, "_loaded", False):
        # Fall back: set minimal state for plane creation
        r._volume_data_cpu = vol
        r._loaded = True
    return r


def test_update_slice_planes_for_only_replaces_changed_axis(qtbot, qapp):
    r = _make_renderer(qtbot)
    if not getattr(r, "_loaded", False):
        pytest.skip("renderer could not initialize in this environment")
    r._update_slice_planes()
    il_before = r._img_il
    xl_before = r._img_xl
    t_before = r._img_t

    r._t_pos = min(getattr(r, "_t_pos", 0) + 1, 9)
    r._update_slice_planes_for({"time"})

    assert r._img_il is il_before
    assert r._img_xl is xl_before
    assert r._img_t is not t_before


def test_update_slice_planes_alias_matches_full_rebuild(qtbot, qapp):
    r = _make_renderer(qtbot)
    if not getattr(r, "_loaded", False):
        pytest.skip("renderer could not initialize in this environment")
    r._update_slice_planes()
    il_before = r._img_il
    r._update_slice_planes_for(None)
    assert r._img_il is not il_before
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest tests/test_renderer_3d_per_axis.py -v
```

预期：FAIL（`_update_slice_planes_for` 不存在）。

- [ ] **Step 3: 实现按轴更新**

对 `renderer_3d.py`：

**3a.** `_create_slice_planes`（第 1376-1432 行）按轴拆出单轴构建助手：把每个轴的（extract → colormap → GLImageItem → border line）代码块提取为 `_create_slice_plane(self, axis: str)`，返回/赋值 `self._img_<suffix>` 与 `self._line_<suffix>`（suffix ∈ `il/xl/t`）；`_create_slice_planes` 改为依次调用三个轴助手 + 原有的 arbitrary/curtain 逻辑（保持全量行为不变）。

**3b.** `_update_slice_planes`（第 1434-1460 行）替换为：

```python
    _PLANE_ATTRS = {
        "inline": ("_img_il", "_line_il"),
        "crossline": ("_img_xl", "_line_xl"),
        "time": ("_img_t", "_line_t"),
    }

    def _update_slice_planes(self):
        """Full rebuild (backward compatible)."""
        self._update_slice_planes_for(None)

    def _update_slice_planes_for(self, axes: set[str] | None = None):
        """Rebuild only the planes for `axes` (None = full rebuild)."""
        if axes is None or axes >= {"inline", "crossline", "time"}:
            axes = None  # fall through to full path
        if axes is None:
            # Original full-rebuild body (unchanged):
            items_to_clean = (
                getattr(self, "_img_il", None), getattr(self, "_img_xl", None), getattr(self, "_img_t", None), getattr(self, "_img_arb", None),
                getattr(self, "_line_il", None), getattr(self, "_line_xl", None), getattr(self, "_line_t", None), getattr(self, "_line_arb", None)
            )
            for v in items_to_clean:
                if v is not None:
                    try:
                        self._view.removeItem(v)
                    except Exception:
                        pass

            self._img_il = self._img_xl = self._img_t = self._img_arb = None
            self._line_il = self._line_xl = self._line_t = self._line_arb = None

            for item in getattr(self, '_arb_curtain_items', []):
                try:
                    self._view.removeItem(item)
                except Exception:
                    pass
            self._arb_curtain_items = []

            self._create_slice_planes()
            self._view.update()
            return

        for axis in axes:
            attrs = self._PLANE_ATTRS.get(axis)
            if attrs is None:
                continue
            for attr in attrs:
                item = getattr(self, attr, None)
                if item is not None:
                    try:
                        self._view.removeItem(item)
                    except Exception:
                        pass
                    setattr(self, attr, None)
            self._create_slice_plane(axis)
        self._view.update()
```

（全量分支就是原方法体原样内联，保证 `_update_slice_planes()` 与现状逐字节等价。）

- [ ] **Step 4: 运行测试确认通过 + 引擎回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest tests/test_renderer_3d_per_axis.py tests/test_renderer_3d.py tests/test_seismic_view_async.py -q
```

预期：全绿（pyvista 不可用时 skip）。

- [ ] **Step 5: 提交（geo-viz-engine 仓库）**

```bash
cd geo-viz-engine && git add packages/geoviz_seismic/geoviz_seismic/renderer_3d.py tests/test_renderer_3d_per_axis.py && git commit -m "perf(seismic): per-axis 3D slice plane updates"
```

---

### Task 3: SeismicView 异步接线 + `_on_jump` 修复

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/seismic_view.py`（`_pending_slice` 结构、`_on_slice_changed`、`_apply_pending_slice`、worker 生命周期、`_on_segy_ready`、`cancel_pending_segy_load`、`cleanup`）
- Test: `geo-viz-engine/tests/test_seismic_view_async.py`

**Interfaces:**
- Consumes: Task 1 的 `SliceReadWorker`（`set_volume/request/stop` + `slice_ready/prefetch_ready` 信号）；Task 2 的 `_update_slice_planes_for(axes)`。
- Produces:
  - `_pending_slice: dict[str, int]`（按轴），`_apply_pending_slice` 处理全部条目。
  - `_on_jump` 后三个 2D 面板一致刷新。
  - 缓存未命中不再阻塞 GUI：发 worker 请求，结果回投后 `_update_profile_panel` + 写缓存。

- [ ] **Step 1: 写失败测试**

创建 `geo-viz-engine/tests/test_seismic_view_async.py`（沿用 `test_seismic_view.py` 的 pyvista skip 守卫模式）：

```python
"""SeismicView async slice-read wiring and _on_jump consistency tests."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

pyvista = pytest.importorskip("pyvista")
pytest.importorskip("pyvistaqt")

from geoviz_seismic.seismic_view import SeismicView


class _FakeWorker(QObject):
    slice_ready = Signal(str, int, object, int)
    prefetch_ready = Signal(str, int, object, int)

    def __init__(self):
        super().__init__()
        self.requests = []
        self.volumes = []
        self.stopped = False

    def set_volume(self, path, generation):
        self.volumes.append((path, generation))

    def request(self, slice_type, actual_pos, generation):
        self.requests.append((slice_type, actual_pos, generation))

    def stop(self):
        self.stopped = True


def _make_view(qtbot, monkeypatch) -> tuple[SeismicView, _FakeWorker]:
    import geoviz_seismic.seismic_view as view_module

    fake = _FakeWorker()
    monkeypatch.setattr(view_module, "SliceReadWorker", lambda *a, **k: fake)
    view = SeismicView(auto_load=False)
    qtbot.addWidget(view)
    return view, fake


def test_pending_slice_is_per_axis_dict(qtbot, monkeypatch):
    view, _ = _make_view(qtbot, monkeypatch)
    assert isinstance(view._pending_slice, dict)


def test_jump_refreshes_all_three_panels(qtbot, monkeypatch):
    view, _ = _make_view(qtbot, monkeypatch)
    # Simulate loaded demo volume
    vol = np.random.default_rng(1).random((10, 12, 14)).astype(np.float32)
    view._renderer_3d._volume_data_cpu = vol
    view._renderer_3d._loaded = True
    applied = []
    monkeypatch.setattr(
        view, "_update_profile_panel",
        lambda stype, pos, data: applied.append((stype, pos)),
    )
    view._on_jump(3, 5, 7)
    view._slice_timer.stop()
    view._apply_pending_slice()
    assert set(stype for stype, _ in applied) == {"inline", "crossline", "time"}


def test_cache_miss_requests_worker_instead_of_blocking(qtbot, monkeypatch):
    view, fake = _make_view(qtbot, monkeypatch)
    view._meta = type("M", (), {
        "iline_start": 100, "iline_step": 2,
        "xline_start": 200, "xline_step": 1,
    })()
    view._ds_factor = (1, 1, 1)
    view._loader = object()  # not None -> loader path
    view._segy_generation = 7
    view._pending_slice = {"inline": 4}
    view._apply_pending_slice()
    assert fake.requests == [("inline", 100 + 4 * 2, 7)]


def test_slice_ready_updates_panel_and_cache(qtbot, monkeypatch):
    view, fake = _make_view(qtbot, monkeypatch)
    view._meta = type("M", (), {
        "iline_start": 100, "iline_step": 2,
        "xline_start": 200, "xline_step": 1,
    })()
    view._ds_factor = (1, 1, 1)
    view._loader = object()
    view._segy_generation = 7
    applied = []
    monkeypatch.setattr(
        view, "_update_profile_panel",
        lambda stype, pos, data: applied.append((stype, pos)),
    )
    data = np.ones((5, 6), dtype=np.float32)
    view._on_slice_ready("inline", 108, data, 7)
    assert applied == [("inline", 108)]
    assert view._cache.get(("inline", 108)) is data


def test_stale_generation_slice_ignored(qtbot, monkeypatch):
    view, fake = _make_view(qtbot, monkeypatch)
    view._segy_generation = 8
    applied = []
    monkeypatch.setattr(
        view, "_update_profile_panel",
        lambda stype, pos, data: applied.append((stype, pos)),
    )
    view._on_slice_ready("inline", 108, np.ones((2, 2), dtype=np.float32), 7)
    assert applied == []


def test_prefetch_only_fills_cache(qtbot, monkeypatch):
    view, _ = _make_view(qtbot, monkeypatch)
    view._segy_generation = 3
    applied = []
    monkeypatch.setattr(
        view, "_update_profile_panel",
        lambda stype, pos, data: applied.append((stype, pos)),
    )
    data = np.ones((4, 4), dtype=np.float32)
    view._on_prefetch_ready("time", 12, data, 3)
    assert applied == []
    assert view._cache.get(("time", 12)) is data
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest tests/test_seismic_view_async.py -v
```

预期：FAIL（`_pending_slice` 不是 dict；`_on_slice_ready`/`_on_prefetch_ready` 不存在）。

- [ ] **Step 3: 实现接线**

对 `seismic_view.py` 做以下修改：

**3a.** import 区：`from .workers import (...)` 的导入列表加 `SliceReadWorker`。

**3b.** `__init__`（`_pending_slice` 初始化，第 158 行）：

```python
        self._pending_slice: dict[str, int] = {}
```

并在 `__init__` 中 `self._cache = SeismicCache(max_slices=50)` 之后加：

```python
        self._slice_worker = SliceReadWorker(self)
        self._slice_worker.slice_ready.connect(self._on_slice_ready)
        self._slice_worker.prefetch_ready.connect(self._on_prefetch_ready)
        self._slice_worker.start()
```

**3c.** `_on_slice_changed`（第 844-861 行）第一行 `self._pending_slice = (slice_type, position)` 改为：

```python
        self._pending_slice[slice_type] = position
```

**3d.** `_apply_pending_slice`（第 939-998 行）整体替换为：

```python
    @Slot()
    def _apply_pending_slice(self):
        if not self._pending_slice:
            return
        pending = dict(self._pending_slice)
        self._pending_slice.clear()
        if self._meta is None:
            return

        # Rebuild only the 3D planes whose axis changed
        self._renderer_3d._update_slice_planes_for(set(pending))

        # Demo mode: slice from cached volume data directly
        if self._loader is None:
            vol = self._renderer_3d._volume_data_cpu
            if vol is None:
                return
            for slice_type, position in pending.items():
                if slice_type == "inline":
                    raw = vol[position, :, :]
                elif slice_type == "crossline":
                    raw = vol[:, position, :]
                else:
                    raw = vol[:, :, position]
                self._update_profile_panel(slice_type, position, raw.T)
            return

        m = self._meta
        df = self._ds_factor
        for slice_type, position in pending.items():
            if slice_type == "inline":
                actual_pos = m.iline_start + position * df[0] * m.iline_step
            elif slice_type == "crossline":
                actual_pos = m.xline_start + position * df[1] * m.xline_step
            else:
                actual_pos = position * df[2]

            cache_key = (slice_type, actual_pos)
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._update_profile_panel(slice_type, actual_pos, cached.T)
            else:
                # Async: worker reads from disk; panel updates on slice_ready
                self._slice_worker.request(
                    slice_type, actual_pos, self._segy_generation
                )

    @Slot(str, int, object, int)
    def _on_slice_ready(self, slice_type: str, actual_pos: int, data, generation: int):
        if generation != self._segy_generation:
            return
        self._cache.put((slice_type, actual_pos), data)
        self._update_profile_panel(slice_type, actual_pos, data.T)

    @Slot(str, int, object, int)
    def _on_prefetch_ready(self, slice_type: str, actual_pos: int, data, generation: int):
        if generation != self._segy_generation:
            return
        self._cache.put((slice_type, actual_pos), data)
```

**3e.** `_on_segy_ready` 中 `self._loader = SeismicLoader(result.path)` 之后加：

```python
        self._slice_worker.set_volume(result.path, self._segy_generation)
```

**3f.** `cancel_pending_segy_load` 末尾加（线程保持运行，仅使请求失效——worker 在 `cleanup` 才停）：

```python
        # In-flight slice reads are invalidated by the bumped generation.
```

（仅注释；generation 递增已使旧请求失效。）

**3g.** `cleanup()` 加：

```python
        self._slice_worker.stop()
```

**3h.** `_on_jump` 不变——三个 `set_position_external` 现在各自写入 `_pending_slice` 的不同键，`_apply_pending_slice` 统一处理（bug 由 3b/3d 结构性修复）。

注意：`seismic_view.py:1198` 处直接调用 `self._on_slice_changed(slice_type, position)` 的既有路径自动兼容。

- [ ] **Step 4: 运行测试确认通过 + 引擎回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest tests/test_seismic_view_async.py tests/test_seismic_view.py tests/test_seismic_workers.py tests/test_seismic_interaction.py -q
```

预期：全绿（pyvista 不可用时 skip 属预期）。

- [ ] **Step 5: 提交（geo-viz-engine 仓库）**

```bash
cd geo-viz-engine && git add packages/geoviz_seismic/geoviz_seismic/seismic_view.py tests/test_seismic_view_async.py && git commit -m "perf(seismic): async slice reads via worker, per-axis pending slices fix jump consistency"
```

---

### Task 4: workbench 预览控件修整

**Files:**
- Modify: `paleo_workbench/ui/pages/seismic_slice_preview_widget.py`
- Test: `tests/test_seismic_slice_preview_widget.py`

**Interfaces:**
- Consumes: 无（`fast_slice_to_indexed8` 现状不变）。
- Produces: 滑杆 80ms 防抖；resize 只重缩放缓存 pixmap；NumPy 构建 256 色表（无 matplotlib import）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_seismic_slice_preview_widget.py`：

```python
"""Debounced slider, cached-resize and numpy colormap for the slice preview."""
from __future__ import annotations

import sys

import numpy as np

from paleo_workbench.ui.pages.seismic_slice_preview_widget import SeismicSlicePreviewWidget


def _make_widget(qtbot):
    w = SeismicSlicePreviewWidget()
    qtbot.addWidget(w)
    vol = np.random.default_rng(5).random((16, 20, 24)).astype(np.float32)
    w.set_volume(vol) if hasattr(w, "set_volume") else setattr(w, "_volume", vol)
    if getattr(w, "_volume", None) is None:
        w._volume = vol
    return w


def test_slider_is_debounced(qtbot, monkeypatch):
    w = _make_widget(qtbot)
    calls = []
    monkeypatch.setattr(w, "_render_slice", lambda: calls.append(1))
    for v in range(5, 10):
        w.slider.setValue(v)
    assert len(calls) <= 1  # rapid changes coalesced (0 until timer fires)
    w._render_timer.stop()
    w._render_timer.timeout.emit()
    assert len(calls) == 1


def test_resize_does_not_rerender(qtbot, monkeypatch):
    w = _make_widget(qtbot)
    w.resize(400, 300)
    w.slider.setValue(3)
    if hasattr(w, "_render_timer"):
        w._render_timer.stop()
        w._render_timer.timeout.emit()
    calls = []
    import paleo_workbench.ui.pages.seismic_slice_preview_widget as mod
    monkeypatch.setattr(mod, "fast_slice_to_indexed8", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(RuntimeError("should not be called")))
    w.resize(420, 320)
    assert calls == []


def test_colormap_table_without_matplotlib(qtbot, monkeypatch):
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", None)
    w = _make_widget(qtbot)
    w._color_table = None
    w.slider.setValue(2)
    if hasattr(w, "_render_timer"):
        w._render_timer.stop()
        w._render_timer.timeout.emit()
    table = w._color_table
    assert table is not None and len(table) == 256
```

- [ ] **Step 2: 运行测试确认失败**

```bash
.venv/bin/python -m pytest tests/test_seismic_slice_preview_widget.py -v
```

预期：FAIL（`_render_timer` 不存在；resize 触发 `_render_slice`；matplotlib 被禁后色表为空）。

注意：若该控件实际构造签名不同（如无参构造/无 `set_volume`），先读文件适配 fixture，保持断言语义。

- [ ] **Step 3: 实现修整**

对 `paleo_workbench/ui/pages/seismic_slice_preview_widget.py`：

**3a.** import 区加 `from PySide6.QtCore import QTimer`（如尚无）；`__init__` 中 slider 连接处把 `self.slider.valueChanged.connect(self._on_slider_changed)` 改为：

```python
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(80)
        self._render_timer.timeout.connect(self._render_slice)
        self.slider.valueChanged.connect(self._on_slider_changed)
```

`_on_slider_changed` 中 `self._render_slice()` 改为 `self._render_timer.start()`。

**3b.** `_render_slice` 末尾保存未缩放 pixmap：`self._last_pixmap = pixmap`（在 scaled 之前）。`resizeEvent` 改为：

```python
    def resizeEvent(self, event):
        super().resizeEvent(event)
        last = getattr(self, "_last_pixmap", None)
        if last is not None and not last.isNull():
            self.image_label.setPixmap(last.scaled(
                max(self.image_label.width() - 4, 10),
                max(self.image_label.height() - 4, 10),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
```

**3c.** 色表构建段替换为纯 NumPy（seismic 蓝-白-红）：

```python
        if getattr(self, "_color_table", None) is None:
            from PySide6.QtGui import qRgba

            t = np.linspace(0.0, 1.0, 256)
            # Blue -> white -> red seismic ramp
            r = np.clip(3.0 * t - 1.0, 0.0, 1.0)
            b = np.clip(1.0 - 3.0 * t, 0.0, 1.0)
            g = np.clip(1.5 - np.abs(3.0 * t - 1.5), 0.0, 1.0)
            self._color_table = [
                qRgba(int(ri * 255), int(gi * 255), int(bi * 255), 255)
                for ri, gi, bi in zip(r, g, b)
            ]
```

（`import numpy as np` 文件已有则复用；删除 matplotlib 分支。）

- [ ] **Step 4: 运行测试确认通过 + 相关回归**

```bash
.venv/bin/python -m pytest tests/test_seismic_slice_preview_widget.py tests/test_data_reader_panel.py -q
```

预期：全绿。

- [ ] **Step 5: 提交（仓库根，含子模块 gitlink）**

```bash
git add paleo_workbench/ui/pages/seismic_slice_preview_widget.py tests/test_seismic_slice_preview_widget.py geo-viz-engine && git commit -m "perf(ui): debounce slice preview slider, cached-pixmap resize, numpy colormap"
```

---

### Task 5: 最终回归与文档

**Files:**
- Modify: `task_plan.md`、`progress.md`

**Interfaces:**
- Consumes: Task 1-4 完成。
- Produces: 无代码产出。

- [ ] **Step 1: 双仓库回归**

```bash
cd geo-viz-engine && ../.venv/bin/python -m pytest packages/geoviz_well_log/tests packages/geoviz_cross_well/tests tests/test_slice_read_worker.py tests/test_seismic_view_async.py tests/test_renderer_3d_per_axis.py tests/test_seismic_workers.py tests/test_seismic_cache.py tests/test_seismic_loader.py tests/test_curve_track.py -q
```

```bash
.venv/bin/python -m pytest tests -q
```

预期：全绿（已知：引擎 4 个既有失败中本命令只含 `test_curve_track.py::test_curve_track_viewport_culling` 一个；workbench lifecycle flake 单独跑通过则记录）。

- [ ] **Step 2: 更新 task_plan.md 与 progress.md**

`task_plan.md` Phase 14 后追加：

```markdown
### Phase 15: 地震切片交互性能加固（P4 阶段 B）

- [x] 新增 SliceReadWorker（自有 loader、最新优先队列、±2 邻域预取、generation 失效）
- [x] SeismicView 异步接线（缓存未命中不再阻塞 GUI）+ `_pending_slice` 按轴字典修复 `_on_jump` 三面板一致
- [x] renderer_3d 按轴切片平面更新（`_update_slice_planes_for`）
- [x] 预览控件 80ms 防抖、resize 缓存缩放、NumPy 色表
- **Status:** complete
```

`progress.md` 追加对应 session 记录。

- [ ] **Step 3: 提交（仓库根）**

```bash
git add task_plan.md progress.md && git commit -m "docs(plan): record phase 15 seismic slice interaction perf hardening"
```

---

## Self-Review 记录

- **Spec 覆盖**：worker+预取 → Task 1+2；缓存字节上限 → 已存在（勘察确认，计划说明）；read_timeslice → 计划内偏差（worker 化消除冻结，算法不改，计划已注明）；3D 仅重建变化平面 → Task 3；`_on_jump` → Task 2（结构性修复）；预览控件 → Task 4。阶段 B 全部条目有对应。
- **占位符扫描**：Task 3 Step 3a 的 `_create_slice_plane` 抽取给出明确职责与返回约定但逐行代码留给实现者（`_create_slice_planes` 原文 1376-1432 已在勘察摘要中，抽取是机械移动）；其余步骤含完整代码。Task 4 Step 2 允许 fixture 适配（构造签名以源码为准），断言语义固定。
- **类型一致性**：`SliceReadWorker` API（`set_volume/request/stop` + 两信号签名）在 Task 1 定义、Task 2 消费一致；`_pending_slice: dict[str, int]` 在 Task 2 测试与实现一致；`_update_slice_planes_for(set[str] | None)` 在 Task 3 定义、Task 2 Step 3d 以 `set(pending)` 消费一致；`_on_slice_ready/_on_prefetch_ready` 槽签名与 worker 信号一致。
- **风险标注**：Task 3 依赖 Task 2 的 `_update_slice_planes_for`，顺序固定为 1(worker)→2(renderer)→3(view)；pyvista 不可用的环境会 skip 3D 相关测试（既有模式）。
