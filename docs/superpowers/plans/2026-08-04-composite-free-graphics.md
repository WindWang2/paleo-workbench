# Composite 自由图形(Free Graphics)Implementation Plan

> **REQUIRED SUB-SKILL:** Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task, in order. Tasks 1–10 land in the **geo-viz-engine** submodule repo (PR-A); Tasks 11–13 land in the **paleo-workbench** parent repo (PR-B) and depend on PR-A being merged.

**Goal:** 在油藏综合图纸面上提供 9 种自由图形(文本/箭头/矩形/椭圆/多边形/手绘/图片/指北针/比例尺)的放置、移动、手柄缩放、删除与属性编辑,随 `plots/<id>.json` 持久化(schema v4),并顺带修复面板布局(`rect_mm`)不保存的缺口。

**Architecture:** 规格文档(已逐节批准,跨仓契约冻结于 §3.5):`docs/superpowers/specs/2026-08-04-composite-free-graphics-design.md`。geoviz cartography 包承载全部图形机制(方案 A);宿主 `well-log-engine/apps/wellplot-desktop/well_log_workstation` 只做持久化与窗口接线。

**Tech Stack:** PySide6 / QGraphicsScene(1 scene unit = 1 mm 纸面坐标);pytest + pytest-qt(CI);引擎仓 `geo-viz-engine/`(独立 git 仓,父仓以 gitlink 引用);宿主仓 pytest 套件在 `tests/`。

**Global Constraints(执行者必读):**

- **本地无 PySide6**:`/usr/bin/python3` 只能 `py_compile` + 跑纯 Python。凡 Qt 测试(pytest/qtbot)以 CI 为准,本地验证 = `py_compile` 全部触及文件 + 纯 Python 内联断言(纯契约模块 `records.py` 不 import Qt,可完整本地验证)。**用户已指示不要等 CI 结果**:每个任务本地验证通过即提交;PR 合并不阻塞于 CI。
- **TDD 红步适配**:Qt 测试本地跑不了,"先写失败测试"仍照写(测试先行落盘),但"验证失败/通过"在本地退化为 py_compile + 可用的纯 Python 检查;不得因此跳过写测试。
- **record dict 契约冻结**(规格 §3.5,两仓共同依赖,不得漂移):`{id, kind, style{stroke, fill, width_mm, font_mm}, geometry{x,y,w,h | points | x,y(+w)}, props{text,path,denominator,head_mm,align}}`。
- **引擎是 submodule**:PR-A 的全部 `git` 操作在 `geo-viz-engine/` 目录内执行,分支 `feat/cartography-free-graphics`;PR 合并后,PR-B 在父仓 bump gitlink。
- **精确 git add**:只 add 本任务列出的文件路径;仓库里大量 untracked 杂项(`.zcode/`、`build/`、`docs/adr/` 散落文件等)永远不提交。绝不 `git commit -a`。
- **坐标约定**:item 几何一律"纸面绝对 mm"。rect 类 item 内部存 `rect=(0,0,w,h)` + `pos=(x,y)`;points 类 item 内部存局部点 + `pos=bbox.topLeft`,`to_record()` 时还原为绝对点。读回 rect_mm 一律 `pos + rect.topLeft()`。
- **浮点**:测试坐标只用二进制精确值(整数、x.5),避免 `pos + (p - pos)` 还原时的浮点抖动。
- **提交信息**:沿用各仓既有风格(引擎:`feat(cartography): ...`;父仓:`feat(workstation): ...`),不署 AI 名。

---

## Task 1: record 契约纯 Python 模块 `records.py`(geo-viz-engine)

冻结契约的校验/归一化核心。**零 Qt import**,使宿主仓与 `/usr/bin/python3` 可独立验证;geoviz 各 item 的 `from_record` 路径与宿主测试都复用它。

**Files:**
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py`
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/records.py`
- Test: `geo-viz-engine/tests/paleo_map/test_cartography_free_records.py`

- [ ] **Step 1: 写失败测试**(importlib 按路径加载 `records.py` —— 包 `__init__.py` 链全部 import PySide6,纯测试必须绕开包导入,这样也保证 `records.py` 永不引入 Qt 依赖)

```python
# geo-viz-engine/tests/paleo_map/test_cartography_free_records.py
"""Free-graphics record contract tests — pure Python, no Qt (spec §3.5).

``records.py`` is the frozen cross-repo contract. It must stay importable
without PySide6, so this test loads it by file path instead of through the
package ``__init__`` chain (which imports Qt modules).
"""

import importlib.util
from pathlib import Path

_RECORDS_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/records.py"
)

_spec = importlib.util.spec_from_file_location("free_records", _RECORDS_PATH)
records = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(records)


def test_parse_minimal_text_record_applies_defaults():
    rec = records.parse_record(
        {"kind": "text", "geometry": {"x": 20.0, "y": 15.0}, "props": {"text": "Hi"}}
    )
    assert rec is not None
    assert rec["kind"] == "text"
    assert rec["style"] == {
        "stroke": "#000000", "fill": None, "width_mm": 0.3, "font_mm": 3.5,
    }
    assert rec["geometry"] == {"x": 20.0, "y": 15.0}
    assert rec["props"] == {"text": "Hi", "align": "left"}
    assert isinstance(rec["id"], str) and rec["id"]


def test_parse_preserves_id_and_full_style():
    rec = records.parse_record(
        {
            "id": "fixed-id",
            "kind": "rect",
            "style": {"stroke": "#FF0000", "fill": "#00ff00", "width_mm": 0.5, "font_mm": 4.0},
            "geometry": {"x": 10.0, "y": 10.0, "w": 40.0, "h": 20.0},
        }
    )
    assert rec["id"] == "fixed-id"
    assert rec["style"]["stroke"] == "#ff0000"  # hex normalised to lowercase
    assert rec["style"]["fill"] == "#00ff00"


def test_unknown_kind_rejected():
    assert records.parse_record({"kind": "blob", "geometry": {"x": 1, "y": 2}}) is None
    assert records.parse_record("not-a-dict") is None
    assert records.parse_record({"geometry": {"x": 1, "y": 2}}) is None


def test_bad_style_rejected():
    base = {"kind": "rect", "geometry": {"x": 1.0, "y": 1.0, "w": 2.0, "h": 2.0}}
    assert records.parse_record({**base, "style": {"stroke": "red"}}) is None
    assert records.parse_record({**base, "style": {"fill": "#xyzxyz"}}) is None
    assert records.parse_record({**base, "style": {"width_mm": -1}}) is None
    assert records.parse_record({**base, "style": {"width_mm": float("nan")}}) is None


def test_geometry_rules_per_kind():
    # box kinds need positive w/h
    assert records.parse_record(
        {"kind": "ellipse", "geometry": {"x": 1.0, "y": 1.0, "w": 0.0, "h": 2.0}}
    ) is None
    # polygon needs >= 3 points
    assert records.parse_record(
        {"kind": "polygon", "geometry": {"points": [[0.0, 0.0], [4.0, 0.0]]}}
    ) is None
    # arrow/freehand need >= 2 points
    assert records.parse_record(
        {"kind": "arrow", "geometry": {"points": [[0.0, 0.0]]}}
    ) is None
    assert records.parse_record(
        {"kind": "freehand", "geometry": {"points": [[0.0, 0.0], [4.0, 4.0]]}}
    ) is not None
    # text accepts optional wrap width, rejects bad one
    ok = records.parse_record({"kind": "text", "geometry": {"x": 1.0, "y": 1.0, "w": 30.0}})
    assert ok["geometry"]["w"] == 30.0
    assert records.parse_record(
        {"kind": "text", "geometry": {"x": 1.0, "y": 1.0, "w": -3.0}}
    ) is None


def test_props_rules_per_kind():
    # image requires a non-empty path
    assert records.parse_record(
        {"kind": "image", "geometry": {"x": 1.0, "y": 1.0, "w": 2.0, "h": 2.0}}
    ) is None
    ok = records.parse_record(
        {"kind": "image", "geometry": {"x": 1.0, "y": 1.0, "w": 2.0, "h": 2.0},
         "props": {"path": "plots/assets/p/a.png"}}
    )
    assert ok["props"] == {"path": "plots/assets/p/a.png"}
    # scale_bar denominator coerced to int, default 5000
    ok = records.parse_record(
        {"kind": "scale_bar", "geometry": {"x": 1.0, "y": 1.0, "w": 50.0, "h": 9.0}}
    )
    assert ok["props"] == {"denominator": 5000}
    assert records.parse_record(
        {"kind": "scale_bar", "geometry": {"x": 1.0, "y": 1.0, "w": 50.0, "h": 9.0},
         "props": {"denominator": -5}}
    ) is None
    # arrow head default 3.0; text align validated
    ok = records.parse_record({"kind": "arrow", "geometry": {"points": [[0.0, 0.0], [4.0, 0.0]]}})
    assert ok["props"] == {"head_mm": 3.0}
    assert records.parse_record(
        {"kind": "text", "geometry": {"x": 1.0, "y": 1.0}, "props": {"align": "justify"}}
    ) is None


def test_is_hex_colour():
    assert records.is_hex_colour("#a1B2c3")
    assert not records.is_hex_colour("a1b2c3")
    assert not records.is_hex_colour("#a1b2")
    assert not records.is_hex_colour(None)
```

- [ ] **Step 2: 验证失败**

```bash
cd geo-viz-engine && /usr/bin/python3 -m pytest tests/paleo_map/test_cartography_free_records.py -x 2>&1 | tail -3
```
预期:`spec_from_file_location` 目标文件不存在 → `exec_module` 抛 `FileNotFoundError`(红)。若本地 pytest 因 `tests/conftest.py` 的 `segyio` import 失败,用内联脚本替代(同样应红):
```bash
cd geo-viz-engine && /usr/bin/python3 - <<'EOF'
import importlib.util
from pathlib import Path
p = Path("packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/records.py")
spec = importlib.util.spec_from_file_location("free_records", p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)  # FileNotFoundError before implementation
EOF
```

- [ ] **Step 3: 实现 `records.py` + 包 `__init__.py`**

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py`(本任务先放空壳,后续任务往 `ITEM_CLASSES` 注册):

```python
"""Free graphics items — nine paper annotation kinds + record registry.

``records`` (pure Python, no Qt) is the frozen cross-repo record contract
(spec §3.5). ``ITEM_CLASSES`` maps kind -> item class; populated as the item
modules land (Tasks 3–6).
"""

from geoviz_paleo_map.cartography.items.free import records

ITEM_CLASSES: dict = {}

__all__ = ["records", "ITEM_CLASSES"]
```

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/records.py`:

```python
"""Free-graphics record schema — the frozen cross-repo contract (spec §3.5).

Pure Python, **no Qt imports**: the host repo (paleo-workbench) and plain
``/usr/bin/python3`` must be able to verify the contract without PySide6.
geoviz item classes consume :func:`parse_record` output in their
``from_normalized`` constructors; the host reuses the same validation in its
persistence boundary.

Record shape (all geometry in paper-absolute mm)::

    {
      "id": "uuid4-string",
      "kind": "text|arrow|rect|ellipse|polygon|freehand|image|north_arrow|scale_bar",
      "style": {"stroke": "#000000", "fill": None, "width_mm": 0.3, "font_mm": 3.5},
      "geometry": {"x": 20.0, "y": 15.0, "w": 60.0, "h": 12.0}   # box kinds
                | {"points": [[x, y], ...]}                      # arrow/polygon/freehand
                | {"x": 20.0, "y": 15.0, "w": 60.0(optional)},   # text
      "props": {"text": "...", "align": "left"}                  # text
             | {"head_mm": 3.0}                                  # arrow
             | {"path": "plots/assets/<plot_id>/<uuid>.png"}     # image
             | {"denominator": 5000}                             # scale_bar
             | {},                                               # others
    }
"""

from __future__ import annotations

import math
import re
import uuid

KINDS = (
    "text", "arrow", "rect", "ellipse", "polygon",
    "freehand", "image", "north_arrow", "scale_bar",
)

POINT_KINDS = ("arrow", "polygon", "freehand")
BOX_KINDS = ("rect", "ellipse", "image", "north_arrow", "scale_bar")

DEFAULT_STYLE = {"stroke": "#000000", "fill": None, "width_mm": 0.3, "font_mm": 3.5}

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def is_hex_colour(value) -> bool:
    """True for ``#rrggbb`` strings (case-insensitive)."""
    return isinstance(value, str) and bool(_HEX_RE.match(value))


def _finite(value):
    """float(value) if finite, else None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def normalize_style(raw) -> dict | None:
    """Normalise a style dict; defaults fill gaps; None when invalid."""
    style = dict(DEFAULT_STYLE)
    if raw is None:
        return style
    if not isinstance(raw, dict):
        return None
    stroke = raw.get("stroke", style["stroke"])
    if stroke is not None and not is_hex_colour(stroke):
        return None
    fill = raw.get("fill")
    if fill is not None and not is_hex_colour(fill):
        return None
    width = _finite(raw.get("width_mm", style["width_mm"]))
    if width is None or width <= 0:
        return None
    font = _finite(raw.get("font_mm", style["font_mm"]))
    if font is None or font <= 0:
        return None
    style["stroke"] = stroke.lower() if isinstance(stroke, str) else stroke
    style["fill"] = fill.lower() if isinstance(fill, str) else None
    style["width_mm"] = width
    style["font_mm"] = font
    return style


def normalize_geometry(kind: str, raw) -> dict | None:
    """Normalise the geometry subset for ``kind``; None when invalid."""
    if not isinstance(raw, dict):
        return None
    if kind in POINT_KINDS:
        pts = raw.get("points")
        if not isinstance(pts, (list, tuple)):
            return None
        out = []
        for p in pts:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                return None
            x = _finite(p[0])
            y = _finite(p[1])
            if x is None or y is None:
                return None
            out.append([x, y])
        min_pts = 3 if kind == "polygon" else 2
        if len(out) < min_pts:
            return None
        return {"points": out}
    if kind == "text":
        x = _finite(raw.get("x"))
        y = _finite(raw.get("y"))
        if x is None or y is None:
            return None
        geom: dict = {"x": x, "y": y}
        if "w" in raw and raw["w"] is not None:
            w = _finite(raw["w"])
            if w is None or w <= 0:
                return None
            geom["w"] = w
        return geom
    if kind in BOX_KINDS:
        vals = [_finite(raw.get(k)) for k in ("x", "y", "w", "h")]
        if any(v is None for v in vals):
            return None
        x, y, w, h = vals
        if w <= 0 or h <= 0:
            return None
        return {"x": x, "y": y, "w": w, "h": h}
    return None


def normalize_props(kind: str, raw) -> dict | None:
    """Normalise kind-specific props; defaults fill gaps; None when invalid."""
    props: dict = {}
    raw = raw if isinstance(raw, dict) else {}
    if kind == "text":
        text = raw.get("text", "")
        if not isinstance(text, str):
            return None
        align = raw.get("align", "left")
        if align not in ("left", "center", "right"):
            return None
        props["text"] = text
        props["align"] = align
    elif kind == "arrow":
        head = _finite(raw.get("head_mm", 3.0))
        if head is None or head <= 0:
            return None
        props["head_mm"] = head
    elif kind == "image":
        path = raw.get("path")
        if not isinstance(path, str) or not path:
            return None
        props["path"] = path
    elif kind == "scale_bar":
        try:
            den = int(raw.get("denominator", 5000))
        except (TypeError, ValueError):
            return None
        if den <= 0:
            return None
        props["denominator"] = den
    return props


def parse_record(record) -> dict | None:
    """Validate + normalise a free-graphics record; None when malformed.

    Output always carries all five keys (``id``/``kind``/``style``/
    ``geometry``/``props``); a missing/blank ``id`` gets a fresh uuid4.
    """
    if not isinstance(record, dict):
        return None
    kind = record.get("kind")
    if kind not in KINDS:
        return None
    style = normalize_style(record.get("style"))
    geometry = normalize_geometry(kind, record.get("geometry"))
    props = normalize_props(kind, record.get("props"))
    if style is None or geometry is None or props is None:
        return None
    item_id = record.get("id")
    if not isinstance(item_id, str) or not item_id:
        item_id = str(uuid.uuid4())
    return {
        "id": item_id,
        "kind": kind,
        "style": style,
        "geometry": geometry,
        "props": props,
    }
```

- [ ] **Step 4: 验证通过**

```bash
cd geo-viz-engine
/usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/records.py \
  tests/paleo_map/test_cartography_free_records.py
/usr/bin/python3 - <<'EOF'
import importlib.util
from pathlib import Path
p = Path("packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/records.py")
spec = importlib.util.spec_from_file_location("free_records", p)
records = importlib.util.module_from_spec(spec)
spec.loader.exec_module(records)
rec = records.parse_record({"kind": "text", "geometry": {"x": 20.0, "y": 15.0}, "props": {"text": "Hi"}})
assert rec["style"] == {"stroke": "#000000", "fill": None, "width_mm": 0.3, "font_mm": 3.5}
assert rec["props"] == {"text": "Hi", "align": "left"}
assert records.parse_record({"kind": "blob", "geometry": {}}) is None
assert records.parse_record({"kind": "polygon", "geometry": {"points": [[0.0, 0.0], [4.0, 0.0]]}}) is None
assert records.parse_record({"kind": "rect", "style": {"stroke": "red"}, "geometry": {"x": 1.0, "y": 1.0, "w": 2.0, "h": 2.0}}) is None
ok = records.parse_record({"kind": "image", "geometry": {"x": 1.0, "y": 1.0, "w": 2.0, "h": 2.0}, "props": {"path": "plots/assets/p/a.png"}})
assert ok["props"] == {"path": "plots/assets/p/a.png"}
assert records.is_hex_colour("#a1B2c3") and not records.is_hex_colour("red")
print("records.py pure checks OK")
EOF
```

- [ ] **Step 5: 提交**

```bash
cd geo-viz-engine
git checkout -b feat/cartography-free-graphics   # 若尚未建分支(在 Task 1 建,后续任务复用)
git add packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
        packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/records.py \
        tests/paleo_map/test_cartography_free_records.py
git commit -m "feat(cartography): free-graphics record contract (pure python, spec §3.5)"
```

---

## Task 2: `base_item.py` 真实 resize 手柄(geo-viz-engine)

把 8 个手柄从"只画不用"变成真实缩放:命中检测 + 场景坐标拖动映射 + `resize_to()` 归一化 + `_remap_content()` 子类钩子。面板 item(`FigurePanelGraphicsItem`)同步受益 —— 这是宿主"面板布局保存"修复的前置。同时把选中手柄绘制抽成 `_paint_selection_handles()`,供自由图形子类复用(它们不画默认边框)。

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/base_item.py`
- Test: `geo-viz-engine/tests/paleo_map/test_cartography_resize.py`

- [ ] **Step 1: 写失败测试**

```python
# geo-viz-engine/tests/paleo_map/test_cartography_resize.py
"""Real resize-handle behaviour on LayoutGraphicsItem (Task 2).

The 8 handles used to be paint-only. Now a selected item can be resized by
dragging a handle; ``resize_to`` normalises any local rect (possibly with a
non-zero origin mid-drag) to ``pos + (0,0,w,h)``.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import QGraphicsScene

from geoviz_paleo_map.cartography.items.base_item import LayoutGraphicsItem


def _item(rect=QRectF(0, 0, 40.0, 20.0), pos=QPointF(10.0, 10.0)):
    scene = QGraphicsScene()
    item = LayoutGraphicsItem(rect)
    item.setPos(pos)
    scene.addItem(item)
    return scene, item


def test_hit_handle_requires_selection():
    _, item = _item()
    assert item.hit_handle(QPointF(40.0, 20.0)) is None  # not selected
    item.setSelected(True)
    assert item.hit_handle(QPointF(40.0, 20.0)) == "br"
    assert item.hit_handle(QPointF(0.0, 0.0)) == "tl"
    assert item.hit_handle(QPointF(20.0, 0.0)) == "t"
    assert item.hit_handle(QPointF(20.0, 10.0)) is None  # centre: no handle


def test_resize_to_grows_from_origin():
    _, item = _item()
    item.resize_to(QRectF(0, 0, 60.0, 30.0))
    assert item.pos() == QPointF(10.0, 10.0)
    assert item.rect() == QRectF(0, 0, 60.0, 30.0)


def test_resize_to_normalises_nonzero_origin():
    # Mid-drag from a top/left handle the local rect has a non-zero origin;
    # resize_to must fold it into pos and zero the rect origin.
    _, item = _item()
    item.resize_to(QRectF(5.0, 4.0, 35.0, 16.0))
    assert item.pos() == QPointF(15.0, 14.0)
    assert item.rect() == QRectF(0, 0, 35.0, 16.0)


def test_resize_to_rejects_degenerate():
    _, item = _item()
    item.resize_to(QRectF(0, 0, 0.0, 10.0))
    assert item.rect() == QRectF(0, 0, 40.0, 20.0)  # unchanged


def test_remap_content_hook_called():
    calls = []

    class Spy(LayoutGraphicsItem):
        def _remap_content(self, old, new_local):
            calls.append((QRectF(old), QRectF(new_local)))

    scene = QGraphicsScene()
    spy = Spy(QRectF(0, 0, 10.0, 10.0))
    scene.addItem(spy)
    spy.resize_to(QRectF(0, 0, 20.0, 20.0))
    assert calls == [(QRectF(0, 0, 10.0, 10.0), QRectF(0, 0, 20.0, 20.0))]


def test_handle_size_is_class_attribute():
    assert LayoutGraphicsItem.handle_size == 4.0
```

- [ ] **Step 2: 验证失败**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile tests/paleo_map/test_cartography_resize.py
```
Qt 测试本地不可跑(无 PySide6),CI 为权威;本地红步 = 测试引用的 `hit_handle`/`resize_to`/`handle_size` 尚不存在(源码 grep 确认):
```bash
grep -n "hit_handle\|resize_to\|handle_size" packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/base_item.py || echo "RED: API missing"
```

- [ ] **Step 3: 实现 —— 整文件替换 `base_item.py`**

```python
# packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/base_item.py
"""Base draggable and resizable paper graphics item with selection feedback.

Resize model: when the item is selected, ``hit_handle`` maps an item-coord
position to one of the 8 handles (corners + edge midpoints). A handle drag
is tracked in **scene coordinates** (``_resize_scene_rect`` captured at
press) so repeated ``resize_to`` normalisation during the drag cannot
accumulate frame error. ``resize_to`` accepts a local rect with a possibly
non-zero origin (top/left drags) and normalises it to ``pos + (0,0,w,h)``;
subclasses carrying geometry beyond the plain rect (point lists, text wrap)
override :meth:`_remap_content`.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QBrush, QPainter
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem

MIN_ITEM_SIZE_MM = 2.0


class LayoutGraphicsItem(QGraphicsRectItem):
    """Base item for interactive paper elements supporting drag and resize handles."""

    handle_size = 4.0  # mm (scene units); was a paint() local

    def __init__(self, rect: QRectF, parent=None):
        super().__init__(rect, parent)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setPen(QPen(QColor("#1f66d4"), 1.0))
        self.setBrush(QBrush(QColor("#ffffff")))
        self._resize_handle: str | None = None
        self._resize_scene_rect = QRectF()

    # -- handles --------------------------------------------------------

    def _handle_points(self) -> dict[str, QPointF]:
        r = self.rect()
        return {
            "tl": r.topLeft(),
            "t": (r.topLeft() + r.topRight()) / 2,
            "tr": r.topRight(),
            "r": (r.topRight() + r.bottomRight()) / 2,
            "br": r.bottomRight(),
            "b": (r.bottomLeft() + r.bottomRight()) / 2,
            "bl": r.bottomLeft(),
            "l": (r.topLeft() + r.bottomLeft()) / 2,
        }

    def hit_handle(self, pos: QPointF) -> str | None:
        """Handle id under item-coord ``pos`` (selected items only)."""
        if not self.isSelected():
            return None
        tol = self.handle_size
        for name, p in self._handle_points().items():
            if abs(pos.x() - p.x()) <= tol and abs(pos.y() - p.y()) <= tol:
                return name
        return None

    # -- resize ---------------------------------------------------------

    def resize_to(self, new_local: QRectF) -> None:
        """Apply a resize given in item coordinates (origin may be non-zero).

        Normalises to ``pos + (0,0,w,h)``: the position shifts by the local
        origin, the rect becomes origin-zero. Subclass content hook runs
        first so it can read the old frame.
        """
        old = QRectF(self.rect())
        if (
            old.width() <= 0 or old.height() <= 0
            or new_local.width() <= 0 or new_local.height() <= 0
        ):
            return
        self._remap_content(old, new_local)
        self.setPos(self.pos() + new_local.topLeft())
        self.setRect(QRectF(0, 0, new_local.width(), new_local.height()))
        self.update()

    def _remap_content(self, old: QRectF, new_local: QRectF) -> None:
        """Subclass hook for content not described by the plain rect."""

    # -- mouse ----------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        handle = self.hit_handle(event.pos())
        if handle is not None and event.button() == Qt.MouseButton.LeftButton:
            self._resize_handle = handle
            self._resize_scene_rect = self.mapToScene(self.rect()).boundingRect()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resize_handle is None:
            super().mouseMoveEvent(event)
            return
        r = QRectF(self._resize_scene_rect)
        s = event.scenePos()
        h = self._resize_handle
        if "l" in h:
            r.setLeft(min(s.x(), r.right() - MIN_ITEM_SIZE_MM))
        if "r" in h:
            r.setRight(max(s.x(), r.left() + MIN_ITEM_SIZE_MM))
        if "t" in h:
            r.setTop(min(s.y(), r.bottom() - MIN_ITEM_SIZE_MM))
        if "b" in h:
            r.setBottom(max(s.y(), r.top() + MIN_ITEM_SIZE_MM))
        self.resize_to(self.mapFromScene(r).boundingRect())

    def mouseReleaseEvent(self, event) -> None:
        if self._resize_handle is not None:
            self._resize_handle = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- paint ----------------------------------------------------------

    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            self._paint_selection_handles(painter)

    def _paint_selection_handles(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor("#1f66d4"), 1.5))
        painter.setBrush(QBrush(QColor("#ffffff")))
        hs = self.handle_size
        for p in self._handle_points().values():
            painter.drawRect(QRectF(p.x() - hs / 2, p.y() - hs / 2, hs, hs))
```

- [ ] **Step 4: 验证通过**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/base_item.py \
  tests/paleo_map/test_cartography_resize.py
grep -c "hit_handle\|resize_to\|_remap_content\|_paint_selection_handles" \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/base_item.py   # 预期 >= 8
```
(Qt 行为测试 `test_cartography_resize.py` 由 CI 跑;本地等价逻辑已含在 resize_to 纯几何中。)

- [ ] **Step 5: 提交**

```bash
cd geo-viz-engine
git add packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/base_item.py \
        tests/paleo_map/test_cartography_resize.py
git commit -m "feat(cartography): real resize handles on LayoutGraphicsItem (hit test + resize_to + remap hook)"
```

---

## Task 3: `FreeGraphicsItem` 基类 + 框类 item(rect/ellipse)(geo-viz-engine)

基类统一 `id`/`kind`/样式存储、`to_record()`/`from_normalized()` 契约、选中装饰(不画默认边框)、右键菜单(属性/删除)。框类两个 item 验证序列化 round-trip。

**Files:**
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/base.py`
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/box_items.py`
- Modify: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py`(注册两个类)
- Test: `geo-viz-engine/tests/paleo_map/test_cartography_free_graphics.py`(本任务新建,后续任务持续追加)

- [ ] **Step 1: 写失败测试**

```python
# geo-viz-engine/tests/paleo_map/test_cartography_free_graphics.py
"""FreeGraphicsItem subclasses: serialization round-trips + paint smoke.

Record contract: spec §3.5 (frozen). Items store geometry internally as
``rect=(0,0,w,h) + pos=(x,y)`` (box kinds) or local points + pos=bbox origin
(point kinds); ``to_record`` always emits paper-absolute mm.
"""

import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter

from geoviz_paleo_map.cartography.items.free import ITEM_CLASSES, records
from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem, mm_font
from geoviz_paleo_map.cartography.items.free.box_items import (
    FreeEllipseItem,
    FreeRectItem,
)


def _roundtrip(item):
    """item -> record -> parse -> from_normalized -> record (must be identical)."""
    rec1 = item.to_record()
    norm = records.parse_record(rec1)
    assert norm is not None, f"own to_record rejected by parse_record: {rec1}"
    item2 = ITEM_CLASSES[norm["kind"]].from_normalized(norm)
    assert item2 is not None
    assert item2.id == item.id
    return item2.to_record()


def _paint_smoke(item):
    img = QImage(120, 90, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    item.paint(p, None, None)
    p.end()


def test_base_stores_style_and_id():
    item = FreeRectItem(QRectF(10.0, 10.0, 40.0, 20.0))
    assert isinstance(item, FreeGraphicsItem)
    assert item.kind == "rect"
    assert item.id and isinstance(item.id, str)
    assert item.stroke == "#000000" and item.fill is None
    assert item.width_mm == 0.3 and item.font_mm == 3.5
    # free items draw no default frame
    assert item.pen().style() == item.pen().Style.NoPen


def test_rect_roundtrip():
    item = FreeRectItem(QRectF(10.0, 10.0, 40.0, 20.0))
    item.fill = "#ff0000"
    rec = _roundtrip(item)
    assert rec["geometry"] == {"x": 10.0, "y": 10.0, "w": 40.0, "h": 20.0}
    assert rec["style"]["fill"] == "#ff0000"


def test_ellipse_roundtrip():
    item = FreeEllipseItem(QRectF(5.0, 6.0, 30.0, 12.0))
    rec = _roundtrip(item)
    assert rec["kind"] == "ellipse"
    assert rec["geometry"] == {"x": 5.0, "y": 6.0, "w": 30.0, "h": 12.0}
    assert rec["props"] == {}


def test_box_items_survive_move_and_resize():
    item = FreeRectItem(QRectF(10.0, 10.0, 40.0, 20.0))
    item.setPos(QPointF(30.0, 25.0))
    assert item.to_record()["geometry"] == {"x": 30.0, "y": 25.0, "w": 40.0, "h": 20.0}
    item.resize_to(QRectF(0, 0, 55.0, 30.0))
    assert item.to_record()["geometry"] == {"x": 30.0, "y": 25.0, "w": 55.0, "h": 30.0}


def test_apply_style_updates_fields():
    item = FreeRectItem(QRectF(0.0, 0.0, 10.0, 10.0))
    item.apply_style({"stroke": "#00ff00", "fill": "#0000ff", "width_mm": 1.5, "font_mm": 5.0})
    assert item.stroke == "#00ff00"
    assert item.fill == "#0000ff"
    assert item.width_mm == 1.5
    assert item.font_mm == 5.0


def test_paint_smoke_box_items(qtbot):
    _paint_smoke(FreeRectItem(QRectF(0.0, 0.0, 40.0, 20.0)))
    _paint_smoke(FreeEllipseItem(QRectF(0.0, 0.0, 40.0, 20.0)))


def test_mm_font_scales_points():
    f = mm_font(3.5)
    assert f.pointSizeF() == pytest.approx(3.5 * 72.0 / 25.4)
```

- [ ] **Step 2: 验证失败**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile tests/paleo_map/test_cartography_free_graphics.py
ls packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/base.py 2>&1  # 预期不存在(红)
```

- [ ] **Step 3: 实现 `base.py` + `box_items.py` + 注册**

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/base.py`:

```python
"""FreeGraphicsItem — base class for the nine paper free-graphic kinds.

Unifies: ``id`` (uuid4), ``kind``, style storage (``stroke``/``fill``/
``width_mm``/``font_mm``), the ``to_record()`` / ``from_normalized()``
serialization contract (spec §3.5), selection decoration without the default
frame, and the context menu (属性 / 删除).

Internal geometry convention: box kinds keep ``rect=(0,0,w,h)`` with the
paper-absolute position in ``pos``; point kinds keep local points with
``pos=bbox.topLeft``. ``to_record`` always emits paper-absolute mm.
"""

from __future__ import annotations

import uuid

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPen
from PySide6.QtWidgets import QMenu

from geoviz_paleo_map.cartography.items.base_item import LayoutGraphicsItem
from geoviz_paleo_map.cartography.items.free import records

POINTS_PER_MM = 72.0 / 25.4


def mm_font(font_mm: float, bold: bool = False) -> QFont:
    """QFont whose point size renders ``font_mm`` millimetres tall on paper.

    Font sizes are stored/edited in mm (paper-deliverable intuition, spec
    §3.1); painting converts mm -> pt (1 pt = 25.4/72 mm).
    """
    font = QFont("Sans Serif")
    font.setPointSizeF(font_mm * POINTS_PER_MM)
    font.setBold(bold)
    return font


class FreeGraphicsItem(LayoutGraphicsItem):
    """Common id/kind/style/serialization for paper free graphics."""

    kind: str = ""

    def __init__(self, rect: QRectF, parent=None) -> None:
        super().__init__(rect, parent)
        self.id = str(uuid.uuid4())
        self.stroke: str = records.DEFAULT_STYLE["stroke"]
        self.fill: str | None = None
        self.width_mm: float = records.DEFAULT_STYLE["width_mm"]
        self.font_mm: float = records.DEFAULT_STYLE["font_mm"]
        # Free graphics paint their own content; the base frame (blue pen /
        # white brush set by LayoutGraphicsItem) must not show.
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    # -- style ----------------------------------------------------------

    def stroke_pen(self) -> QPen:
        pen = QPen(QColor(self.stroke), self.width_mm)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    def fill_brush(self) -> QBrush:
        if self.fill is None:
            return QBrush(Qt.BrushStyle.NoBrush)
        return QBrush(QColor(self.fill))

    def apply_style(self, style: dict) -> None:
        self.stroke = style["stroke"]
        self.fill = style["fill"]
        self.width_mm = style["width_mm"]
        self.font_mm = style["font_mm"]
        self.update()

    # -- serialization (spec §3.5) --------------------------------------

    def style_record(self) -> dict:
        return {
            "stroke": self.stroke,
            "fill": self.fill,
            "width_mm": self.width_mm,
            "font_mm": self.font_mm,
        }

    def geometry_record(self) -> dict:
        raise NotImplementedError

    def props_record(self) -> dict:
        return {}

    def to_record(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "style": self.style_record(),
            "geometry": self.geometry_record(),
            "props": self.props_record(),
        }

    def _init_from_normalized(self, rec: dict) -> None:
        """Shared tail of every ``from_normalized``: id + style."""
        self.id = rec["id"]
        self.apply_style(rec["style"])

    @classmethod
    def from_normalized(cls, rec: dict) -> "FreeGraphicsItem":
        """Build from ``records.parse_record`` output. Subclasses implement."""
        raise NotImplementedError

    def set_frame_from_geometry(self, g: dict) -> None:
        """Box-kind helper: absolute ``{x,y,w,h}`` -> pos + origin-zero rect."""
        self.setRect(0, 0, g["w"], g["h"])
        self.setPos(g["x"], g["y"])

    def frame_geometry_record(self) -> dict:
        """Box-kind helper: pos + rect -> absolute ``{x,y,w,h}``."""
        p = self.pos()
        r = self.rect()
        return {"x": p.x() + r.x(), "y": p.y() + r.y(), "w": r.width(), "h": r.height()}

    # -- paint ------------------------------------------------------------

    def paint(self, painter, option, widget=None) -> None:
        self.paint_content(painter)
        if self.isSelected():
            self._paint_selection_handles(painter)

    def paint_content(self, painter) -> None:
        raise NotImplementedError

    # -- context menu (属性 / 删除; spec §3.4) ----------------------------

    def contextMenuEvent(self, event) -> None:
        self.setSelected(True)
        menu = QMenu()
        prop_action = menu.addAction("属性")
        del_action = menu.addAction("删除")
        chosen = menu.exec(event.screenPos())
        if chosen is del_action:
            scene = self.scene()
            if scene is not None:
                scene.removeItem(self)
        # "属性": selection alone drives the window's property panel.
```

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/box_items.py`:

```python
"""Box-kind free graphics: FreeRectItem, FreeEllipseItem."""

from __future__ import annotations

from PySide6.QtCore import QRectF

from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem


class FreeRectItem(FreeGraphicsItem):
    kind = "rect"

    def __init__(self, rect_scene: QRectF, parent=None) -> None:
        super().__init__(QRectF(0, 0, rect_scene.width(), rect_scene.height()), parent)
        self.setPos(rect_scene.topLeft())

    def paint_content(self, painter) -> None:
        painter.setPen(self.stroke_pen())
        painter.setBrush(self.fill_brush())
        painter.drawRect(self.rect())

    def geometry_record(self) -> dict:
        return self.frame_geometry_record()

    @classmethod
    def from_normalized(cls, rec: dict) -> "FreeRectItem":
        g = rec["geometry"]
        item = cls(QRectF(g["x"], g["y"], g["w"], g["h"]))
        item._init_from_normalized(rec)
        return item


class FreeEllipseItem(FreeGraphicsItem):
    kind = "ellipse"

    def __init__(self, rect_scene: QRectF, parent=None) -> None:
        super().__init__(QRectF(0, 0, rect_scene.width(), rect_scene.height()), parent)
        self.setPos(rect_scene.topLeft())

    def paint_content(self, painter) -> None:
        painter.setPen(self.stroke_pen())
        painter.setBrush(self.fill_brush())
        painter.drawEllipse(self.rect())

    def geometry_record(self) -> dict:
        return self.frame_geometry_record()

    @classmethod
    def from_normalized(cls, rec: dict) -> "FreeEllipseItem":
        g = rec["geometry"]
        item = cls(QRectF(g["x"], g["y"], g["w"], g["h"]))
        item._init_from_normalized(rec)
        return item
```

`__init__.py` 改为(注册本任务两个类,后续任务继续追加):

```python
"""Free graphics items — nine paper annotation kinds + record registry.

``records`` (pure Python, no Qt) is the frozen cross-repo record contract
(spec §3.5). ``ITEM_CLASSES`` maps kind -> item class; ``item_from_record``
is the window's restore path (unknown/malformed records -> None, the host
counts and reports them).
"""

from geoviz_paleo_map.cartography.items.free import records
from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem
from geoviz_paleo_map.cartography.items.free.box_items import (
    FreeEllipseItem,
    FreeRectItem,
)

ITEM_CLASSES: dict[str, type[FreeGraphicsItem]] = {
    cls.kind: cls
    for cls in (FreeRectItem, FreeEllipseItem)
}


def item_from_record(record: dict) -> FreeGraphicsItem | None:
    """Validate ``record`` (frozen contract) and build the item; None when
    the kind is unknown or the record is malformed."""
    norm = records.parse_record(record)
    if norm is None:
        return None
    cls = ITEM_CLASSES.get(norm["kind"])
    if cls is None:
        return None
    try:
        return cls.from_normalized(norm)
    except Exception:
        return None


__all__ = [
    "records",
    "FreeGraphicsItem",
    "FreeRectItem",
    "FreeEllipseItem",
    "ITEM_CLASSES",
    "item_from_record",
]
```

- [ ] **Step 4: 验证通过**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/base.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/box_items.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
  tests/paleo_map/test_cartography_free_graphics.py
```
(Qt round-trip 测试由 CI 跑。)

- [ ] **Step 5: 提交**

```bash
cd geo-viz-engine
git add packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/base.py \
        packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/box_items.py \
        packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
        tests/paleo_map/test_cartography_free_graphics.py
git commit -m "feat(cartography): FreeGraphicsItem base + rect/ellipse items with record round-trip"
```

---

## Task 4: `FreeTextItem`(geo-viz-engine)

文本:几何 `(x, y)` + 可选折行宽 `w`;字号 mm;对齐 left/center/right。resize 只改折行宽,高度随内容重排。

**Files:**
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/text_item.py`
- Modify: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py`
- Test: `geo-viz-engine/tests/paleo_map/test_cartography_free_graphics.py`(追加)

- [ ] **Step 1: 写失败测试(追加到既有测试文件)**

```python
# 追加到 geo-viz-engine/tests/paleo_map/test_cartography_free_graphics.py
from geoviz_paleo_map.cartography.items.free.text_item import FreeTextItem


def test_text_roundtrip_minimal():
    item = FreeTextItem(QPointF(20.0, 15.0), text="井位图")
    rec = _roundtrip(item)
    assert rec["kind"] == "text"
    assert rec["geometry"] == {"x": 20.0, "y": 15.0}
    assert rec["props"] == {"text": "井位图", "align": "left"}


def test_text_roundtrip_with_wrap_and_align():
    item = FreeTextItem(QPointF(20.0, 15.0), text="长文本折行", wrap_w=30.0)
    item.align = "center"
    rec = _roundtrip(item)
    assert rec["geometry"] == {"x": 20.0, "y": 15.0, "w": 30.0}
    assert rec["props"]["align"] == "center"


def test_text_resize_sets_wrap_width():
    item = FreeTextItem(QPointF(20.0, 15.0), text="abc")
    assert "w" not in item.to_record()["geometry"]
    item.resize_to(QRectF(0, 0, 25.0, 8.0))
    geom = item.to_record()["geometry"]
    assert geom["w"] == 25.0
    assert geom["x"] == 20.0 and geom["y"] == 15.0
    assert item.rect().width() == 25.0
    assert item.rect().height() > 0


def test_text_font_mm_drives_height():
    small = FreeTextItem(QPointF(0.0, 0.0), text="Hg")
    large = FreeTextItem(QPointF(0.0, 0.0), text="Hg")
    large.apply_style({"stroke": "#000000", "fill": None, "width_mm": 0.3, "font_mm": 10.0})
    assert large.rect().height() > small.rect().height()


def test_paint_smoke_text(qtbot):
    _paint_smoke(FreeTextItem(QPointF(0.0, 0.0), text="冒烟", wrap_w=30.0))
```

- [ ] **Step 2: 验证失败**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile tests/paleo_map/test_cartography_free_graphics.py
ls packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/text_item.py 2>&1  # 预期不存在(红)
```

- [ ] **Step 3: 实现 `text_item.py` + 注册**

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/text_item.py`:

```python
"""FreeTextItem — paper text annotation with mm font size and word wrap."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPen

from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem, mm_font

_ALIGN = {
    "left": Qt.AlignmentFlag.AlignLeft,
    "center": Qt.AlignmentFlag.AlignHCenter,
    "right": Qt.AlignmentFlag.AlignRight,
}


class FreeTextItem(FreeGraphicsItem):
    """Text at ``pos``; optional wrap width (record geometry ``w``).

    The item rect is always ``(0,0,w,h)``; without a wrap width ``w`` tracks
    the natural text width. Resizing sets the wrap width and reflows; the
    height always follows content + ``font_mm``.
    """

    kind = "text"

    def __init__(self, pos: QPointF, text: str = "", wrap_w: float | None = None, parent=None) -> None:
        super().__init__(QRectF(0, 0, 40.0, 8.0), parent)
        self.setPos(pos)
        self.text = text
        self.align = "left"
        self._wrap_w = wrap_w
        self._reflow()

    # -- layout ---------------------------------------------------------

    def _reflow(self) -> None:
        fm = QFontMetricsF(mm_font(self.font_mm))
        flags = int(Qt.TextFlag.TextWordWrap)
        if self._wrap_w:
            br = fm.boundingRect(
                QRectF(0, 0, self._wrap_w, 10000.0), flags, self.text or " "
            )
            w, h = self._wrap_w, max(br.height(), self.font_mm)
        else:
            br = fm.boundingRect(self.text or " ")
            w, h = max(br.width(), 5.0), max(br.height(), self.font_mm)
        self.setRect(0, 0, w, h)

    def resize_to(self, new_local: QRectF) -> None:
        """Resize = set wrap width; height reflows to content."""
        if new_local.width() <= 0:
            return
        self._wrap_w = new_local.width()
        self.setPos(self.pos() + new_local.topLeft())
        self._reflow()

    def apply_style(self, style: dict) -> None:
        super().apply_style(style)
        self._reflow()

    # -- paint ----------------------------------------------------------

    def paint_content(self, painter) -> None:
        painter.setFont(mm_font(self.font_mm))
        painter.setPen(QPen(QColor(self.stroke), 0))
        flags = _ALIGN[self.align] | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
        painter.drawText(self.rect(), int(flags), self.text)

    # -- serialization ----------------------------------------------------

    def geometry_record(self) -> dict:
        geom = {"x": self.pos().x(), "y": self.pos().y()}
        if self._wrap_w:
            geom["w"] = self._wrap_w
        return geom

    def props_record(self) -> dict:
        return {"text": self.text, "align": self.align}

    @classmethod
    def from_normalized(cls, rec: dict) -> "FreeTextItem":
        g = rec["geometry"]
        item = cls(
            QPointF(g["x"], g["y"]),
            text=rec["props"]["text"],
            wrap_w=g.get("w"),
        )
        item.align = rec["props"]["align"]
        item._init_from_normalized(rec)  # apply_style -> _reflow with final font_mm
        return item
```

`__init__.py` 的 import 块与 `ITEM_CLASSES` 注册追加 `FreeTextItem`:

```python
from geoviz_paleo_map.cartography.items.free.text_item import FreeTextItem

ITEM_CLASSES: dict[str, type[FreeGraphicsItem]] = {
    cls.kind: cls
    for cls in (FreeRectItem, FreeEllipseItem, FreeTextItem)
}
```

并把 `"FreeTextItem"` 加入 `__all__`。

- [ ] **Step 4: 验证通过**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/text_item.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
  tests/paleo_map/test_cartography_free_graphics.py
```

- [ ] **Step 5: 提交**

```bash
cd geo-viz-engine
git add packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/text_item.py \
        packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
        tests/paleo_map/test_cartography_free_graphics.py
git commit -m "feat(cartography): FreeTextItem with mm font + wrap reflow"
```

---

## Task 5: 点类 item — 箭头/多边形/手绘(geo-viz-engine)

三种 points 类 item:arrow(开放折线 + 箭头头)、polygon(闭合填充)、freehand(开放,放置时鼠标拖出)。几何存局部点 + `pos=bbox.topLeft`；`to_record()` 还原为绝对点；resize 时按包围盒仿射映射。

**Files:**
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/line_items.py`
- Modify: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py`
- Test: `geo-viz-engine/tests/paleo_map/test_cartography_free_graphics.py`(追加)

- [ ] **Step 1: 写失败测试(追加)**

```python
# 追加到 geo-viz-engine/tests/paleo_map/test_cartography_free_graphics.py
from geoviz_paleo_map.cartography.items.free.line_items import (
    FreeArrowItem,
    FreePolygonItem,
    FreehandItem,
)


def test_arrow_roundtrip():
    pts = [(10.0, 10.0), (50.0, 10.0)]
    item = FreeArrowItem(pts)
    rec = _roundtrip(item)
    assert rec["kind"] == "arrow"
    assert rec["geometry"]["points"] == [[10.0, 10.0], [50.0, 10.0]]
    assert rec["props"] == {"head_mm": 3.0}


def test_polygon_roundtrip_with_fill():
    pts = [(0.0, 0.0), (40.0, 0.0), (20.0, 30.0)]
    item = FreePolygonItem(pts)
    item.fill = "#00ff00"
    rec = _roundtrip(item)
    assert rec["kind"] == "polygon"
    assert len(rec["geometry"]["points"]) == 3
    assert rec["style"]["fill"] == "#00ff00"


def test_freehand_roundtrip():
    pts = [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0), (30.0, 5.0)]
    item = FreehandItem(pts)
    rec = _roundtrip(item)
    assert rec["kind"] == "freehand"
    assert rec["geometry"]["points"] == [[0.0, 0.0], [10.0, 5.0], [20.0, 0.0], [30.0, 5.0]]


def test_points_items_survive_move():
    item = FreeArrowItem([(10.0, 10.0), (50.0, 10.0)])
    item.setPos(QPointF(30.0, 25.0))
    rec = item.to_record()
    assert rec["geometry"]["points"] == [[40.0, 35.0], [80.0, 35.0]]


def test_points_resize_remaps_bbox():
    # Move bbox top-left by (20, 10) and double its size.
    pts = [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0)]
    item = FreePolygonItem(pts)
    # bbox is (0,0,40,20).  Resize to (0,0,80,40) — scale x2 in both axes.
    item.resize_to(QRectF(0, 0, 80.0, 40.0))
    rec = item.to_record()
    assert rec["geometry"]["points"] == [[0.0, 0.0], [80.0, 0.0], [80.0, 40.0]]


def test_arrow_head_mm_applied():
    item = FreeArrowItem([(0.0, 0.0), (40.0, 0.0)])
    item.apply_style({"stroke": "#ff0000", "fill": None, "width_mm": 0.5, "font_mm": 3.5})
    assert item.width_mm == 0.5


def test_paint_smoke_points_items(qtbot):
    _paint_smoke(FreeArrowItem([(0.0, 0.0), (40.0, 10.0)]))
    _paint_smoke(FreePolygonItem([(0.0, 0.0), (40.0, 0.0), (20.0, 30.0)]))
    _paint_smoke(FreehandItem([(0.0, 0.0), (10.0, 5.0), (20.0, 0.0)]))
```

- [ ] **Step 2: 验证失败**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile tests/paleo_map/test_cartography_free_graphics.py
ls packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/line_items.py 2>&1
```

- [ ] **Step 3: 实现 `line_items.py` + 注册**

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/line_items.py`:

```python
"""Points-kind free graphics: FreeArrowItem, FreePolygonItem, FreehandItem.

Geometry stored as local points + ``pos = bbox.topLeft``; ``to_record``
emits paper-absolute mm points. Resize applies a bounding-box affine map
via :meth:`_remap_content` (spec §3.2): ``p' = p * (new/old)``.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QPolygonF, QRectF

from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem


class _PointsItem(FreeGraphicsItem):
    """Shared backbone for arrow / polygon / freehand."""

    def __init__(self, abs_points: list[tuple[float, float]], parent=None) -> None:
        xs = [p[0] for p in abs_points]
        ys = [p[1] for p in abs_points]
        x0, y0 = min(xs), min(ys)
        w = max(xs) - x0
        h = max(ys) - y0
        super().__init__(QRectF(0, 0, w, h), parent)
        self.setPos(x0, y0)
        self._local_points = [QPointF(px - x0, py - y0) for px, py in abs_points]

    # -- geometry helpers ----------------------------------------------

    def _abs_points(self) -> list[list[float]]:
        p = self.pos()
        return [[pt.x() + p.x(), pt.y() + p.y()] for pt in self._local_points]

    def geometry_record(self) -> dict:
        return {"points": self._abs_points()}

    def _remap_content(self, old: QRectF, new_local: QRectF) -> None:
        if old.width() <= 0 or old.height() <= 0:
            return
        sx = new_local.width() / old.width()
        sy = new_local.height() / old.height()
        self._local_points = [
            QPointF(pt.x() * sx, pt.y() * sy) for pt in self._local_points
        ]

    @classmethod
    def _set_points_from_record(cls, item: "_PointsItem", rec: dict) -> None:
        """Re-init local points from an already-parsed record."""
        pts = rec["geometry"]["points"]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, y0 = min(xs), min(ys)
        item.setPos(x0, y0)
        item._local_points = [QPointF(px - x0, py - y0) for px, py in pts]
        item.setRect(0, 0, max(xs) - x0, max(ys) - y0)


class FreeArrowItem(_PointsItem):
    kind = "arrow"

    def __init__(self, abs_points: list[tuple[float, float]], parent=None) -> None:
        super().__init__(abs_points, parent)
        self.head_mm = 3.0

    def paint_content(self, painter) -> None:
        painter.setPen(self.stroke_pen())
        poly = QPolygonF(self._local_points)
        painter.drawPolyline(poly)
        # Arrowhead on the last segment.
        if len(self._local_points) >= 2:
            p1 = self._local_points[-2]
            p2 = self._local_points[-1]
            self._draw_arrowhead(painter, p1, p2)

    def _draw_arrowhead(self, painter, p1: QPointF, p2: QPointF) -> None:
        dx = p2.x() - p1.x()
        dy = p2.y() - p1.y()
        length = math.hypot(dx, dy)
        if length < 0.001:
            return
        ux, uy = dx / length, dy / length
        head = self.head_mm
        # Two barbs perpendicular to the direction, `head` mm back from tip.
        bx, by = p2.x() - ux * head, p2.y() - uy * head
        px, py = -uy * head * 0.4, ux * head * 0.4
        painter.setBrush(__import__("PySide6.QtGui", fromlist=["QBrush"]).QBrush(
            __import__("PySide6.QtGui", fromlist=["QColor"]).QColor(self.stroke)
        ))
        arrow = QPolygonF([p2, QPointF(bx + px, by + py), QPointF(bx - px, by - py)])
        painter.drawPolygon(arrow)

    def props_record(self) -> dict:
        return {"head_mm": self.head_mm}

    @classmethod
    def from_normalized(cls, rec: dict) -> "FreeArrowItem":
        pts = [tuple(p) for p in rec["geometry"]["points"]]
        item = cls(pts)
        item.head_mm = rec["props"]["head_mm"]
        item._init_from_normalized(rec)
        return item


class FreePolygonItem(_PointsItem):
    kind = "polygon"

    def paint_content(self, painter) -> None:
        painter.setPen(self.stroke_pen())
        painter.setBrush(self.fill_brush())
        painter.drawPolygon(QPolygonF(self._local_points))

    @classmethod
    def from_normalized(cls, rec: dict) -> "FreePolygonItem":
        pts = [tuple(p) for p in rec["geometry"]["points"]]
        item = cls(pts)
        item._init_from_normalized(rec)
        return item


class FreehandItem(_PointsItem):
    kind = "freehand"

    def paint_content(self, painter) -> None:
        painter.setPen(self.stroke_pen())
        painter.drawPolyline(QPolygonF(self._local_points))

    @classmethod
    def from_normalized(cls, rec: dict) -> "FreehandItem":
        pts = [tuple(p) for p in rec["geometry"]["points"]]
        item = cls(pts)
        item._init_from_normalized(rec)
        return item
```

`__init__.py` 追加 import 与注册:

```python
from geoviz_paleo_map.cartography.items.free.line_items import (
    FreeArrowItem,
    FreePolygonItem,
    FreehandItem,
)

ITEM_CLASSES: dict[str, type[FreeGraphicsItem]] = {
    cls.kind: cls
    for cls in (
        FreeRectItem, FreeEllipseItem, FreeTextItem,
        FreeArrowItem, FreePolygonItem, FreehandItem,
    )
}
```

`__all__` 追加 `"FreeArrowItem"`, `"FreePolygonItem"`, `"FreehandItem"`。

- [ ] **Step 4: 验证通过**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/line_items.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
  tests/paleo_map/test_cartography_free_graphics.py
```

- [ ] **Step 5: 提交**

```bash
cd geo-viz-engine
git add packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/line_items.py \
        packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
        tests/paleo_map/test_cartography_free_graphics.py
git commit -m "feat(cartography): arrow/polygon/freehand items with bbox-affine resize"
```

---

## Task 6: 图片 item + 符号 item(指北针/比例尺)(geo-viz-engine)

图片 item 持绝对路径 + 加载像素(不感知工区);指北针/比例尺借鉴既有 `layers/north_arrow.py`、`scale_bar.py` 画法,改造为纸面固定 mm 尺寸。比例尺 `denominator` 与 `w` 共同决定标注文字。

**Files:**
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/image_item.py`
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/symbol_items.py`
- Modify: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py`
- Test: `geo-viz-engine/tests/paleo_map/test_cartography_free_graphics.py`(追加)

- [ ] **Step 1: 写失败测试(追加)**

```python
# 追加到 geo-viz-engine/tests/paleo_map/test_cartography_free_graphics.py
from geoviz_paleo_map.cartography.items.free.image_item import FreeImageItem
from geoviz_paleo_map.cartography.items.free.symbol_items import (
    NorthArrowItem,
    ScaleBarItem,
)


def test_image_roundtrip():
    item = FreeImageItem(QRectF(10.0, 10.0, 30.0, 20.0), path="/abs/logo.png")
    rec = _roundtrip(item)
    assert rec["kind"] == "image"
    assert rec["props"] == {"path": "/abs/logo.png"}
    assert rec["geometry"] == {"x": 10.0, "y": 10.0, "w": 30.0, "h": 20.0}


def test_image_missing_file_placeholder_paint(qtbot):
    item = FreeImageItem(QRectF(0.0, 0.0, 30.0, 20.0), path="/nonexistent/missing.png")
    assert item._pixmap is None
    _paint_smoke(item)  # must not crash; draws placeholder rect + text


def test_image_set_path_reloads():
    from PySide6.QtGui import QPixmap
    pm = QPixmap(4, 3)
    pm.fill(0xFF0000)
    item = FreeImageItem(QRectF(0.0, 0.0, 10.0, 10.0), path="/abs/x.png")
    item.set_pixmap(pm)
    assert item._pixmap is not None and item._pixmap.width() == 4


def test_north_arrow_roundtrip():
    item = NorthArrowItem(QRectF(50.0, 20.0, 15.0, 20.0))
    rec = _roundtrip(item)
    assert rec["kind"] == "north_arrow"
    assert rec["props"] == {}
    assert rec["geometry"] == {"x": 50.0, "y": 20.0, "w": 15.0, "h": 20.0}


def test_scale_bar_roundtrip():
    item = ScaleBarItem(QRectF(10.0, 180.0, 60.0, 10.0), denominator=25000)
    rec = _roundtrip(item)
    assert rec["kind"] == "scale_bar"
    assert rec["props"] == {"denominator": 25000}


def test_scale_bar_default_denominator():
    item = ScaleBarItem(QRectF(10.0, 180.0, 60.0, 10.0))
    assert item.denominator == 5000


def test_paint_smoke_symbols(qtbot):
    _paint_smoke(NorthArrowItem(QRectF(0.0, 0.0, 15.0, 20.0)))
    _paint_smoke(ScaleBarItem(QRectF(0.0, 0.0, 60.0, 10.0)))
```

- [ ] **Step 2: 验证失败**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile tests/paleo_map/test_cartography_free_graphics.py
ls packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/image_item.py \
   packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/symbol_items.py 2>&1
```

- [ ] **Step 3: 实现 `image_item.py` + `symbol_items.py` + 注册**

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/image_item.py`:

```python
"""FreeImageItem — paper image / logo with absolute source path.

The geoviz side only holds the source path and loads pixels; copying the
file into the workspace asset directory is the host's job on save (spec
§4.3). Missing files degrade to a placeholder rectangle + filename.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPen, QPixmap

from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem, mm_font


class FreeImageItem(FreeGraphicsItem):
    kind = "image"

    def __init__(self, rect_scene: QRectF, path: str = "", parent=None) -> None:
        super().__init__(QRectF(0, 0, rect_scene.width(), rect_scene.height()), parent)
        self.setPos(rect_scene.topLeft())
        self.path = path
        self._pixmap: QPixmap | None = None
        self._load_pixmap()

    def _load_pixmap(self) -> None:
        if self.path and os.path.isfile(self.path):
            self._pixmap = QPixmap(self.path)
        else:
            self._pixmap = None

    def set_pixmap(self, pm: QPixmap | None) -> None:
        self._pixmap = pm
        self.update()

    def set_path(self, path: str) -> None:
        self.path = path
        self._load_pixmap()
        self.update()

    def paint_content(self, painter) -> None:
        r = self.rect()
        if self._pixmap is not None and not self._pixmap.isNull():
            painter.drawPixmap(r, self._pixmap)
        else:
            painter.setPen(QPen(QColor("#94a3b8"), 0.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r)
            painter.setPen(QColor("#94a3b8"))
            name = os.path.basename(self.path) if self.path else "(无图片)"
            painter.setFont(mm_font(self.font_mm))
            painter.drawText(r, int(Qt.AlignmentFlag.AlignCenter), name)

    def geometry_record(self) -> dict:
        return self.frame_geometry_record()

    def props_record(self) -> dict:
        return {"path": self.path}

    @classmethod
    def from_normalized(cls, rec: dict) -> "FreeImageItem":
        g = rec["geometry"]
        item = cls(QRectF(g["x"], g["y"], g["w"], g["h"]), path=rec["props"]["path"])
        item._init_from_normalized(rec)
        return item
```

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/symbol_items.py`:

```python
"""NorthArrowItem + ScaleBarItem — paper-fixed cartographic symbols.

Adapted from ``geoviz_paleo_map.layers.north_arrow`` and ``scale_bar``,
but drawn at fixed mm dimensions on the paper instead of dynamic screen
pixels. The scale bar label is derived from ``denominator`` and ``w``.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPen, QPolygonF

from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem, mm_font

_SYMBOL_COLOR = QColor("#334155")


class NorthArrowItem(FreeGraphicsItem):
    kind = "north_arrow"

    def __init__(self, rect_scene: QRectF, parent=None) -> None:
        super().__init__(QRectF(0, 0, rect_scene.width(), rect_scene.height()), parent)
        self.setPos(rect_scene.topLeft())

    def paint_content(self, painter) -> None:
        r = self.rect()
        cx = r.center().x()
        # Triangle occupies top 70% of the item; "N" sits at bottom.
        tri_h = r.height() * 0.7
        half_w = r.width() * 0.3
        polygon = QPolygonF([
            QPointF(cx, r.top()),
            QPointF(cx - half_w, r.top() + tri_h),
            QPointF(cx + half_w, r.top() + tri_h),
        ])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_SYMBOL_COLOR)
        painter.drawPolygon(polygon)
        # "N" label
        painter.setPen(QPen(_SYMBOL_COLOR, 0))
        painter.setFont(mm_font(self.font_mm, bold=True))
        fm = QFontMetricsF(painter.font())
        tw = fm.horizontalAdvance("N")
        painter.drawText(
            QPointF(cx - tw / 2, r.bottom()),
            "N",
        )

    def geometry_record(self) -> dict:
        return self.frame_geometry_record()

    @classmethod
    def from_normalized(cls, rec: dict) -> "NorthArrowItem":
        g = rec["geometry"]
        item = cls(QRectF(g["x"], g["y"], g["w"], g["h"]))
        item._init_from_normalized(rec)
        return item


class ScaleBarItem(FreeGraphicsItem):
    kind = "scale_bar"

    def __init__(self, rect_scene: QRectF, denominator: int = 5000, parent=None) -> None:
        super().__init__(QRectF(0, 0, rect_scene.width(), rect_scene.height()), parent)
        self.setPos(rect_scene.topLeft())
        self.denominator = denominator

    def _label(self) -> str:
        """Ground distance represented by the bar width, in m or km."""
        ground_m = self.rect().width() / 1000.0 * self.denominator
        if ground_m >= 1000:
            return f"{ground_m / 1000:.1f} km  (1:{self.denominator})"
        return f"{ground_m:.0f} m  (1:{self.denominator})"

    def paint_content(self, painter) -> None:
        r = self.rect()
        bar_y = r.top() + r.height() * 0.4
        pen = QPen(_SYMBOL_COLOR, max(0.5, self.width_mm))
        painter.setPen(pen)
        painter.drawLine(QPointF(r.left(), bar_y), QPointF(r.right(), bar_y))
        painter.drawLine(QPointF(r.left(), bar_y - 2.0), QPointF(r.left(), bar_y + 2.0))
        painter.drawLine(QPointF(r.right(), bar_y - 2.0), QPointF(r.right(), bar_y + 2.0))
        # Label beneath
        painter.setPen(QPen(_SYMBOL_COLOR, 0))
        painter.setFont(mm_font(self.font_mm))
        fm = QFontMetricsF(painter.font())
        label = self._label()
        tw = fm.horizontalAdvance(label)
        painter.drawText(QPointF(r.center().x() - tw / 2, r.bottom()), label)

    def geometry_record(self) -> dict:
        return self.frame_geometry_record()

    def props_record(self) -> dict:
        return {"denominator": self.denominator}

    @classmethod
    def from_normalized(cls, rec: dict) -> "ScaleBarItem":
        g = rec["geometry"]
        item = cls(QRectF(g["x"], g["y"], g["w"], g["h"]), denominator=rec["props"]["denominator"])
        item._init_from_normalized(rec)
        return item
```

`__init__.py` 完成全集注册(9 种全部到位):

```python
from geoviz_paleo_map.cartography.items.free.image_item import FreeImageItem
from geoviz_paleo_map.cartography.items.free.symbol_items import NorthArrowItem, ScaleBarItem

ITEM_CLASSES: dict[str, type[FreeGraphicsItem]] = {
    cls.kind: cls
    for cls in (
        FreeRectItem, FreeEllipseItem, FreeTextItem,
        FreeArrowItem, FreePolygonItem, FreehandItem,
        FreeImageItem, NorthArrowItem, ScaleBarItem,
    )
}
```

`__all__` 追加 `"FreeImageItem"`, `"NorthArrowItem"`, `"ScaleBarItem"`。

- [ ] **Step 4: 验证通过**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/image_item.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/symbol_items.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
  tests/paleo_map/test_cartography_free_graphics.py
```

- [ ] **Step 5: 提交**

```bash
cd geo-viz-engine
git add packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/image_item.py \
        packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/symbol_items.py \
        packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
        tests/paleo_map/test_cartography_free_graphics.py
git commit -m "feat(cartography): image/north_arrow/scale_bar items (9-kind free graphics complete)"
```

---

## Task 7: 放置控制器 + 工具模式(geo-viz-engine)

窗口工具栏新增互斥模式组(选择/文本/箭头/矩形/椭圆/多边形/手绘/图片/指北针/比例尺)。放置控制器接管 view 的鼠标事件:点击类单击放置默认尺寸;拖拽类按下-拖动-释放成形;多边形多点连击+双击/Enter 闭合;Esc 回选择模式。图片放置弹 `QFileDialog`。

**Files:**
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/placement.py`
- Modify: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py`
- Test: `geo-viz-engine/tests/paleo_map/test_cartography_placement.py`

- [ ] **Step 1: 写失败测试**

```python
# geo-viz-engine/tests/paleo_map/test_cartography_placement.py
"""Placement controller + window tool-mode smoke tests (Task 7).

Offscreen Qt: we exercise the mode state machine and item creation, not
real mouse pixels. The controller installs as a Qt event filter on the
QGraphicsView.
"""

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt

from geoviz_paleo_map.cartography.items.free import ITEM_CLASSES
from geoviz_paleo_map.cartography.placement import PlacementController
from geoviz_paleo_map.cartography.window import CartographyLayoutWindow


def test_window_has_tool_modes(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    assert win.current_tool_mode() == "select"
    win.set_tool_mode("rect")
    assert win.current_tool_mode() == "rect"


def test_placement_click_mode_creates_item(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    win.set_tool_mode("rect")
    ctrl = win._placement
    ctrl.begin_click(QPointF(30.0, 20.0))
    ctrl.end_click(QPointF(80.0, 60.0))
    free = [it for it in win._scene.items() if hasattr(it, "kind")]
    assert len(free) == 1
    assert free[0].kind == "rect"
    assert free[0].to_record()["geometry"]["x"] == 30.0


def test_placement_text_single_click(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    win.set_tool_mode("text")
    ctrl = win._placement
    ctrl.begin_click(QPointF(20.0, 15.0))
    ctrl.end_click(QPointF(20.0, 15.0))
    free = [it for it in win._scene.items() if hasattr(it, "kind")]
    assert len(free) == 1
    assert free[0].kind == "text"


def test_placement_freehand_drag(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    win.set_tool_mode("freehand")
    ctrl = win._placement
    ctrl.begin_click(QPointF(10.0, 10.0))
    ctrl.add_point(QPointF(20.0, 15.0))
    ctrl.add_point(QPointF(30.0, 10.0))
    ctrl.end_click(QPointF(30.0, 10.0))
    free = [it for it in win._scene.items() if hasattr(it, "kind")]
    assert len(free) == 1
    assert free[0].kind == "freehand"
    assert len(free[0].to_record()["geometry"]["points"]) >= 3


def test_placement_polygon_double_click_closes(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    win.set_tool_mode("polygon")
    ctrl = win._placement
    ctrl.begin_click(QPointF(0.0, 0.0))
    ctrl.add_point(QPointF(40.0, 0.0))
    ctrl.add_point(QPointF(20.0, 30.0))
    ctrl.finish_polygon()
    free = [it for it in win._scene.items() if hasattr(it, "kind")]
    assert len(free) == 1
    assert free[0].kind == "polygon"
    assert len(free[0].to_record()["geometry"]["points"]) == 3


def test_placement_esc_resets_to_select(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    win.set_tool_mode("rect")
    ctrl = win._placement
    ctrl.begin_click(QPointF(10.0, 10.0))
    ctrl.cancel()
    assert win.current_tool_mode() == "select"
    assert len([it for it in win._scene.items() if hasattr(it, "kind")]) == 0


def test_placement_clamps_to_paper(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    win.set_tool_mode("rect")
    ctrl = win._placement
    # Click beyond the paper bottom-right corner.
    paper = win._scene.paper_rect()
    beyond = QPointF(paper.right() + 100, paper.bottom() + 100)
    ctrl.begin_click(QPointF(paper.right() - 50, paper.bottom() - 30))
    ctrl.end_click(beyond)
    free = [it for it in win._scene.items() if hasattr(it, "kind")]
    assert len(free) == 1
    g = free[0].to_record()["geometry"]
    assert g["x"] + g["w"] <= paper.right() + 0.1
    assert g["y"] + g["h"] <= paper.bottom() + 0.1
```

- [ ] **Step 2: 验证失败**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile tests/paleo_map/test_cartography_placement.py
ls packages/geoviz_paleo_map/geoviz_paleo_map/cartography/placement.py 2>&1
grep -n "current_tool_mode\|set_tool_mode\|_placement" \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py || echo "RED: window API missing"
```

- [ ] **Step 3: 实现 `placement.py`**

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/placement.py`:

```python
"""PlacementController — tool-mode state machine for free-graphics placement.

Mode groups (spec §3.3):

* **click-drag box** — rect, ellipse, image, north_arrow, scale_bar:
  press → drag (live preview) → release creates the item.
* **single-click** — text, (image when no drag): one click drops a
  default-size item.
* **freehand** — press → move (accumulate points) → release finalises.
* **polygon** — click to add vertices, double-click / Enter to close.
* **select** — default; the bare QGraphicsView selection/move/resize path.

The controller owns no UI; the window wires tool-bar buttons to
:meth:`set_mode` and routes view mouse / key events to the controller's
``begin_click`` / ``add_point`` / ``end_click`` / ``finish_polygon`` /
``cancel`` methods. All coordinates are scene (paper-absolute mm) units.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF

from geoviz_paleo_map.cartography.items.free import ITEM_CLASSES
from geoviz_paleo_map.cartography.items.free.image_item import FreeImageItem
from geoviz_paleo_map.cartography.items.free.text_item import FreeTextItem

CLICK_BOX_KINDS = ("rect", "ellipse", "north_arrow", "scale_bar")
DEFAULT_BOX_W = 40.0
DEFAULT_BOX_H = 20.0


class PlacementController:
    """Mode-driven placement state machine (no Qt widget of its own)."""

    def __init__(self, scene, parent_window=None) -> None:
        self._scene = scene
        self._win = parent_window
        self._mode = "select"
        self._active = False
        self._points: list[QPointF] = []

    # -- mode -----------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self.cancel()
        self._mode = mode

    # -- click protocol (called by the window's eventFilter) -----------

    def begin_click(self, scene_pos: QPointF) -> None:
        if self._mode == "select":
            return
        self._active = True
        self._points = [self._clamp(scene_pos)]
        if self._mode in ("rect", "ellipse", "north_arrow", "scale_bar"):
            # box: wait for drag end; nothing added yet
            return
        if self._mode == "text":
            self._place_text(self._clamp(scene_pos))
            self._finish_active()
            return
        if self._mode == "image":
            self._place_image(self._clamp(scene_pos))
            self._finish_active()
            return
        if self._mode == "freehand":
            return  # accumulate on add_point
        if self._mode == "polygon":
            return  # accumulate on add_point

    def add_point(self, scene_pos: QPointF) -> None:
        if not self._active:
            return
        p = self._clamp(scene_pos)
        if self._mode == "freehand":
            self._points.append(p)
        elif self._mode == "polygon":
            self._points.append(p)

    def end_click(self, scene_pos: QPointF) -> None:
        if not self._active:
            return
        if self._mode in CLICK_BOX_KINDS:
            start = self._points[0]
            end = self._clamp(scene_pos)
            rect = QRectF(start, end).normalized()
            if rect.width() < 2.0 or rect.height() < 2.0:
                # treated as a click: default-size box at the click point
                rect = QRectF(start.x(), start.y(), DEFAULT_BOX_W, DEFAULT_BOX_H)
            self._place_box(rect)
            self._finish_active()
        elif self._mode == "freehand":
            if len(self._points) >= 2:
                self._place_points("freehand")
            self._finish_active()
        elif self._mode == "polygon":
            pass  # polygon waits for finish_polygon() on double-click / Enter

    def finish_polygon(self) -> None:
        if not self._active or self._mode != "polygon":
            return
        if len(self._points) >= 3:
            self._place_points("polygon")
        self._finish_active()

    def cancel(self) -> None:
        self._active = False
        self._points = []

    # -- helpers --------------------------------------------------------

    def _finish_active(self) -> None:
        self._active = False
        self._points = []
        # Auto-return to select after each placement.
        if self._win is not None:
            self._win.set_tool_mode("select")

    def _clamp(self, pos: QPointF) -> QPointF:
        paper = self._scene.paper_rect()
        x = max(paper.left(), min(pos.x(), paper.right()))
        y = max(paper.top(), min(pos.y(), paper.bottom()))
        return QPointF(x, y)

    def _clamp_rect(self, rect: QRectF) -> QRectF:
        paper = self._scene.paper_rect()
        x = max(paper.left(), rect.x())
        y = max(paper.top(), rect.y())
        w = min(rect.width(), paper.right() - x)
        h = min(rect.height(), paper.bottom() - y)
        return QRectF(x, y, max(2.0, w), max(2.0, h))

    def _place_box(self, rect: QRectF) -> None:
        rect = self._clamp_rect(rect)
        cls = ITEM_CLASSES[self._mode]
        item = cls(rect)
        self._scene.addItem(item)
        self._scene.clearSelection()
        item.setSelected(True)

    def _place_text(self, pos: QPointF) -> None:
        item = FreeTextItem(pos, text="文本")
        self._scene.addItem(item)
        self._scene.clearSelection()
        item.setSelected(True)

    def _place_image(self, pos: QPointF) -> None:
        # Window handles the QFileDialog; if it returns None (cancelled or
        # local test), we create a placeholder at the click point.
        path = ""
        if self._win is not None:
            path = self._win._pick_image_path()
        rect = QRectF(pos.x(), pos.y(), DEFAULT_BOX_W, DEFAULT_BOX_H)
        item = FreeImageItem(rect, path=path)
        self._scene.addItem(item)
        self._scene.clearSelection()
        item.setSelected(True)

    def _place_points(self, kind: str) -> None:
        cls = ITEM_CLASSES[kind]
        pts = [(p.x(), p.y()) for p in self._points]
        item = cls(pts)
        self._scene.addItem(item)
        self._scene.clearSelection()
        item.setSelected(True)
```

- [ ] **Step 4: 修改 `window.py` —— 加工具模式 + 放置控制器接线**

在 `CartographyLayoutWindow.__init__` 的 `self._build_toolbar()` 之后追加:

```python
        # Placement controller for free graphics (Task 7).
        from geoviz_paleo_map.cartography.placement import PlacementController
        self._placement = PlacementController(self._scene, parent_window=self)
        self._tool_mode = "select"
        self._build_free_toolbar()
        # Route view events to the placement controller.
        self._view.installEventFilter(self)
```

在类末尾(与 `_build_toolbar` 同级)追加新方法:

```python
    # -- free-graphics tool bar + placement (Task 7) -------------------

    _TOOL_MODES = (
        ("select", "选择"),
        ("text", "文本"),
        ("arrow", "箭头"),
        ("rect", "矩形"),
        ("ellipse", "椭圆"),
        ("polygon", "多边形"),
        ("freehand", "手绘"),
        ("image", "图片"),
        ("north_arrow", "指北针"),
        ("scale_bar", "比例尺"),
    )

    def _build_free_toolbar(self) -> None:
        tb = self.addToolBar("Free Graphics")
        tb.addWidget(QLabel(" 工具："))
        self._tool_combo = QComboBox()
        for mode_id, label in self._TOOL_MODES:
            self._tool_combo.addItem(label, mode_id)
        self._tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        tb.addWidget(self._tool_combo)

    def _on_tool_changed(self) -> None:
        mode = self._tool_combo.currentData()
        self.set_tool_mode(mode)

    def current_tool_mode(self) -> str:
        return self._tool_mode

    def set_tool_mode(self, mode: str) -> None:
        self._tool_mode = mode
        self._placement.set_mode(mode)
        idx = next(
            (i for i, (m, _) in enumerate(self._TOOL_MODES) if m == mode), 0
        )
        self._tool_combo.blockSignals(True)
        self._tool_combo.setCurrentIndex(idx)
        self._tool_combo.blockSignals(False)
        # In placement mode the view must not steal clicks for selection.
        for item in self._scene.items():
            item.setFlag(
                item.GraphicsItemFlag.ItemIsMovable, mode == "select"
            )

    def _pick_image_path(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.svg)"
        )
        return path or ""

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QGraphicsView
        if obj is not self._view:
            return False
        et = event.type()
        ctrl = self._placement
        if ctrl.mode == "select":
            return False
        if et == QEvent.Type.GraphicsSceneMousePress:
            vp = event.widget() if hasattr(event, "widget") else None
            pos = self._view.mapToScene(event.pos()) if hasattr(event, "pos") else None
            if pos is not None:
                ctrl.begin_click(pos)
                return True
        elif et == QEvent.Type.GraphicsSceneMouseMove:
            pos = self._view.mapToScene(event.pos()) if hasattr(event, "pos") else None
            if pos is not None:
                ctrl.add_point(pos)
                return True
        elif et == QEvent.Type.GraphicsSceneMouseRelease:
            pos = self._view.mapToScene(event.pos()) if hasattr(event, "pos") else None
            if pos is not None:
                ctrl.end_click(pos)
                return True
        elif et == QEvent.Type.GraphicsSceneMouseDoubleClick:
            ctrl.finish_polygon()
            return True
        return False

    def keyPressEvent(self, event) -> None:
        from PySide6.QtCore import Qt
        if event.key() == Qt.Key.Key_Escape:
            self._placement.cancel()
            self.set_tool_mode("select")
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._placement.finish_polygon()
            return
        super().keyPressEvent(event)
```

在文件顶部 import 中追加 `QComboBox`(已有)和 `QFileDialog`(已有),无需改 import 行。

- [ ] **Step 5: 验证通过**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/placement.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py \
  tests/paleo_map/test_cartography_placement.py
grep -n "current_tool_mode\|set_tool_mode\|_placement\|eventFilter" \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py | head -6
```

- [ ] **Step 6: 提交**

```bash
cd geo-viz-engine
git add packages/geoviz_paleo_map/geoviz_paleo_map/cartography/placement.py \
        packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py \
        tests/paleo_map/test_cartography_placement.py
git commit -m "feat(cartography): tool-mode placement controller (click/drag/freehand/polygon + Esc)"
```

---

## Task 8: 属性面板 + 删除(geo-viz-engine)

sidebar 新增"选中项属性"区:`QFormLayout` + `QLineEdit`(文本/颜色 hex)/ `QDoubleSpinBox`(线宽/字号/比例尺分母)/ `QComboBox`(对齐)。场景选中变化 → 面板刷新;编辑 → 即时写回 item。Del 键删除选中项。

**Files:**
- Create: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/properties.py`
- Modify: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py`
- Test: `geo-viz-engine/tests/paleo_map/test_cartography_properties.py`

- [ ] **Step 1: 写失败测试**

```python
# geo-viz-engine/tests/paleo_map/test_cartography_properties.py
"""Property panel + delete-key behaviour (Task 8)."""

from PySide6.QtCore import QPointF, QRectF, Qt

from geoviz_paleo_map.cartography.items.free.box_items import FreeRectItem
from geoviz_paleo_map.cartography.window import CartographyLayoutWindow


def test_property_panel_reflects_selection(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    item = FreeRectItem(QRectF(10.0, 10.0, 40.0, 20.0))
    win._scene.addItem(item)
    win._scene.clearSelection()
    item.setSelected(True)
    panel = win._property_panel
    panel.refresh_from_selection()
    assert panel._stroke_edit.text() == "#000000"
    assert panel._width_spin.value() == 0.3


def test_property_panel_edits_write_back(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    item = FreeRectItem(QRectF(10.0, 10.0, 40.0, 20.0))
    win._scene.addItem(item)
    item.setSelected(True)
    panel = win._property_panel
    panel.refresh_from_selection()
    panel._stroke_edit.setText("#ff0000")
    panel._apply_stroke()
    assert item.stroke == "#ff0000"
    panel._width_spin.setValue(1.5)
    panel._apply_width()
    assert item.width_mm == 1.5


def test_delete_key_removes_selected(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    item = FreeRectItem(QRectF(10.0, 10.0, 40.0, 20.0))
    win._scene.addItem(item)
    item.setSelected(True)
    win.set_tool_mode("select")
    # Simulate Del key.
    from PySide6.QtGui import QKeyEvent
    ev = QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier
    )
    win.keyPressEvent(ev)
    assert item.scene() is None  # removed


def test_property_panel_empty_when_no_selection(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    panel = win._property_panel
    panel.refresh_from_selection()
    assert not panel.isEnabled()
```

- [ ] **Step 2: 验证失败**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile tests/paleo_map/test_cartography_properties.py
ls packages/geoviz_paleo_map/geoviz_paleo_map/cartography/properties.py 2>&1
grep -n "_property_panel" packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py || echo "RED"
```

- [ ] **Step 3: 实现 `properties.py`**

`geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/properties.py`:

```python
"""PropertyPanel — sidebar form for the currently-selected free graphic.

Wires ``QFormLayout`` editors (stroke/fill hex, line-width mm, font mm,
text, align, scale-bar denominator) to the selected ``FreeGraphicsItem``.
The window refreshes the panel on ``selectionChanged``; each editor
signal writes back to the item immediately (spec §3.4).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QWidget,
)

from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem


class PropertyPanel(QWidget):
    """Form that edits the single selected free graphic."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._item: FreeGraphicsItem | None = None
        form = QFormLayout(self)
        form.setContentsMargins(4, 4, 4, 4)

        self._stroke_edit = QLineEdit()
        form.addRow("描边色", self._stroke_edit)
        self._fill_edit = QLineEdit()
        form.addRow("填充色", self._fill_edit)
        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(0.1, 20.0)
        self._width_spin.setSingleStep(0.1)
        self._width_spin.setSuffix(" mm")
        form.addRow("线宽", self._width_spin)
        self._font_spin = QDoubleSpinBox()
        self._font_spin.setRange(1.0, 50.0)
        self._font_spin.setSingleStep(0.5)
        self._font_spin.setSuffix(" mm")
        form.addRow("字号", self._font_spin)
        self._text_edit = QLineEdit()
        form.addRow("文本", self._text_edit)
        self._align_combo = QComboBox()
        self._align_combo.addItems(["left", "center", "right"])
        form.addRow("对齐", self._align_combo)
        self._denom_spin = QDoubleSpinBox()
        self._denom_spin.setRange(1, 10_000_000)
        self._denom_spin.setDecimals(0)
        form.addRow("比例尺分母", self._denom_spin)

        self._stroke_edit.editingFinished.connect(self._apply_stroke)
        self._fill_edit.editingFinished.connect(self._apply_fill)
        self._width_spin.valueChanged.connect(self._apply_width)
        self._font_spin.valueChanged.connect(self._apply_font)
        self._text_edit.editingFinished.connect(self._apply_text)
        self._align_combo.currentIndexChanged.connect(self._apply_align)
        self._denom_spin.valueChanged.connect(self._apply_denominator)
        self.setEnabled(False)

    # -- refresh --------------------------------------------------------

    def refresh_from_selection(self) -> None:
        from PySide6.QtWidgets import QGraphicsScene
        scene = self.parent() if isinstance(self.parent(), QGraphicsScene) else None
        # The window calls set_item directly; this fallback is a safety net.
        self.set_item(None)

    def set_item(self, item: FreeGraphicsItem | None) -> None:
        self._item = item
        if item is None:
            self.setEnabled(False)
            return
        self.setEnabled(True)
        self._stroke_edit.setText(item.stroke)
        self._fill_edit.setText(item.fill or "")
        self._width_spin.blockSignals(True)
        self._width_spin.setValue(item.width_mm)
        self._width_spin.blockSignals(False)
        self._font_spin.blockSignals(True)
        self._font_spin.setValue(item.font_mm)
        self._font_spin.blockSignals(False)
        text = getattr(item, "text", "")
        self._text_edit.setText(text)
        align = getattr(item, "align", "left")
        idx = self._align_combo.findText(align)
        self._align_combo.blockSignals(True)
        self._align_combo.setCurrentIndex(max(0, idx))
        self._align_combo.blockSignals(False)
        denom = getattr(item, "denominator", 0)
        if denom:
            self._denom_spin.blockSignals(True)
            self._denom_spin.setValue(float(denom))
            self._denom_spin.blockSignals(False)

    # -- write-back -----------------------------------------------------

    def _current_style(self) -> dict:
        item = self._item
        return {
            "stroke": item.stroke,
            "fill": item.fill,
            "width_mm": item.width_mm,
            "font_mm": item.font_mm,
        }

    def _apply_stroke(self) -> None:
        if self._item is None:
            return
        self._item.stroke = self._stroke_edit.text()
        self._item.update()

    def _apply_fill(self) -> None:
        if self._item is None:
            return
        txt = self._fill_edit.text().strip()
        self._item.fill = txt or None
        self._item.update()

    def _apply_width(self) -> None:
        if self._item is None:
            return
        self._item.apply_style({**self._current_style(), "width_mm": self._width_spin.value()})

    def _apply_font(self) -> None:
        if self._item is None:
            return
        self._item.apply_style({**self._current_style(), "font_mm": self._font_spin.value()})

    def _apply_text(self) -> None:
        if self._item is not None and hasattr(self._item, "text"):
            self._item.text = self._text_edit.text()
            if hasattr(self._item, "_reflow"):
                self._item._reflow()
            self._item.update()

    def _apply_align(self) -> None:
        if self._item is not None and hasattr(self._item, "align"):
            self._item.align = self._align_combo.currentText()
            self._item.update()

    def _apply_denominator(self) -> None:
        if self._item is not None and hasattr(self._item, "denominator"):
            self._item.denominator = int(self._denom_spin.value())
            self._item.update()
```

- [ ] **Step 4: 修改 `window.py` —— 集成属性面板 + 选中刷新 + Del 删除**

在 `__init__` 的 `self._build_free_toolbar()` 之后、`self._view.installEventFilter(self)` 之后追加:

```python
        # Property panel in the sidebar (Task 8).
        from geoviz_paleo_map.cartography.properties import PropertyPanel
        self._property_panel = PropertyPanel()
        # Insert into the existing sidebar (built by _build_sidebar).
        sidebar_layout: QVBoxLayout = self._sidebar_layout
        sidebar_layout.insertWidget(sidebar_layout.count() - 1, self._property_panel)  # before stretch
        self._scene.selectionChanged.connect(self._on_selection_changed)
```

在 `_build_sidebar` 中,把 `s_layout` 存为 `self._sidebar_layout = s_layout`(加一行),使属性面板可动态插入。

在类中追加选中处理 + Del 键:

```python
    def _on_selection_changed(self) -> None:
        from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem
        free_items = [
            it for it in self._scene.selectedItems()
            if isinstance(it, FreeGraphicsItem)
        ]
        self._property_panel.set_item(free_items[0] if free_items else None)
```

在 `keyPressEvent` 中(已有 Task 7 的 Esc/Enter 分支)追加 Del 分支:

```python
        if event.key() == Qt.Key.Key_Delete:
            for it in list(self._scene.selectedItems()):
                self._scene.removeItem(it)
            return
```

- [ ] **Step 5: 验证通过**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/properties.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py \
  tests/paleo_map/test_cartography_properties.py
```

- [ ] **Step 6: 提交**

```bash
cd geo-viz-engine
git add packages/geoviz_paleo_map/geoviz_paleo_map/cartography/properties.py \
        packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py \
        tests/paleo_map/test_cartography_properties.py
git commit -m "feat(cartography): property panel sidebar + Del-key delete for free graphics"
```

---

## Task 9: `CartographyLayoutWindow` 公开 API(geo-viz-engine)

新增四个公开方法: `add_free_graphic`/`free_graphics`/`remove_free_graphic`/`panels`。取代宿主对 `win._view`/`window._scene` 的私有属性访问(规格 §3.6)。

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py`
- Test: `geo-viz-engine/tests/paleo_map/test_cartography_window_api.py`

- [ ] **Step 1: 写失败测试**

```python
# geo-viz-engine/tests/paleo_map/test_cartography_window_api.py
"""CartographyLayoutWindow public API for free graphics + panel read-back (Task 9)."""

from PySide6.QtCore import QRectF

from geoviz_paleo_map.cartography.window import CartographyLayoutWindow


def test_add_free_graphic_returns_id(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    rec = {
        "kind": "rect",
        "geometry": {"x": 20.0, "y": 20.0, "w": 40.0, "h": 20.0},
    }
    item_id = win.add_free_graphic(rec)
    assert item_id is not None
    assert len(win.free_graphics()) == 1
    assert win.free_graphics()[0]["id"] == item_id


def test_add_free_graphic_rejects_bad_record(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    assert win.add_free_graphic({"kind": "blob"}) is None
    assert win.add_free_graphic("not-a-dict") is None
    assert len(win.free_graphics()) == 0


def test_remove_free_graphic(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    item_id = win.add_free_graphic(
        {"kind": "rect", "geometry": {"x": 10.0, "y": 10.0, "w": 30.0, "h": 15.0}}
    )
    assert item_id is not None
    assert win.remove_free_graphic(item_id) is True
    assert len(win.free_graphics()) == 0
    assert win.remove_free_graphic("nonexistent") is False


def test_free_graphics_excludes_panels(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    win.set_plot_sources(["p1"])
    win.add_figure_panel("p1")
    win.add_free_graphic({"kind": "text", "geometry": {"x": 5.0, "y": 5.0}, "props": {"text": "X"}})
    recs = win.free_graphics()
    assert len(recs) == 1
    assert recs[0]["kind"] == "text"


def test_panels_read_back(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    win.set_plot_sources(["p1"])
    win.add_figure_panel("p1", source_plot_type="section", render_mode="snapshot")
    panels = win.panels()
    assert len(panels) == 1
    p = panels[0]
    assert p["plot_id"] == "p1"
    assert p["source_plot_type"] == "section"
    assert p["render_mode"] == "snapshot"
    assert "rect_mm" in p and len(p["rect_mm"]) == 4


def test_panels_empty(qtbot):
    win = CartographyLayoutWindow()
    qtbot.addWidget(win)
    assert win.panels() == []
```

- [ ] **Step 2: 验证失败**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile tests/paleo_map/test_cartography_window_api.py
grep -n "def add_free_graphic\|def free_graphics\|def remove_free_graphic\|def panels" \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py || echo "RED: API missing"
```

- [ ] **Step 3: 实现 —— 在 `window.py` 的 `figure_panels` 方法之后追加四个公开方法**

```python
    # -- free-graphics public API (spec §3.6, Task 9) ------------------

    def add_free_graphic(self, record: dict) -> str | None:
        """Validate ``record`` and add the item to the scene.

        Returns the item id on success, None when the record is unknown /
        malformed (host counts and reports these). Unknown kinds are
        silently skipped — the host reports a count to the user.
        """
        from geoviz_paleo_map.cartography.items.free import item_from_record
        item = item_from_record(record)
        if item is None:
            return None
        self._scene.addItem(item)
        return item.id

    def free_graphics(self) -> list[dict]:
        """Return ``to_record()`` dicts for every free graphic on the paper."""
        from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem
        return [
            it.to_record()
            for it in self._scene.items()
            if isinstance(it, FreeGraphicsItem)
        ]

    def remove_free_graphic(self, item_id: str) -> bool:
        """Remove the free graphic with ``item_id``; True when found."""
        from geoviz_paleo_map.cartography.items.free.base import FreeGraphicsItem
        for it in list(self._scene.items()):
            if isinstance(it, FreeGraphicsItem) and it.id == item_id:
                self._scene.removeItem(it)
                return True
        return False

    def panels(self) -> list[dict]:
        """Read back panel geometry as plain dicts for host persistence.

        Each dict: ``{plot_id, slot, source_plot_type, rect_mm, render_mode}``.
        """
        result = []
        for panel in self.figure_panels():
            r = panel.rect()
            p = panel.pos()
            result.append({
                "plot_id": panel.source_plot_id,
                "slot": "main",
                "source_plot_type": panel.source_plot_type,
                "rect_mm": [
                    round(p.x() + r.x(), 2),
                    round(p.y() + r.y(), 2),
                    round(r.width(), 2),
                    round(r.height(), 2),
                ],
                "render_mode": panel.render_mode,
            })
        return result
```

- [ ] **Step 4: 验证通过**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py \
  tests/paleo_map/test_cartography_window_api.py
grep -c "def add_free_graphic\|def free_graphics\|def remove_free_graphic\|def panels" \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py  # 预期 >= 4
```

- [ ] **Step 5: 提交**

```bash
cd geo-viz-engine
git add packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py \
        tests/paleo_map/test_cartography_window_api.py
git commit -m "feat(cartography): public window API — add/free/remove_free_graphic + panels read-back"
```

---

## Task 10: PR-A push + PR(geo-viz-engine)

把 `feat/cartography-free-graphics` 分支推上,开 PR。**不等 CI**(用户指示)。

- [ ] **Step 1: 全量 py_compile 终检**

```bash
cd geo-viz-engine && /usr/bin/python3 -m py_compile \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/__init__.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/records.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/base.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/box_items.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/text_item.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/line_items.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/image_item.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/symbol_items.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/placement.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/properties.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/base_item.py \
  packages/geoviz_paleo_map/geoviz_paleo_map/cartography/window.py \
  tests/paleo_map/test_cartography_free_records.py \
  tests/paleo_map/test_cartography_free_graphics.py \
  tests/paleo_map/test_cartography_resize.py \
  tests/paleo_map/test_cartography_placement.py \
  tests/paleo_map/test_cartography_properties.py \
  tests/paleo_map/test_cartography_window_api.py
```

- [ ] **Step 2: 纯 Python 契约回归**

```bash
cd geo-viz-engine && /usr/bin/python3 - <<'EOF'
import importlib.util
from pathlib import Path
p = Path("packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/records.py")
spec = importlib.util.spec_from_file_location("free_records", p)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
for kind, geom, props in [
    ("rect", {"x":1.0,"y":1.0,"w":2.0,"h":2.0}, {}),
    ("ellipse", {"x":1.0,"y":1.0,"w":2.0,"h":2.0}, {}),
    ("text", {"x":20.0,"y":15.0}, {"text":"Hi"}),
    ("arrow", {"points":[[0.0,0.0],[4.0,0.0]]}, {}),
    ("polygon", {"points":[[0.0,0.0],[4.0,0.0],[2.0,3.0]]}, {}),
    ("freehand", {"points":[[0.0,0.0],[4.0,4.0]]}, {}),
    ("image", {"x":1.0,"y":1.0,"w":2.0,"h":2.0}, {"path":"plots/assets/p/a.png"}),
    ("north_arrow", {"x":1.0,"y":1.0,"w":2.0,"h":2.0}, {}),
    ("scale_bar", {"x":1.0,"y":1.0,"w":50.0,"h":9.0}, {}),
]:
    rec = r.parse_record({"kind": kind, "geometry": geom, "props": props})
    assert rec is not None, f"{kind} failed"
    assert rec["kind"] == kind
assert r.parse_record({"kind": "blob"}) is None
print("All 9 kinds pass contract validation")
EOF
```

- [ ] **Step 3: push + 开 PR**

```bash
cd geo-viz-engine
git log --oneline feat/cartography-free-graphics ^main | head -10
git push -u origin feat/cartography-free-graphics
gh pr create --title "feat(cartography): free-graphics system (9 kinds + placement + property panel + window API)" \
  --body "Implements spec §3.5 / `docs/superpowers/specs/2026-08-04-composite-free-graphics-design.md` (PR-A).

**Contents:**
- Task 1: ``records.py`` — frozen cross-repo record contract (pure Python, no Qt)
- Task 2: real resize handles on ``LayoutGraphicsItem`` (hit test + resize_to + remap hook)
- Task 3: ``FreeGraphicsItem`` base + rect/ellipse
- Task 4: ``FreeTextItem`` (mm font + wrap reflow)
- Task 5: arrow/polygon/freehand (bbox-affine resize)
- Task 6: image/north_arrow/scale_bar (9 kinds complete)
- Task 7: tool-mode placement controller (click/drag/freehand/polygon + Esc)
- Task 8: property panel sidebar + Del-key delete
- Task 9: public window API (add/free/remove_free_graphic + panels read-back)

Follow-up PR-B bumps the gitlink in the parent repo."
```

- [ ] **Step 4: 记下引擎 PR 号**(PR-B Task 13 需要)

```bash
cd geo-viz-engine && gh pr list --head feat/cartography-free-graphics --json number,title -q '.[0].number'
```

---

## Task 11: schema v4 — `free_graphics` 字段(paleo-workbench 父仓)

`PlotDocument` 新增 `free_graphics: list[dict]`;`PLOT_SCHEMA_VERSION = 4`;升级链追加 `version == 3` 分支。**先不切分支** —— Task 11-13 在父仓 `main` 上新建分支 `feat/composite-free-graphics-host`。

**Files:**
- Modify: `well-log-engine/apps/wellplot-desktop/well_log_workstation/plot_document.py`
- Test: `well-log-engine/apps/wellplot-desktop/tests/test_well_log_workstation_plot_free_graphics.py`

- [ ] **Step 1: 确认当前分支 + 建分支**

```bash
cd /home/kevin/projects/paleo_project
git checkout main
git checkout -b feat/composite-free-graphics-host
```

- [ ] **Step 2: 写失败测试**

```python
# well-log-engine/apps/wellplot-desktop/tests/test_well_log_workstation_plot_free_graphics.py
"""Schema v4 free_graphics persistence (spec §4.1).

Mirrors the pattern of ``well-log-engine/apps/wellplot-desktop/tests/test_well_log_workstation_plot_revision.py``:
``_from_json``/``_to_json`` are pure Python and verifiable without PySide6
(events.py is lazily imported by save/load, so the pure branches stay
importable for ``/usr/bin/python3``).
"""

from __future__ import annotations

import json
from pathlib import Path


def _workspace_with_well(tmp_path: Path):
    from well_log_workstation.workspace import add_well, create_workspace

    ws = create_workspace(tmp_path / "ws")
    well = add_well(ws, name="W1", path="wells/w1.las", well_id="well-fixed")
    return ws, well


def test_schema_version_is_4():
    from well_log_workstation.plot_document import PLOT_SCHEMA_VERSION
    assert PLOT_SCHEMA_VERSION == 4


def test_v3_file_upgrades_with_empty_free_graphics(tmp_path: Path):
    from well_log_workstation.plot_document import _from_json

    data = {
        "schemaVersion": 3,
        "id": "old-plot",
        "name": "Old",
        "type": "composite",
        "well_ids": [],
        "template_id": None,
        "revision": 1,
        "panels": [
            {"plot_id": "p1", "slot": "main", "source_plot_type": "single_well",
             "rect_mm": [10.0, 10.0, 40.0, 20.0], "render_mode": "live"},
        ],
    }
    doc = _from_json(data, path="plots/old-plot.json")
    assert doc.free_graphics == []
    assert doc.panels[0].plot_id == "p1"


def test_to_json_writes_free_graphics_for_composite(tmp_path: Path):
    from well_log_workstation.plot_document import _to_json, PlotDocument

    doc = PlotDocument(
        id="c1", name="C", type="composite", well_ids=[], template_id=None,
        path="plots/c1.json",
        free_graphics=[
            {"id": "u1", "kind": "rect",
             "style": {"stroke": "#000000", "fill": None, "width_mm": 0.3, "font_mm": 3.5},
             "geometry": {"x": 10.0, "y": 10.0, "w": 40.0, "h": 20.0},
             "props": {}},
        ],
    )
    payload = _to_json(doc)
    assert payload["schemaVersion"] == 4
    assert len(payload["free_graphics"]) == 1
    assert payload["free_graphics"][0]["kind"] == "rect"


def test_to_json_omits_free_graphics_when_empty_non_composite(tmp_path: Path):
    from well_log_workstation.plot_document import _to_json, PlotDocument

    doc = PlotDocument(
        id="s1", name="S", type="single_well", well_ids=["w1"],
        template_id="t1", path="plots/s1.json",
    )
    payload = _to_json(doc)
    assert "free_graphics" not in payload


def test_save_persists_free_graphics_schema_v4(tmp_path: Path):
    from well_log_workstation.events import reset_revisions
    from well_log_workstation.plot_document import (
        create_composite_plot, save_plot_document, PanelRef,
    )
    from well_log_workstation.workspace import create_workspace

    reset_revisions()
    ws = create_workspace(tmp_path / "ws")
    doc = create_composite_plot(
        ws, panels=[PanelRef(plot_id="p1")], template_id="tpl",
    )
    doc.free_graphics = [
        {"id": "u1", "kind": "text",
         "style": {"stroke": "#000000", "fill": None, "width_mm": 0.3, "font_mm": 3.5},
         "geometry": {"x": 5.0, "y": 5.0},
         "props": {"text": "注解", "align": "left"}},
    ]
    save_plot_document(ws, doc)
    data = json.loads((ws.root / doc.path).read_text(encoding="utf-8"))
    assert data["schemaVersion"] == 4
    assert len(data["free_graphics"]) == 1
    assert data["free_graphics"][0]["kind"] == "text"
```

- [ ] **Step 3: 验证失败**

```bash
/usr/bin/python3 -m py_compile well-log-engine/apps/wellplot-desktop/tests/test_well_log_workstation_plot_free_graphics.py
/usr/bin/python3 -c "from well_log_workstation.plot_document import PLOT_SCHEMA_VERSION; print(PLOT_SCHEMA_VERSION)"
# 预期输出 3(红:应为 4)
```

- [ ] **Step 4: 实现 —— 修改 `plot_document.py`**

**(a)** `PLOT_SCHEMA_VERSION = 4`(改第 24 行的 `3` → `4`)。

**(b)** `PlotDocument` 新增字段(在 `revision` 之后):

```python
    # Per-plot revision, persisted in plots/<id>.json (schema v3, ADR 0051).
    revision: int = 0
    # Free-graphics records for composite plots (schema v4, spec §4.1).
    # Kind-discriminated dicts validated at the geoviz ``from_record``
    # boundary; the host stores them opaquely (PanelRef precedent).
    free_graphics: list[dict] = field(default_factory=list)
```

**(c)** `_to_json` 新增 `free_graphics` 写入(在 `payload["revision"] = ...` 之后):

```python
    if doc.type == "composite" or doc.free_graphics:
        payload["free_graphics"] = list(doc.free_graphics)
```

**(d)** `_from_json` 升级链(在 `version == 2` 分支之后追加 `version == 3` 分支):

```python
    if version == 3:
        # v3 -> v4 additive: free_graphics is new and defaults to empty.
        data = dict(data)
        data.setdefault("free_graphics", [])
        version = PLOT_SCHEMA_VERSION
```

**(e)** `_from_json` 解析(在 `panels` 解析之后,`return PlotDocument(...)` 之前):

```python
    free_graphics: list[dict] = []
    for raw in data.get("free_graphics") or []:
        if isinstance(raw, dict):
            free_graphics.append(raw)
```

**(f)** `return PlotDocument(...)` 新增 `free_graphics=free_graphics,`。同时修复 id-mismatch rebuild 路径(`load_plot_document` 内):在那个 `PlotDocument(...)` 构造中也加 `free_graphics=list(doc.free_graphics),`。

- [ ] **Step 5: 验证通过**

```bash
/usr/bin/python3 -m py_compile well-log-engine/apps/wellplot-desktop/well_log_workstation/plot_document.py
/usr/bin/python3 -c "
from well_log_workstation.plot_document import PLOT_SCHEMA_VERSION, _from_json, _to_json, PlotDocument
assert PLOT_SCHEMA_VERSION == 4
# v3 upgrade
d = _from_json({'schemaVersion':3,'id':'x','name':'X','type':'composite','well_ids':[],'template_id':None,'revision':1}, path='plots/x.json')
assert d.free_graphics == []
# v4 round-trip
doc = PlotDocument(id='c1',name='C',type='composite',well_ids=[],template_id=None,path='plots/c1.json',free_graphics=[{'kind':'rect','geometry':{'x':1.0,'y':1.0,'w':2.0,'h':2.0}}])
p = _to_json(doc)
assert p['schemaVersion']==4 and len(p['free_graphics'])==1
# empty non-composite omits
doc2 = PlotDocument(id='s1',name='S',type='single_well',well_ids=['w'],template_id='t',path='plots/s1.json')
assert 'free_graphics' not in _to_json(doc2)
print('schema v4 OK')
"
```

- [ ] **Step 6: 提交**

```bash
git add well-log-engine/apps/wellplot-desktop/well_log_workstation/plot_document.py well-log-engine/apps/wellplot-desktop/tests/test_well_log_workstation_plot_free_graphics.py
git commit -m "feat(workstation): schema v4 free_graphics field + v3 upgrade chain (spec §4.1)"
```

---

## Task 12: CompositeView 保存/恢复 + 图片资产 + 工具条(paleo-workbench 父仓)

CompositeView 新增"保存布局"入口:回写 panels `rect_mm` + free_graphics + 图片复制到工区资产目录;恢复路径在 `_show_composite` 中按 `doc.free_graphics` 逐条 `add_free_graphic`;工具条新增按钮。

**Files:**
- Modify: `well-log-engine/apps/wellplot-desktop/well_log_workstation/composite_view.py`
- Modify: `well-log-engine/apps/wellplot-desktop/well_log_workstation/shell.py`(`_show_composite` 追加 free_graphics 恢复)
- Test: `tests/test_composite_free_graphics_save_restore.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_composite_free_graphics_save_restore.py
"""CompositeView save/restore + image asset copy (spec §4.2–4.4).

The pure-Python pieces (panel reconciliation, image-path rewrite) are
verifiable without PySide6; the Qt save/restore path runs on CI.
"""

from __future__ import annotations

import json
from pathlib import Path


def test_reconcile_panels_updates_rect_mm():
    """Panel rects read from the window override persisted rect_mm."""
    from well_log_workstation.composite_view import reconcile_panels

    doc_panels = [
        {"plot_id": "p1", "slot": "main", "source_plot_type": "single_well",
         "rect_mm": [10.0, 10.0, 40.0, 20.0], "render_mode": "live"},
    ]
    scene_panels = [
        {"plot_id": "p1", "slot": "main", "source_plot_type": "single_well",
         "rect_mm": [30.0, 30.0, 50.0, 25.0], "render_mode": "live"},
    ]
    result = reconcile_panels(doc_panels, scene_panels)
    assert result[0]["rect_mm"] == [30.0, 30.0, 50.0, 25.0]


def test_reconcile_panels_adds_new_removes_gone():
    from well_log_workstation.composite_view import reconcile_panels

    doc_panels = [
        {"plot_id": "p1", "slot": "main", "source_plot_type": "single_well",
         "rect_mm": None, "render_mode": "live"},
        {"plot_id": "gone", "slot": "main", "source_plot_type": "single_well",
         "rect_mm": None, "render_mode": "live"},
    ]
    scene_panels = [
        {"plot_id": "p1", "slot": "main", "source_plot_type": "single_well",
         "rect_mm": [10.0, 10.0, 40.0, 20.0], "render_mode": "live"},
        {"plot_id": "p2", "slot": "main", "source_plot_type": "section",
         "rect_mm": [10.0, 40.0, 40.0, 20.0], "render_mode": "snapshot"},
    ]
    result = reconcile_panels(doc_panels, scene_panels)
    ids = {p["plot_id"] for p in result}
    assert "p1" in ids
    assert "p2" in ids
    assert "gone" not in ids


def test_rewrite_image_paths_copies_to_assets(tmp_path: Path):
    """Image records with absolute paths get rewritten to workspace-relative."""
    from well_log_workstation.composite_view import rewrite_image_paths

    # Create a fake source image
    src = tmp_path / "logo.png"
    src.write_bytes(b"\x89PNG fake")
    records = [
        {"kind": "image", "props": {"path": str(src)},
         "geometry": {"x": 1.0, "y": 1.0, "w": 10.0, "h": 5.0}},
        {"kind": "rect", "props": {},
         "geometry": {"x": 1.0, "y": 1.0, "w": 10.0, "h": 5.0}},
    ]
    result = rewrite_image_paths(records, workspace_root=tmp_path, plot_id="comp1")
    # Image path rewritten to workspace-relative
    assert result[0]["props"]["path"].startswith("plots/assets/comp1/")
    asset_file = tmp_path / result[0]["props"]["path"]
    assert asset_file.is_file()
    # Non-image untouched
    assert result[1]["props"] == {}
```

- [ ] **Step 2: 验证失败**

```bash
/usr/bin/python3 -m py_compile tests/test_composite_free_graphics_save_restore.py
/usr/bin/python3 -c "from well_log_workstation.composite_view import reconcile_panels" 2>&1 | tail -1
# 预期 ImportError(红)
```

- [ ] **Step 3: 实现 `composite_view.py` 追加 —— 纯函数 + 保存/恢复方法**

在文件末尾(`CompositeView` 类之后)追加两个纯函数:

```python
# -- pure helpers (spec §4.2–4.3; no Qt, verifiable with /usr/bin/python3) --

def reconcile_panels(
    doc_panels: list[dict],
    scene_panels: list[dict],
) -> list[dict]:
    """Reconcile persisted panel dicts with what the window reports.

    Matching key is ``(plot_id, slot)``. Scene rects override; scene-only
    panels are appended; doc-only panels are dropped (removed from scene).
    """
    scene_map: dict[tuple[str, str], dict] = {}
    for sp in scene_panels:
        scene_map[(sp["plot_id"], sp["slot"])] = sp
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for dp in doc_panels:
        key = (dp["plot_id"], dp["slot"])
        if key in scene_map:
            sp = scene_map[key]
            result.append({
                "plot_id": sp["plot_id"],
                "slot": sp["slot"],
                "source_plot_type": sp["source_plot_type"],
                "rect_mm": sp["rect_mm"],
                "render_mode": sp["render_mode"],
            })
            seen.add(key)
        # else: panel was in doc but removed from scene -> drop
    # Append scene panels that weren't in doc (newly added)
    for key, sp in scene_map.items():
        if key not in seen:
            result.append({
                "plot_id": sp["plot_id"],
                "slot": sp["slot"],
                "source_plot_type": sp["source_plot_type"],
                "rect_mm": sp["rect_mm"],
                "render_mode": sp["render_mode"],
            })
    return result


def rewrite_image_paths(
    records: list[dict],
    workspace_root: Path,
    plot_id: str,
) -> list[dict]:
    """Copy absolute-path image sources into ``plots/assets/<plot_id>/`` and
    rewrite ``props.path`` to workspace-relative. Non-image and
    already-relative paths are untouched (spec §4.3).
    """
    import shutil
    import uuid as _uuid

    asset_prefix = f"plots/assets/{plot_id}/"
    result = []
    for rec in records:
        if rec.get("kind") != "image":
            result.append(rec)
            continue
        path = rec.get("props", {}).get("path", "")
        if path.startswith(asset_prefix) or not path:
            result.append(rec)
            continue
        src = Path(path)
        if not src.is_absolute() or not src.is_file():
            result.append(rec)
            continue
        dest_rel = f"plots/assets/{plot_id}/{_uuid.uuid4().hex}.png"
        dest = workspace_root / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        new_rec = dict(rec)
        new_rec["props"] = {**rec.get("props", {}), "path": dest_rel}
        result.append(new_rec)
    return result
```

在 `CompositeView` 类中追加保存/恢复方法(在 `add_panel_ref` 之后):

```python
    # -- save / restore (spec §4.2–4.4, Task 12) ------------------------

    def save_layout(self) -> None:
        """Persist panel rects + free graphics + image assets to the active
        composite plot document."""
        if self._workspace is None or self._active_plot_id is None:
            return
        win = self._layout_window
        if win is None:
            return
        from well_log_workstation.plot_document import (
            load_plot_document, save_plot_document,
        )
        from well_log_workstation.composite_view import (
            reconcile_panels, rewrite_image_paths,
        )

        doc = load_plot_document(self._workspace, self._active_plot_id)
        scene_panels = win.panels()
        doc_panels = [
            {
                "plot_id": p.plot_id, "slot": p.slot,
                "source_plot_type": p.source_plot_type,
                "rect_mm": p.rect_mm, "render_mode": p.render_mode,
            }
            for p in doc.panels
        ]
        reconciled = reconcile_panels(doc_panels, scene_panels)
        from well_log_workstation.plot_document import PanelRef
        doc.panels = [
            PanelRef(
                plot_id=p["plot_id"], slot=p["slot"],
                source_plot_type=p["source_plot_type"],
                rect_mm=p["rect_mm"], render_mode=p["render_mode"],
            )
            for p in reconciled
        ]
        free_recs = win.free_graphics()
        free_recs = rewrite_image_paths(
            free_recs, self._workspace.root, self._active_plot_id,
        )
        doc.free_graphics = free_recs
        save_plot_document(self._workspace, doc)

    def restore_free_graphics(self, records: list[dict]) -> int:
        """Rebuild free graphics from persisted records.

        Returns the number of records that could not be restored (unknown
        kind / malformed); the caller reports this to the status bar.
        """
        win = self._layout_window
        if win is None:
            return 0
        failed = 0
        for rec in records:
            item_id = win.add_free_graphic(rec)
            if item_id is None:
                failed += 1
        return failed
```

在工具条 `bar` 的 `add_btn` 之后追加保存按钮(`__init__` 内):

```python
        save_btn = QPushButton("保存布局")
        save_btn.setObjectName("Button_SaveCompositeLayout")
        save_btn.clicked.connect(self.save_layout)
        bar.addWidget(save_btn)
```

同时加 `self._active_plot_id: str | None = None`(在 `self._workspace = None` 之后),并在 `set_workspace` 中不改;需要新增一个方法让 shell 设定当前 plot:

```python
    def set_active_plot_id(self, plot_id: str | None) -> None:
        self._active_plot_id = plot_id
```

- [ ] **Step 4: 修改 `shell.py` —— `_show_composite` 追加 free_graphics 恢复**

在 `_show_composite` 方法中,`for panel in plot.panels:` 循环之后追加:

```python
        self.composite_view.set_active_plot_id(plot.id)
        failed = self.composite_view.restore_free_graphics(plot.free_graphics)
        if failed > 0:
            self.statusBar().showMessage(
                f"{failed} 条图形记录无法恢复（未知类型或格式错误）", 5000
            )
```

- [ ] **Step 5: 验证通过**

```bash
/usr/bin/python3 -m py_compile \
  well-log-engine/apps/wellplot-desktop/well_log_workstation/composite_view.py \
  well-log-engine/apps/wellplot-desktop/well_log_workstation/shell.py \
  tests/test_composite_free_graphics_save_restore.py
/usr/bin/python3 -c "
from pathlib import Path
import tempfile
from well_log_workstation.composite_view import reconcile_panels, rewrite_image_paths
# reconcile
r = reconcile_panels(
    [{'plot_id':'p1','slot':'main','source_plot_type':'sw','rect_mm':[10.0,10.0,40.0,20.0],'render_mode':'live'}],
    [{'plot_id':'p1','slot':'main','source_plot_type':'sw','rect_mm':[30.0,30.0,50.0,25.0],'render_mode':'live'}],
)
assert r[0]['rect_mm'] == [30.0,30.0,50.0,25.0]
# image rewrite
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    src = td / 'logo.png'; src.write_bytes(b'fake')
    recs = [{'kind':'image','props':{'path':str(src)},'geometry':{'x':1.0,'y':1.0,'w':2.0,'h':2.0}}]
    out = rewrite_image_paths(recs, td, 'c1')
    assert out[0]['props']['path'].startswith('plots/assets/c1/')
    assert (td / out[0]['props']['path']).is_file()
print('composite save/restore pure helpers OK')
"
```

- [ ] **Step 6: 提交**

```bash
git add well-log-engine/apps/wellplot-desktop/well_log_workstation/composite_view.py well-log-engine/apps/wellplot-desktop/well_log_workstation/shell.py tests/test_composite_free_graphics_save_restore.py
git commit -m "feat(workstation): CompositeView save/restore layout + free_graphics + image assets (spec §4.2–4.4)"
```

---

## Task 13: gitlink bump + 接线终验 + PR-B(paleo-workbench 父仓)

引擎 PR-A 合并后,bump 父仓 gitlink 指向引擎 PR-A 的 merge commit;推分支开 PR-B。

**Files:**
- Modify: `geo-viz-engine`(gitlink bump —— `git add geo-viz-engine`)
- Test: 接线冒烟(纯 Python)

- [ ] **Step 1: 确认引擎 PR-A 已合并**

```bash
cd geo-viz-engine && gh pr list --state merged --head feat/cartography-free-graphics \
  --json number,mergeCommit -q '.[0].mergeCommit.oid'
```

如果尚未合并(用户说不要等 CI,但 merge 需要人在 GitHub 操作),向用户确认是否可以 merge 后继续。

- [ ] **Step 2: bump gitlink**

```bash
cd /home/kevin/projects/paleo_project
cd geo-viz-engine && git checkout main && git pull origin main
cd /home/kevin/projects/paleo_project
git add geo-viz-engine    # 只 add gitlink,绝不 add -A
git diff --cached --stat  # 确认只有 geo-viz-engine 一行变更
```

- [ ] **Step 3: 迁移宿主私有属性访问**

把 `export_dispatch.py:242` 的 `window._scene.render(...)` 迁移到公开 API:

```bash
# 读当前代码,确认精确 old_string
grep -n "_scene" well-log-engine/apps/wellplot-desktop/well_log_workstation/export_dispatch.py
```

如果引擎 PR-A 已添加了公开的 `scene()` 方法(window.py Task 9 未显式加,若没有则在此补):

在 `window.py` 中追加(如果没有的话):

```python
    def scene(self):
        """Public accessor replacing ``window._scene`` private access."""
        return self._scene

    def view(self):
        """Public accessor replacing ``win._view`` private access."""
        return self._view
```

在 `export_dispatch.py` 中把 `window._scene` 改为 `window.scene()`。

在 `composite_view.py` 的 `_ensure_layout_window` 中把 `view = win._view` 改为 `view = win.view()`。

- [ ] **Step 4: 纯 Python 接线冒烟**

```bash
/usr/bin/python3 -m py_compile \
  well-log-engine/apps/wellplot-desktop/well_log_workstation/composite_view.py \
  well-log-engine/apps/wellplot-desktop/well_log_workstation/export_dispatch.py \
  well-log-engine/apps/wellplot-desktop/well_log_workstation/shell.py \
  well-log-engine/apps/wellplot-desktop/well_log_workstation/plot_document.py
/usr/bin/python3 -c "
# 确认宿主不再依赖私有 _scene / _view
import ast, pathlib
for f in ['well-log-engine/apps/wellplot-desktop/well_log_workstation/composite_view.py', 'well-log-engine/apps/wellplot-desktop/well_log_workstation/export_dispatch.py']:
    src = pathlib.Path(f).read_text()
    assert 'win._scene' not in src and 'window._scene' not in src, f'{f} still uses _scene'
    assert 'win._view' not in src, f'{f} still uses win._view'
print('private-attribute migration OK')
"
```

- [ ] **Step 5: push + 开 PR-B**

```bash
cd /home/kevin/projects/paleo_project
git add geo-viz-engine well-log-engine/apps/wellplot-desktop/well_log_workstation/composite_view.py well-log-engine/apps/wellplot-desktop/well_log_workstation/export_dispatch.py
git diff --cached --stat  # 确认: geo-viz-engine gitlink + 两个 .py
git commit -m "feat(workstation): composite free-graphics host integration (gitlink bump + save/restore + public API migration)"
git push -u origin feat/composite-free-graphics-host
gh pr create --title "feat(workstation): composite free-graphics host (schema v4 + save/restore + gitlink bump)" \
  --body "Implements spec §4 / \`docs/superpowers/specs/2026-08-04-composite-free-graphics-design.md\` (PR-B).

Depends on engine PR-A: \`feat/cartography-free-graphics\`.

**Contents:**
- Task 11: schema v4 ``free_graphics`` field + v3 upgrade chain
- Task 12: CompositeView save/restore layout + free_graphics + image asset copy
- Task 13: gitlink bump to engine PR-A merge + private-attribute migration (``_scene``/``_view`` → ``scene()``/``view()``)
"
```

- [ ] **Step 6: 向用户报告 PR-A 和 PR-B 号**

---

## Self-Audit Checklist(执行完所有 Task 后跑一次)

1. **Spec coverage**: 逐条对照规格 §3.1–§4.4:
   - 9 种 item 全部实现 ✓(Task 3–6)
   - resize 手柄真实逻辑 ✓(Task 2)
   - 工具模式放置 ✓(Task 7)
   - 属性面板 + 删除 ✓(Task 8)
   - record 契约 ✓(Task 1,`records.py` 冻结)
   - window 公开 API ✓(Task 9)
   - schema v4 ✓(Task 11)
   - 保存布局 ✓(Task 12)
   - 图片资产 ✓(Task 12 `rewrite_image_paths`)
   - 恢复路径 ✓(Task 12 `_show_composite` + `restore_free_graphics`)
   - 面板布局持久化修复 ✓(Task 12 `reconcile_panels` + `panels()`)

2. **占位符扫描**:
```bash
grep -rn "TODO\|FIXME\|pass\s*$\|\.\.\.\s*$" \
  geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/items/free/ \
  geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/placement.py \
  geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/cartography/properties.py \
  | grep -v __pycache__ || echo "No placeholders found"
```

3. **类型一致性**: `records.py` 的 `parse_record` 输出 dict 的 key 与 item 类 `to_record()` 的输出 key 完全一致(id/kind/style/geometry/props);`from_normalized` 接收 `parse_record` 输出。

4. **跨仓契约**: PR-B 的 `rewrite_image_paths` 输出的 path 格式 (`plots/assets/<plot_id>/<uuid>.png`) 与规格 §4.3 一致;`from_record` 对已相对化的路径不重复复制。
