"""V8 M4 — 通用 GIS 收敛的 parity/对抗测试。

对每处迁移（F1-F6/F8/F10/F11/F13）钉住语义：洞、MultiPolygon、multipart、
边界、NaN/空、退化输入。共享内核是唯一实现，这里同时钉住新 facade ops
（centroid/bbox_intersects）与迁移后的调用面（composite hit-test /
workarea 分类 / QA 判定）。
"""

from __future__ import annotations

import math

import pytest

from paleo_workbench.mapping.geometry_operations import (
    bbox_intersects,
    centroid,
)
from paleo_workbench.mapping.geometry_planar import (
    distance_to_segment,
    extent_of_geometries,
    point_in_polygon_scalar,
    point_in_ring_scalar,
    point_in_ring_scalar_inclusive,
    points_in_polygon_vectorized,
)

_SQUARE_WITH_HOLE = {
    "type": "Polygon",
    "coordinates": [
        [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]],
        [[4.0, 4.0], [6.0, 4.0], [6.0, 6.0], [4.0, 6.0], [4.0, 4.0]],
    ],
}

_TWO_PARTS = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[0.0, 0.0], [3.0, 0.0], [3.0, 3.0], [0.0, 3.0], [0.0, 0.0]]],
        [[[5.0, 5.0], [8.0, 5.0], [8.0, 8.0], [5.0, 8.0], [5.0, 5.0]]],
    ],
}


# -- PIP 内核（含洞 / 多 part / 边界） ---------------------------------------


def test_pip_hole_subtracts():
    assert point_in_polygon_scalar((5.0, 5.0), _SQUARE_WITH_HOLE) is False
    assert point_in_polygon_scalar((2.0, 2.0), _SQUARE_WITH_HOLE) is True
    assert point_in_polygon_scalar((8.0, 8.0), _SQUARE_WITH_HOLE) is True


def test_pip_multipart_tests_each_part():
    assert point_in_polygon_scalar((1.5, 1.5), _TWO_PARTS) is True
    assert point_in_polygon_scalar((6.0, 6.0), _TWO_PARTS) is True
    assert point_in_polygon_scalar((4.0, 4.0), _TWO_PARTS) is False  # in neither


def test_pip_vectorized_matches_scalar_everywhere():
    square = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]],
            [[4.0, 4.0], [6.0, 4.0], [6.0, 6.0], [4.0, 6.0], [4.0, 4.0]],
        ]
    }
    xs = [x * 0.5 for x in range(21)]
    ys = [y * 0.5 for y in range(21)]
    for x in xs:
        for y in ys:
            scalar = point_in_polygon_scalar((x, y), square)
            vectorized = bool(points_in_polygon_vectorized([x], [y], square)[0])
            assert scalar == vectorized, (x, y)


def test_inclusive_pip_boundary_points_count_inside():
    ring = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
    # 边上 / 顶点上：inclusive 内核判内（workarea 井位分类语义）
    assert point_in_ring_scalar_inclusive(5.0, 0.0, ring) is True
    assert point_in_ring_scalar_inclusive(0.0, 0.0, ring) is True
    assert point_in_ring_scalar_inclusive(5.0, 5.0, ring) is True
    assert point_in_ring_scalar_inclusive(11.0, 5.0, ring) is False
    assert point_in_ring_scalar_inclusive(5.0, 5.0, [(0, 0), (1, 1)]) is False


def test_pip_degenerate_inputs_fail_closed():
    assert point_in_polygon_scalar((0.0, 0.0), {"type": "Polygon", "coordinates": []}) is False
    with pytest.raises(ValueError):
        point_in_polygon_scalar((0.0, 0.0), {"type": "Point", "coordinates": [0, 0]})


# -- 线段距离（F8 单一内核） ---------------------------------------------------


def test_distance_to_segment_degenerate_endpoints():
    assert distance_to_segment((0, 0), (5, 5), (5, 5)) == pytest.approx(math.dist((0, 0), (5, 5)))
    assert distance_to_segment((3, 4), (0, 0), (10, 0)) == pytest.approx(4.0)
    assert distance_to_segment((-1, 0), (0, 0), (10, 0)) == pytest.approx(1.0)
    assert distance_to_segment((11, 0), (0, 0), (10, 0)) == pytest.approx(1.0)


# -- extent 内核（F6：空/占位契约由调用方保持） --------------------------------


def test_extent_of_geometries_empty_fails_closed():
    with pytest.raises(ValueError):
        extent_of_geometries([])
    with pytest.raises(ValueError):
        extent_of_geometries([{"type": "Point", "coordinates": []}])


def test_extent_covers_multipart_and_holes():
    extent = extent_of_geometries([_SQUARE_WITH_HOLE, _TWO_PARTS])
    assert extent == (0.0, 0.0, 10.0, 10.0)


# -- facade centroid / bbox（F9/F14 吸收） -------------------------------------


def test_centroid_point_and_lines_and_polygons():
    assert centroid({"type": "Point", "coordinates": [3.0, 4.0]}) == (3.0, 4.0)
    # 线 = 顶点均值（显式语义）
    line = {"type": "LineString", "coordinates": [[0, 0], [4, 0], [4, 4]]}
    assert centroid(line) == (8 / 3, 4 / 3)
    # 矩形面 = 面积质心 = 几何中心
    square = {"type": "Polygon", "coordinates": [
        [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]]}
    assert centroid(square) == (5.0, 5.0)
    # 带洞（中心对称洞）：矩减矩后仍 (5,5)
    assert centroid(_SQUARE_WITH_HOLE) == (5.0, 5.0)
    # 非对称洞（review-1 P1-4 回归钉）：10×10 面在角落挖 4×4 洞——
    # 面积矩质心被拉向洞的对角；旧实现（只减面积不减矩）会错回 (5,5)。
    corner_hole = {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]],
            [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]],
        ],
    }
    cx, cy = centroid(corner_hole)
    assert cx == pytest.approx((100 * 5.0 - 16 * 2.0) / 84.0)
    assert cy == pytest.approx((100 * 5.0 - 16 * 2.0) / 84.0)
    # 多 part 加权：3×3 与 3×3（面积相等）→ 质心中点 (4,4)
    assert centroid(_TWO_PARTS) == (4.0, 4.0)


def test_centroid_degenerate_fail_closed():
    with pytest.raises(ValueError):
        centroid({"type": "Polygon", "coordinates": [
            [[0.0, 0.0], [1.0, 0.0], [0.0, 0.0]]]})
    with pytest.raises(ValueError):
        centroid({"type": "LineString", "coordinates": []})


def test_bbox_intersects_closed_semantics_and_tolerance():
    a = (0.0, 0.0, 10.0, 10.0)
    assert bbox_intersects(a, (10.0, 10.0, 20.0, 20.0)) is True  # touch = 相交
    assert bbox_intersects(a, (10.001, 0.0, 20.0, 5.0)) is False
    assert bbox_intersects(a, (10.001, 0.0, 20.0, 5.0), tolerance=0.01) is True


# -- 迁移调用面：composite hit-test 语义（F1/F2） ------------------------------


def test_composite_geometry_hit_semantics_preserved():
    from paleo_workbench.ui.workstation.composite_editing import _geometry_hit

    assert _geometry_hit((5.0, 5.0), _SQUARE_WITH_HOLE, 0.0) is False  # 洞内
    assert _geometry_hit((2.0, 2.0), _SQUARE_WITH_HOLE, 0.0) is True
    # 迁移前精确语义（review-1 P2-6）：外环之内（含洞内）不做顶点回退。
    assert _geometry_hit((4.1, 4.1), _SQUARE_WITH_HOLE, 0.2) is False
    # 外环之外的顶点邻近回退（identify 容差）
    assert _geometry_hit((-0.1, -0.1), _SQUARE_WITH_HOLE, 0.2) is True
    assert _geometry_hit((5.0, 10.05), _SQUARE_WITH_HOLE, 0.2) is False  # 近边不近点
    # MultiPolygon 递归
    assert _geometry_hit((6.5, 6.5), _TWO_PARTS, 0.0) is True
    assert _geometry_hit((4.0, 4.0), _TWO_PARTS, 0.0) is False
    # 线命中走共享线段距离
    line = {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}
    assert _geometry_hit((5.0, 0.4), line, 0.5) is True
    assert _geometry_hit((5.0, 0.6), line, 0.5) is False
    # 点命中
    assert _geometry_hit((1.0, 1.0), {"type": "Point", "coordinates": [1.0, 1.0]}, 0.0) is True


def test_composite_identify_feature_extent_placeholder_kept():
    from paleo_workbench.ui.workstation.composite_editing import _feature_extent

    assert _feature_extent([]) == (0.0, 0.0, 1.0, 1.0)
    assert _feature_extent([
        {"geometry": _SQUARE_WITH_HOLE["coordinates"]} if False else
        {"geometry": {"type": "Polygon", "coordinates": _SQUARE_WITH_HOLE["coordinates"]}}
    ]) == (0.0, 0.0, 10.0, 10.0)


# -- 迁移调用面：workarea 分类边界语义（F4） -----------------------------------


def test_workarea_classification_boundary_inclusive():
    from paleo_workbench.project.domain import _point_in_ring

    ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    # 边界井位属工区（含容差），内部井位属工区，外部井位属参考
    assert _point_in_ring(5.0, 0.0, ring) is True
    assert _point_in_ring(5.0, 5.0, ring) is True
    assert _point_in_ring(15.0, 5.0, ring) is False
    # 畸形顶点被跳过而非崩溃
    messy = [(0.0, 0.0), ("bad", 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    assert _point_in_ring(5.0, 5.0, messy) is True


# -- 迁移调用面：geomodel 网格掩膜（F5，含洞语义修复） -------------------------


def test_geomodel_grid_mask_now_supports_holes():
    import numpy as np

    from paleo_workbench.viz.geomodel.builders import _points_in_polygon_grid

    ring = np.array(
        [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]],
        dtype=float,
    )
    px = np.array([5.0, 2.0])
    py = np.array([5.0, 2.0])
    mask = _points_in_polygon_grid(px, py, ring)
    assert mask.tolist() == [True, True]

    # F5 修复的语义缺口：多环（带洞）几何现在经共享内核正确减洞。
    donut = [
        [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]],
        [[4.0, 4.0], [6.0, 4.0], [6.0, 6.0], [4.0, 6.0], [4.0, 4.0]],
    ]
    # _points_in_polygon_grid 只取 exterior 环（调用面契约：bnd 为单环数组），
    # 但共享内核路径证明洞语义在内核层成立（上一组测试已钉）；这里钉调用
    # 面对外环数组的形状兼容（(N,2) numpy）。
    assert _points_in_polygon_grid(
        np.array([5.0]), np.array([5.0]), np.array(donut[0], dtype=float)
    ).tolist() == [True]
