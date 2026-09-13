"""V12-B 编图计算核黄金值基线：确定性数据集 → 现状输出快照 + 墙钟计时。

用法（在 geopipeline-v12 worktree 根目录）::

    .venv/bin/python scripts/geopipeline_v12_golden.py generate \
        --out tests/data/geopipeline_golden
    .venv/bin/python scripts/geopipeline_v12_golden.py compare \
        --against tests/data/geopipeline_golden

``generate`` 用当前代码把每个案例的输出（网格 float32 原始字节 / 多边形与
等值线的规范化 JSON）落盘并记录 SHA-256 与耗时；``compare`` 用当前代码重算
并逐案例比对。默认路径（未启用邻域参数）要求**字节级一致**——这是本 Goal
"数值保真"的第一道闸门：性能改造不得扰动默认输出的任何一位。

数据集全部由固定种子生成（见 ``_samples``），跨机器可复现。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path

import numpy as np

# 黄金值钉的是**纯 numpy 回退路径**（本 Goal 的优化对象）。geoviz 是否可导入
# 取决于环境（例如 site-packages 里出现 matplotlib 会让经 editable 安装指向
# 的 geoviz_plots 导入成功），这会静默把 KrigingInterpolator 切到引擎路径、
# 让基线比对失真。这里显式挡掉 geoviz，保证脚本在任何环境下钉同一实现。
sys.modules.setdefault("geoviz", None)  # None in sys.modules → import geoviz 即 ImportError

from paleo_workbench.mapping.geological_pipeline.interpolator import (
    IDWInterpolator,
    KrigingInterpolator,
)
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.mapping.geological_pipeline.polygonization import (
    generate_facies_polygon_layer,
)
from paleo_workbench.mapping.geological_pipeline.contouring import (
    generate_contour_layer,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult

# ---------------------------------------------------------------------------
# Deterministic synthetic datasets (V12-B golden baseline)
# ---------------------------------------------------------------------------

BASE_SEED = 20260913
FIELD_EXTENT = (0.0, 0.0, 1000.0, 1000.0)


def _field(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Smooth trend + sinusoidal structure: a field with a real variogram."""
    return (
        5.0
        + 0.004 * x
        + 0.002 * y
        + 3.0 * np.sin(x / 150.0) * np.cos(y / 180.0)
        + 1.5 * np.cos((x + y) / 260.0)
    )


def _samples(n: int, seed_offset: int, nodata_frac: float = 0.0):
    rng = np.random.default_rng(BASE_SEED + seed_offset)
    x = rng.uniform(20.0, 980.0, n)
    y = rng.uniform(20.0, 980.0, n)
    z = _field(x, y) + rng.normal(0.0, 0.8, n)
    if nodata_frac > 0.0:
        # 井点级 nodata：非有限值被 valid_points 过滤（Inferred Null 语义）
        drop = rng.random(n) < nodata_frac
        z = np.where(drop, np.nan, z)
    return x, y, z


def _dataset(n: int, seed_offset: int, nodata_frac: float = 0.0) -> GeologicalFactorDataset:
    x, y, z = _samples(n, seed_offset, nodata_frac)
    ds = GeologicalFactorDataset(factor_name="golden_factor", unit="m", crs="EPSG:32650")
    for i in range(n):
        ds.add_point(
            GeologicalFactor(
                name="golden_factor",
                value=float(z[i]),
                unit="m",
                well_id=f"W{i:05d}",
                x=float(x[i]),
                y=float(y[i]),
                crs="EPSG:32650",
            )
        )
    return ds


_BOUNDARY_RING = [
    (150.0, 180.0), (520.0, 120.0), (860.0, 260.0), (900.0, 620.0),
    (640.0, 880.0), (300.0, 850.0), (110.0, 520.0), (150.0, 180.0),
]


def _interp_cases() -> list[dict]:
    cases = []
    for method, tag in ((KrigingInterpolator, "krig"), (IDWInterpolator, "idw")):
        for n, g in ((50, 50), (500, 50), (2000, 50), (500, 200), (500, 300), (50, 300)):
            cases.append({
                "kind": "interp", "name": f"{tag}_n{n}_g{g}",
                "engine": method, "n": n, "grid_n": g, "seed_offset": n,
                "nodata_frac": 0.0, "boundary": None,
            })
    # 边界多边形（D6 域掩膜 → 网格出现 nodata 单元）
    for tag in ("krig", "idw"):
        cases.append({
            "kind": "interp", "name": f"{tag}_n500_g50_boundary",
            "engine": KrigingInterpolator if tag == "krig" else IDWInterpolator,
            "n": 500, "grid_n": 50, "seed_offset": 500,
            "nodata_frac": 0.0, "boundary": _BOUNDARY_RING,
        })
    # 各向异性声明（回退路径不消费 → 输出必须与未声明案例逐位一致）
    cases.append({
        "kind": "interp", "name": "krig_n500_g50_aniso_declared",
        "engine": KrigingInterpolator, "n": 500, "grid_n": 50, "seed_offset": 500,
        "nodata_frac": 0.0, "boundary": None,
        "extra_opts": {"anisotropy_angle": 30.0, "anisotropy_ratio": 2.5},
    })
    # 井点级 nodata（valid_points 过滤后有效样本约 90%）
    for tag in ("krig", "idw"):
        cases.append({
            "kind": "interp", "name": f"{tag}_n500_g50_nodata",
            "engine": KrigingInterpolator if tag == "krig" else IDWInterpolator,
            "n": 500, "grid_n": 50, "seed_offset": 501,
            "nodata_frac": 0.1, "boundary": None,
        })
    return cases


def _run_interp(case: dict) -> tuple[FactorGridResult, float]:
    ds = _dataset(case["n"], case["seed_offset"], case["nodata_frac"])
    opts = InterpolationOptions(
        method="kriging" if case["name"].startswith("krig") else "idw",
        grid_n=case["grid_n"],
        boundary=[(float(px), float(py)) for px, py in case["boundary"]] if case["boundary"] else None,
        **case.get("extra_opts", {}),
    )
    engine = case["engine"]()
    t0 = time.perf_counter()
    result = engine.interpolate(ds, opts)
    elapsed = time.perf_counter() - t0
    return result, elapsed


# ---------------------------------------------------------------------------
# Polygonization / contouring golden grids
# ---------------------------------------------------------------------------

def _polygon_grid(kind: str, size: int) -> np.ndarray:
    rng = np.random.default_rng(BASE_SEED + 7000 + size)
    if kind == "speckle":
        return rng.normal(0.0, 1.0, (size, size))
    # 平滑场： sigma 随尺寸缩放，跨尺度结构一致
    from scipy.ndimage import gaussian_filter
    return gaussian_filter(rng.normal(0.0, 1.0, (size, size)), sigma=max(2.0, size / 12.0))


def _grid_result(z: np.ndarray) -> FactorGridResult:
    n = z.shape[0]
    return FactorGridResult(
        grid_z=z.astype(np.float32),
        grid_x=np.linspace(0.0, float(n), n),
        grid_y=np.linspace(0.0, float(n), n),
        factor_name="golden_factor",
        algorithm_id="idw",
        algorithm_parameters={"method": "idw"},
        crs="EPSG:32650",
    )


def _polygon_cases() -> list[dict]:
    out = []
    for size in (50, 100, 150):  # speckle：洞/外环数量随尺寸超线性增长的最坏场
        out.append({"kind": "polygon", "name": f"poly_speckle_{size}", "field": "speckle", "size": size})
    for size in (200, 300):  # 平滑场：常规操作的大网格
        out.append({"kind": "polygon", "name": f"poly_smooth_{size}", "field": "smooth", "size": size})
    return out


def _contour_cases() -> list[dict]:
    return [
        {"kind": "contour", "name": f"contour_smooth_{size}", "field": "smooth", "size": size}
        for size in (100, 200, 300)
    ]


# ---------------------------------------------------------------------------
# Canonical serialization + digests
# ---------------------------------------------------------------------------

def _canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _layer_payload(layer) -> dict:
    """Polygon/ContourMapLayer → 可比对的纯数据投影（顺序即产出顺序）。"""
    features = []
    for f in layer.features:
        features.append({"geometry": f["geometry"], "properties": f["properties"]})
    payload = {
        "features": features,
        "metadata": dict(layer.metadata),
    }
    categories = getattr(layer, "categories", None)
    if categories:
        payload["categories"] = [dict(c) for c in categories]
    levels = getattr(layer, "levels", None)
    if levels is not None:
        payload["levels"] = [float(v) for v in levels]
    return payload


# ---------------------------------------------------------------------------
# generate / compare
# ---------------------------------------------------------------------------

def _machine_info() -> dict:
    try:
        blas = np.show_config(mode="dicts")
        blas_name = (
            blas.get("Build Dependencies", {}).get("blas", {}).get("name", "unknown")
        )
    except Exception:
        blas_name = "unknown"
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "blas": blas_name,
        "machine": platform.machine(),
        "platform": platform.platform(),
    }


def _iter_all_cases():
    return _interp_cases() + _polygon_cases() + _contour_cases()


def _compute_case(case: dict) -> tuple[dict, float]:
    """Run one case with the CURRENT code; return (payload-for-digest, seconds)."""
    if case["kind"] == "interp":
        result, elapsed = _run_interp(case)
        params = {
            k: v for k, v in result.algorithm_parameters.items() if k != "sample_points"
        }
        payload = {
            "algorithm_id": result.algorithm_id,
            "grid_z": result.grid_z,
            "variance_grid": result.variance_grid,
            "grid_x": result.grid_x,
            "grid_y": result.grid_y,
            "params": params,
            "statistics": result.statistics.to_dict(),
        }
        return payload, elapsed
    if case["kind"] == "polygon":
        z = _polygon_grid(case["field"], case["size"])
        grid = _grid_result(z)
        t0 = time.perf_counter()
        layer = generate_facies_polygon_layer(
            grid, layer_id="golden_poly", name="golden_poly"
        )
        elapsed = time.perf_counter() - t0
        return {"layer": _layer_payload(layer)}, elapsed
    if case["kind"] == "contour":
        z = _polygon_grid(case["field"], case["size"])
        grid = _grid_result(z)
        t0 = time.perf_counter()
        layer = generate_contour_layer(grid, layer_id="golden_contour", name="golden_contour")
        elapsed = time.perf_counter() - t0
        return {"layer": _layer_payload(layer)}, elapsed
    raise ValueError(f"unknown case kind: {case['kind']}")


def _serialize_payload(case: dict, payload: dict) -> dict[str, bytes]:
    """Payload → on-disk artifacts (name → bytes)."""
    out: dict[str, bytes] = {}
    if case["kind"] == "interp":
        arrays = {
            "grid_z": payload["grid_z"],
            "grid_x": payload["grid_x"],
            "grid_y": payload["grid_y"],
        }
        if payload["variance_grid"] is not None:
            arrays["variance_grid"] = payload["variance_grid"]
        from io import BytesIO

        buf = BytesIO()
        np.savez_compressed(buf, **arrays)
        out[f"{case['name']}.npz"] = buf.getvalue()
        meta = {
            "algorithm_id": payload["algorithm_id"],
            "params": payload["params"],
            "statistics": payload["statistics"],
        }
        out[f"{case['name']}.json"] = _canonical_json(meta)
    else:
        body = _canonical_json(payload["layer"])
        out[f"{case['name']}.json.gz"] = gzip.compress(body, mtime=0)
    return out


def _load_payload(case: dict, root: Path) -> dict | None:
    """Read stored artifacts back into the in-memory payload shape."""
    if case["kind"] == "interp":
        npz_path = root / f"{case['name']}.npz"
        json_path = root / f"{case['name']}.json"
        if not npz_path.exists() or not json_path.exists():
            return None
        with np.load(npz_path) as npz:
            payload = {k: npz[k] for k in npz.files}
        payload["variance_grid"] = payload.get("variance_grid")
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        payload["algorithm_id"] = meta["algorithm_id"]
        payload["params"] = meta["params"]
        payload["statistics"] = meta["statistics"]
        return payload
    gz_path = root / f"{case['name']}.json.gz"
    if not gz_path.exists():
        return None
    return {"layer": json.loads(gzip.decompress(gz_path.read_bytes()).decode("utf-8"))}


# 比对策略（V12-B 黄金值契约）：
# * IDW 网格 / 多边形 / 等值线 / 算法参数标量 —— 字节级一致（确定性代码路径）。
# * 克里金网格（z + 方差）—— 大案例的线程化 BLAS 会按缓冲区对齐选择内核，
#   同一代码两次运行的末位比特可差 ~1e-7（float32 存储）。因此克里金网格
#   允许 max|Δ| ≤ KRIGING_GRID_ATOL（论证见 docs/development/geopipeline-v12/
#   03-verification.md：值域 O(1..100)，1e-5 是内核噪声（实测 9.5e-7）的
#   ~10 倍余量，任何真实的邻域/求解语义改动都远大于此）。摘要仍报告实际差异。
KRIGING_GRID_ATOL = 1e-5
KRIGING_STAT_RTOL = 1e-6


def _compare_payload(case: dict, stored: dict, fresh: dict) -> tuple[list[str], list[str]]:
    """Compare everything the golden baseline pins down.

    Default paths (no neighborhood opt-in) must reproduce the baseline:
    byte-exact everywhere except kriging grids, which tolerate last-bit
    threaded-BLAS kernel noise within an explicitly justified atol. Returns
    (failures, notes); notes document in-tolerance drift, failures gate.
    """
    failures: list[str] = []
    notes: list[str] = []
    is_kriging = case["kind"] == "interp" and "krig" in case["name"]
    if case["kind"] == "interp":
        for key in ("grid_z", "variance_grid", "grid_x", "grid_y"):
            a, b = stored.get(key), fresh.get(key)
            if (a is None) != (b is None):
                failures.append(f"{key}: presence changed ({a is not None} -> {b is not None})")
                continue
            if a is None:
                continue
            if a.shape != b.shape:
                failures.append(f"{key}: shape {a.shape} -> {b.shape}")
                continue
            if a.tobytes() != b.tobytes():
                nan_a, nan_b = int(np.isnan(a).sum()), int(np.isnan(b).sum())
                diff = float(np.nanmax(np.abs(a.astype("f8") - b.astype("f8")))) if nan_a == nan_b else math.inf
                if is_kriging and nan_a == nan_b and diff <= KRIGING_GRID_ATOL:
                    notes.append(f"{key}: bytes differ, max|Δ|={diff:.3e} (within kriging atol)")
                    continue
                failures.append(
                    f"{key}: bytes differ, max|Δ|={diff:.3e}, NaN cells {nan_a}->{nan_b}"
                )
        if _canonical_json(stored["params"]) != _canonical_json(fresh["params"]):
            if is_kriging and _floats_close(stored["params"], fresh["params"]):
                notes.append("algorithm_parameters differ only within float tolerance")
            else:
                failures.append("algorithm_parameters JSON mismatch")
        if _canonical_json(stored["statistics"]) != _canonical_json(fresh["statistics"]):
            if is_kriging and _floats_close(stored["statistics"], fresh["statistics"], rtol=KRIGING_STAT_RTOL):
                notes.append("statistics differ only within float tolerance")
            else:
                failures.append("statistics JSON mismatch")
    else:
        if _canonical_json(stored["layer"]) != _canonical_json(fresh["layer"]):
            failures.append("layer canonical JSON mismatch")
    return failures, notes


def _floats_close(a, b, rtol: float = 1e-9, depth: int = 0) -> bool:
    """Structural float comparison with tolerance for nested dict/list values."""
    if depth > 8:
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(
            _floats_close(a[k], b[k], rtol, depth + 1) for k in a
        )
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(
            _floats_close(x, y, rtol, depth + 1) for x, y in zip(a, b)
        )
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=rtol, abs_tol=1e-12)
    return a == b


def generate(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"machine": _machine_info(), "cases": {}}
    for case in _iter_all_cases():
        payload, elapsed = _compute_case(case)
        artifacts = _serialize_payload(case, payload)
        digests = {}
        for name, blob in artifacts.items():
            (out_dir / name).write_bytes(blob)
            digests[name] = _digest(blob)
        manifest["cases"][case["name"]] = {
            "kind": case["kind"],
            "seconds": round(elapsed, 4),
            "digests": digests,
        }
        print(f"  {case['name']:36s} {elapsed:9.3f}s  {len(artifacts)} artifact(s)")
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"manifest → {manifest_path}")
    return 0


def compare(against: Path) -> int:
    manifest = json.loads((against / "manifest.json").read_text(encoding="utf-8"))
    failures = 0
    header = f"{'case':36s} {'result':8s} {'now':>9s} {'baseline':>9s}"
    print(header)
    print("-" * len(header))
    for case in _iter_all_cases():
        name = case["name"]
        base_info = manifest["cases"].get(name)
        if base_info is None:
            print(f"{name:36s} MISSING  (no baseline entry)")
            failures += 1
            continue
        stored = _load_payload(case, against)
        if stored is None:
            print(f"{name:36s} MISSING  (artifact files absent)")
            failures += 1
            continue
        fresh, elapsed = _compute_case(case)
        case_failures, notes = _compare_payload(case, stored, fresh)
        speedup = base_info["seconds"] / elapsed if elapsed > 0 else math.inf
        if case_failures:
            failures += 1
            print(f"{name:36s} FAIL     {elapsed:8.3f}s {base_info['seconds']:8.3f}s")
            for p in case_failures:
                print(f"    ! {p}")
        else:
            note = f"  ({speedup:.1f}x faster)" if speedup > 1.05 else ""
            print(f"{name:36s} OK       {elapsed:8.3f}s {base_info['seconds']:8.3f}s{note}")
        for n in notes:
            print(f"    ~ {n}")
    print()
    if failures:
        print(f"{failures} case(s) FAILED golden comparison")
        return 1
    print("all golden cases byte-identical (or within stated tolerance policy: default paths are byte-exact)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--out", type=Path, required=True)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--against", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.cmd == "generate":
        return generate(args.out)
    return compare(args.against)


if __name__ == "__main__":
    sys.exit(main())
