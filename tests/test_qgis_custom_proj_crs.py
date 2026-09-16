"""自定义 +proj/WKT 工程 CRS：画布目标 CRS 与工程 CRS 必须接受。

用户现场（project_area，本地假坐标 tmerc 米制）：桥曾只用
``QgsCoordinateReferenceSystem(QString)``（仅认 authid），自定义串
被静默拒收 → 目标 CRS 落空、单位 unknown、比例尺按度换算出几十亿
（状态栏 1:24亿）。本文件钉住 authid → PROJ → WKT 的解析顺序；
无桥环境诚实跳过。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

from tests.qgis_support import require_mapstack  # noqa: E402

mapstack = require_mapstack()

CUSTOM_TMERC = (
    "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 "
    "+ellps=WGS84 +units=m +no_defs"
)
# 用户工区真实 bbox（米）。
WORKAREA = (328.0, 1264.0, 12843.0, 15882.0)


@pytest.fixture()
def stack(qapp):
    s = mapstack.QgisMapStack()
    s.initialize()
    yield s
    s.shutdown()


@pytest.fixture()
def canvas(stack):
    return stack.create_canvas()


def test_destination_crs_accepts_custom_proj(stack, canvas) -> None:
    stack.set_destination_crs(canvas, CUSTOM_TMERC)
    assert stack.canvas_map_units(canvas) == "meters"
    stack.set_canvas_extent(canvas, *WORKAREA)
    scale = stack.canvas_scale(canvas)
    assert 1.0e3 < scale < 1.0e7, scale


def test_destination_crs_accepts_wkt(stack, canvas) -> None:
    pyproj = pytest.importorskip("pyproj", reason="WKT 变体需 pyproj 生成")
    wkt = pyproj.CRS(CUSTOM_TMERC).to_wkt()
    stack.set_destination_crs(canvas, wkt)
    assert stack.canvas_map_units(canvas) == "meters"
    stack.set_canvas_extent(canvas, *WORKAREA)
    assert 1.0e3 < stack.canvas_scale(canvas) < 1.0e7


def test_project_crs_accepts_custom_proj(stack) -> None:
    assert stack.set_project_crs(CUSTOM_TMERC) == ""
    assert stack.set_project_crs("NOPE:123").startswith("cannot resolve")
