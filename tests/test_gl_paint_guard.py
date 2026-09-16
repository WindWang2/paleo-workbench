"""GL 视口绘制守卫回归（dock 拖动崩溃：零尺寸 paint 进驱动）。

现场：移动地震/测井可视化窗口 → Windows 访问违规，栈顶停在
``GLLinePlotItem.paint``（context 有效，surface 不可画）。守卫必须在
item GL 调用之前拦掉零尺寸 paint；本文件零 GL 上下文可测（桩对象）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.main import (
    _gl_surface_drawable,
    _install_glview_paint_guard,
)


class _StubView:
    def __init__(self, *, valid=True, context=True, width=800, height=600):
        self._valid = valid
        self._context = object() if context else None
        self._width = width
        self._height = height

    def isValid(self):  # noqa: N802 - Qt 命名
        return self._valid

    def context(self):
        return self._context

    def width(self):
        return self._width

    def height(self):
        return self._height


class _DeletedView:
    def isValid(self):
        raise RuntimeError("wrapped C++ object already deleted")

    def context(self):
        raise RuntimeError("wrapped C++ object already deleted")

    def width(self):
        raise RuntimeError("wrapped C++ object already deleted")

    def height(self):
        raise RuntimeError("wrapped C++ object already deleted")


def test_drawable_predicate() -> None:
    assert _gl_surface_drawable(_StubView()) is True
    assert _gl_surface_drawable(_StubView(width=0, height=600)) is False
    assert _gl_surface_drawable(_StubView(width=800, height=0)) is False
    assert _gl_surface_drawable(_StubView(width=0, height=0)) is False
    assert _gl_surface_drawable(_DeletedView()) is False


def test_guard_skips_zero_size_paint(monkeypatch) -> None:
    """零尺寸 + 有效 context：不得进入原始 paintGL（会进驱动）。"""
    pytest.importorskip("pyqtgraph.opengl")
    import pyqtgraph.opengl as gl

    calls: list = []
    monkeypatch.setattr(
        gl.GLViewWidget, "paintGL",
        lambda self, *a, **k: calls.append(self),
        raising=False)
    _install_glview_paint_guard()
    patched = gl.GLViewWidget.paintGL
    patched(_StubView(width=0, height=600))
    assert calls == []


def test_guard_passes_healthy_paint(monkeypatch) -> None:
    """正常尺寸 + 有效 context：原样透传。"""
    pytest.importorskip("pyqtgraph.opengl")
    import pyqtgraph.opengl as gl

    calls: list = []
    monkeypatch.setattr(
        gl.GLViewWidget, "paintGL",
        lambda self, *a, **k: calls.append(self),
        raising=False)
    _install_glview_paint_guard()
    patched = gl.GLViewWidget.paintGL
    view = _StubView()
    patched(view)
    assert calls == [view]


def test_guard_skips_dead_context(monkeypatch) -> None:
    """既有行为：无效 context 照样拦（零尺寸判断不得先崩）。"""
    pytest.importorskip("pyqtgraph.opengl")
    import pyqtgraph.opengl as gl

    calls: list = []
    monkeypatch.setattr(
        gl.GLViewWidget, "paintGL",
        lambda self, *a, **k: calls.append(self),
        raising=False)
    _install_glview_paint_guard()
    patched = gl.GLViewWidget.paintGL
    patched(_StubView(valid=False))
    patched(_StubView(context=None))
    patched(_DeletedView())
    assert calls == []
