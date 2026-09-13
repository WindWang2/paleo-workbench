"""V12-B moving-neighbourhood kriging: wiring, disclosure, and equivalence.

The neighbourhood path is OPT-IN (``max_neighbors`` / ``search_radius`` on
``InterpolationOptions`` — fields that already existed for IDW). The default
path stays byte-identical to the pre-V12-B fallback; that contract is pinned
by the golden baseline (``scripts/geopipeline_v12_golden.py`` +
``tests/data/geopipeline_golden``), not by this file.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from paleo_workbench.mapping.geological_pipeline.interpolator import (
    KrigingInterpolator,
    _pure_numpy_kriging,
)
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)


def _synthetic_dataset(n: int, seed: int = 7) -> GeologicalFactorDataset:
    rng = np.random.default_rng(seed)
    ds = GeologicalFactorDataset(factor_name="sand_ratio", unit="%", crs="EPSG:32650")
    for i in range(n):
        x = float(rng.uniform(0.0, 1000.0))
        y = float(rng.uniform(0.0, 1000.0))
        value = float(30.0 + 0.02 * x - 0.01 * y + rng.normal(0.0, 2.0))
        ds.add_point(
            GeologicalFactor(
                name="sand_ratio", value=value, unit="%", well_id=f"W{i:04d}",
                x=x, y=y, crs="EPSG:32650",
            )
        )
    return ds


def _arrays(n: int, seed: int = 7):
    ds = _synthetic_dataset(n, seed)
    return ds.to_arrays()


class TestWiringAndDisclosure:
    def test_default_path_has_no_neighborhood_block(self):
        x, y, z = _arrays(60)
        _, _, params = _pure_numpy_kriging(
            x, y, z, np.linspace(0, 1000, 12), np.linspace(0, 1000, 12)
        )
        assert "neighborhood" not in params
        assert params["method"] == "kriging_fallback"

    def test_interpolator_discloses_neighborhood(self):
        ds = _synthetic_dataset(200)
        result = KrigingInterpolator().interpolate(
            ds,
            InterpolationOptions(
                method="kriging", grid_n=24,
                max_neighbors=16, search_radius=500.0, min_neighbors=6,
            ),
        )
        nb = result.algorithm_parameters["neighborhood"]
        assert nb["engine"] == "cKDTree-moving"
        assert nb["max_neighbors"] == 16
        assert nb["search_radius"] == 500.0
        assert nb["min_neighbors"] == 6
        assert nb["capped"] is False
        # 近似披露：这条路径不是引擎等价物（诚实降级惯例）
        assert result.algorithm_parameters["degraded"] is True
        assert "moving-neighbourhood" in result.algorithm_parameters["degraded_reason"]

    def test_cap_is_disclosed_not_silent(self):
        ds = _synthetic_dataset(120)
        result = KrigingInterpolator().interpolate(
            ds,
            InterpolationOptions(method="kriging", grid_n=16, max_neighbors=5000),
        )
        nb = result.algorithm_parameters["neighborhood"]
        # n=120：k=min(5000,120,256)=120 —— 样本数截断不是近似
        assert nb["max_neighbors"] == 120
        assert nb["capped"] is False

        result_big = KrigingInterpolator().interpolate(
            _synthetic_dataset(600),
            InterpolationOptions(method="kriging", grid_n=16, max_neighbors=2000),
        )
        nb_big = result_big.algorithm_parameters["neighborhood"]
        assert nb_big["max_neighbors"] == 256  # _KRIGE_NEIGHBORHOOD_CAP
        assert nb_big["capped"] is True
        assert "tractability cap" in nb_big["note"]

    def test_constant_field_still_shortcircuits_with_disclosure(self):
        x, y, _ = _arrays(30)
        z = np.full_like(x, 17.25)
        gz, gv, params = _pure_numpy_kriging(
            x, y, z, np.linspace(0, 1000, 10), np.linspace(0, 1000, 10),
            max_neighbors=8,
        )
        assert np.allclose(gz, 17.25, atol=1e-6)
        assert params["neighborhood"]["max_neighbors"] == 8
        assert "constant field" in params["neighborhood"]["note"]

    def test_dispatcher_routes_neighborhood_options(self):
        from paleo_workbench.mapping.geological_pipeline.interpolator import (
            interpolate_factor,
        )
        ds = _synthetic_dataset(150)
        result = interpolate_factor(
            ds,
            InterpolationOptions(method="kriging", grid_n=20, max_neighbors=12),
        )
        assert result.algorithm_parameters["neighborhood"]["max_neighbors"] == 12
        # dispatcher 的 D5 距离策略记录不受影响
        assert result.algorithm_parameters["distance_policy"] == "planar"


class TestNumerics:
    def test_k_equals_n_matches_global_solve(self):
        """k=n (≤cap, no radius): 同一组方程，逐目标解与全局解一致。"""
        x, y, z = _arrays(40, seed=11)
        gx = np.linspace(0, 1000, 15)
        gy = np.linspace(0, 1000, 15)
        gz_global, gv_global, _ = _pure_numpy_kriging(x, y, z, gx, gy)
        gz_moving, gv_moving, _ = _pure_numpy_kriging(
            x, y, z, gx, gy, max_neighbors=40
        )
        assert np.allclose(gz_moving, gz_global, rtol=1e-9, atol=1e-9)
        assert np.allclose(gv_moving, gv_global, rtol=1e-9, atol=1e-9)

    def test_exact_interpolation_at_sample_locations(self):
        """样本点落在自身邻域内（距离 0）→ 精确插值（OK 无偏性质）。"""
        x, y, z = _arrays(80, seed=13)
        gz, _, _ = _pure_numpy_kriging(
            x, y, z, x, y, max_neighbors=12, min_neighbors=4
        )
        assert np.allclose(np.diag(gz), z, atol=1e-4)

    def test_radius_pruning_yields_nodata_below_min_neighbors(self):
        """远离全部样本的目标（邻居数 < min_neighbors）→ NaN，与 IDW 契约一致。"""
        x, y, z = _arrays(60, seed=17)
        # seed=17 的邻居计数（r=300）：远点 0；原点 4（< min）；
        # 场中心 26（≥ min）——三个分支都被钉住。gz[i, j] 是 (y_i, x_j)，
        # 对角线元素即 (gx[i], gy[i])。
        gx = np.array([2000.0, 2001.0, 0.0, 500.0])
        gy = np.array([2000.0, 0.0, 0.0, 500.0])
        gz, _, _ = _pure_numpy_kriging(
            x, y, z, gx, gy, search_radius=300.0, min_neighbors=10
        )
        assert math.isnan(gz[0, 0])   # (2000,2000)：0 个邻居
        assert math.isnan(gz[1, 1])   # (2001,0)：0 个邻居
        assert math.isnan(gz[2, 2])   # (0,0)：4 个邻居 < 10
        assert np.isfinite(gz[3, 3])  # (500,500)：26 个邻居 ≥ 10

    def test_variance_nonnegative_and_lower_at_samples(self):
        x, y, z = _arrays(80, seed=19)
        gz, gv, _ = _pure_numpy_kriging(
            x, y, z, x, y, max_neighbors=16, min_neighbors=8
        )
        assert bool((gv >= -1e-9).all())
        assert float(np.diag(gv).max()) < float(gv.max())

    def test_duplicates_are_merged_before_neighborhood_selection(self):
        rng = np.random.default_rng(23)
        x = rng.uniform(0, 100, 25)
        x[5:8] = 42.0  # 三重合样本
        y = rng.uniform(0, 100, 25)
        y[5:8] = 42.0
        z = rng.normal(10, 2, 25)
        z[5:8] = [4.0, 6.0, 8.0]  # 均值 6
        gz, _, params = _pure_numpy_kriging(
            x, y, z, np.array([42.0]), np.array([42.0]),
            max_neighbors=4, min_neighbors=2,
        )
        assert params["duplicates_merged"] == 2
        assert abs(gz[0, 0] - 6.0) < 0.5

    def test_deterministic_repeat(self):
        x, y, z = _arrays(120, seed=29)
        gx = np.linspace(0, 1000, 20)
        g1, v1, _ = _pure_numpy_kriging(
            x, y, z, gx, gx, max_neighbors=16, min_neighbors=6
        )
        g2, v2, _ = _pure_numpy_kriging(
            x, y, z, gx, gx, max_neighbors=16, min_neighbors=6
        )
        assert g1.tobytes() == g2.tobytes()
        assert v1.tobytes() == v2.tobytes()

    def test_small_k_still_tracks_the_field(self):
        """k=12 的局部克里金仍复现趋势面（信噪比合理的合成场）。"""
        x, y, z = _arrays(300, seed=31)
        rng = np.random.default_rng(32)
        xt = rng.uniform(50, 950, 200)
        yt = rng.uniform(50, 950, 200)
        truth = 30.0 + 0.02 * xt - 0.01 * yt
        gz, _, _ = _pure_numpy_kriging(
            x, y, z, xt, yt, max_neighbors=12, min_neighbors=6
        )
        residual = gz - truth
        # 噪声 σ=2 的场：克里金残差不应劣于样本噪声水平太多
        assert float(np.abs(residual).mean()) < 4.0


class TestPerformance:
    def test_moving_neighborhood_beats_global_at_scale(self):
        """N=2000 / 100²：moving(k=32) 显著快于全局路径（结构性 O(M·k³) vs O(n³+M·n²)）。

        用比例而非绝对墙钟（跨机器稳定）：moving 应至少比 global 快 2×，
        且绝对值保持在秒级以内。
        """
        import time

        x, y, z = _arrays(2000, seed=37)
        gx = np.linspace(0, 1000, 100)
        gy = np.linspace(0, 1000, 100)

        t0 = time.perf_counter()
        _pure_numpy_kriging(x, y, z, gx, gy)
        t_global = time.perf_counter() - t0

        t0 = time.perf_counter()
        gz, gv, _ = _pure_numpy_kriging(
            x, y, z, gx, gy, max_neighbors=32, min_neighbors=8
        )
        t_moving = time.perf_counter() - t0

        assert np.isfinite(gz).all()
        assert t_moving < t_global / 2.0
        assert t_moving < 5.0  # 秒级上限（宽限 ~8× 于本机实测 ~0.6s）
