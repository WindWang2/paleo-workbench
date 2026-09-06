"""MapStatusBar 坐标读数格式契约（固定小数位数）。"""

from __future__ import annotations

from paleo_workbench.ui.map_status_bar import (
    _GEO_DECIMALS,
    _PROJECTED_DECIMALS,
    MapStatusBar,
)


def _make_bar(qtbot) -> MapStatusBar:
    bar = MapStatusBar()
    qtbot.addWidget(bar)
    return bar


def test_coordinate_readout_uses_fixed_decimals(qtbot):
    """同一坐标系下小数位数恒定，不随数值大小漂移（回归：原 :.6g）。"""
    bar = _make_bar(qtbot)
    bar.update_state(point=(113.234567891, 34.56789012), crs="EPSG:4326")
    assert bar.coordinate.toolTip() == (
        f"X: {113.234567891:.{_GEO_DECIMALS}f}  Y: {34.56789012:.{_GEO_DECIMALS}f}"
    )
    # 整数坐标也按固定位数补零，读数宽度稳定。
    bar.update_state(point=(113.0, 34.0), crs="EPSG:4326")
    assert bar.coordinate.toolTip() == f"X: {113:.{_GEO_DECIMALS}f}  Y: {34:.{_GEO_DECIMALS}f}"


def test_projected_crs_uses_projected_decimals(qtbot):
    bar = _make_bar(qtbot)
    bar.update_state(point=(456789.123456, 3456789.987654), crs="EPSG:32650")
    assert bar.coordinate.toolTip() == (
        f"X: {456789.123456:.{_PROJECTED_DECIMALS}f}"
        f"  Y: {3456789.987654:.{_PROJECTED_DECIMALS}f}"
    )


def test_decimal_selection_falls_back_without_pyproj(qtbot, monkeypatch):
    import builtins

    bar = _make_bar(qtbot)
    real_import = builtins.__import__

    def _no_pyproj(name, *args, **kwargs):
        if name == "pyproj":
            raise ImportError("simulated missing pyproj")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pyproj)
    # 度域坐标 → 按量级猜地理；超出度域 → 投影。
    assert bar._decimals_for("EPSG:4326", (113.1, 34.2)) == _GEO_DECIMALS
    assert bar._decimals_for("", (456789.1, 3456789.9)) == _PROJECTED_DECIMALS
