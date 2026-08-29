"""Mapping scientific-correctness regressions: CRS propagation (#1050),
IDW k-NN rewrite parity/performance (#1048), fallback CRS reprojection
(#1051) and the engine kriging dispatch contract (#1049)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import time

import numpy as np
import pytest

from paleo_workbench.mapping.geological_pipeline import (
    GeologicalFactor,
    GeologicalFactorDataset,
    IDWInterpolator,
    InterpolationOptions,
)
from paleo_workbench.mapping.layers import GridMapLayer, MapDocument
from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
    _flatten_qgis_style,
    make_crs_transformer,
    reproject_xy,
)
from paleo_workbench.project.models import (
    CoordinateReference,
    ProjectDocument,
    ProjectMeta,
    StratigraphicFramework,
    WellTable,
    WellTableRow,
)
from paleo_workbench.services.geological_mapping_service import GeologicalMappingService


# ---------------------------------------------------------------------------
# #1050: project.coordinate.project_crs must reach the factor dataset / map.
# ---------------------------------------------------------------------------

_UTM49N = "EPSG:32649"


def _project_with_wells(project_crs: str) -> ProjectDocument:
    rows = []
    for index in range(9):
        rows.append(
            WellTableRow(
                well_id=f"W{index + 1}",
                name=f"井-{index + 1}",
                x=500000.0 + (index % 3) * 1200.0,
                y=4400000.0 + (index // 3) * 900.0,
                z=1000.0 + index,
                H_s=12.0 + index,
                H_t=40.0 + index,
                attributes={"value": 8.0 + 2.5 * index},
            )
        )
    return ProjectDocument(
        meta=ProjectMeta(name="crs-regression"),
        coordinate=CoordinateReference(project_crs=project_crs),
        stratigraphy=StratigraphicFramework(target_horizon="T1"),
        well_tables=[WellTable(id="wt-1", name="T1 井表", target_horizon="T1", rows=rows)],
    )


def test_project_crs_propagates_to_factor_dataset() -> None:
    """ProjectDocument carries no `crs` attribute; the CRS lives at
    project.coordinate.project_crs and must reach the dataset (#1050)."""
    service = GeologicalMappingService()
    dataset = service.extract_well_factors(_project_with_wells(_UTM49N), "孔隙度")
    assert dataset.crs == _UTM49N
    assert len(dataset.valid_points) == 9
    # A descriptive alias spelling must propagate verbatim too.
    descriptive = service.extract_well_factors(
        _project_with_wells(f"{_UTM49N} / WGS84 UTM 49N"), "孔隙度"
    )
    assert descriptive.crs == f"{_UTM49N} / WGS84 UTM 49N"


def test_empty_project_crs_falls_back_to_4326() -> None:
    service = GeologicalMappingService()
    dataset = service.extract_well_factors(_project_with_wells(""), "孔隙度")
    assert dataset.crs == "EPSG:4326"


def test_project_crs_propagates_to_create_factor_map_output() -> None:
    """End to end: the produced MapDocument and its grid layer carry the
    project CRS instead of a hard-coded EPSG:4326."""
    service = GeologicalMappingService()
    map_doc, task = service.create_factor_map(
        _project_with_wells(_UTM49N),
        "孔隙度",
        method="idw",
        grid_n=12,
        include_contours=False,
        include_polygons=False,
    )
    assert isinstance(map_doc, MapDocument)
    assert map_doc.crs == _UTM49N
    grid_layers = [layer for layer in map_doc.layers if isinstance(layer, GridMapLayer)]
    assert grid_layers, "factor map must contain a grid layer"
    assert all(layer.crs == _UTM49N for layer in grid_layers)
    assert task.status == "complete"


# ---------------------------------------------------------------------------
# #1048: IDWInterpolator — cKDTree k-NN + chunked queries vs a naive O(M·N)
# mathematical reference, plus a performance regression.
# ---------------------------------------------------------------------------


def _naive_idw(
    target_pts: np.ndarray,
    sample_pts: np.ndarray,
    zs: np.ndarray,
    *,
    power: float = 2.0,
    search_radius: float | None = None,
    min_neighbors: int = 1,
    max_neighbors: int | None = None,
) -> np.ndarray:
    """Deliberately naive O(M·N) reference mirroring the legacy semantics.

    Top-k selection uses a full row sort (deterministic); with distinct
    distances this selects exactly the k nearest neighbours the production
    cKDTree path returns.
    """
    m, n = len(target_pts), len(zs)
    dx = target_pts[:, 0:1] - sample_pts[:, 0][None, :]
    dy = target_pts[:, 1:2] - sample_pts[:, 1][None, :]
    dist = np.sqrt(dx * dx + dy * dy)
    p = max(1.0, float(power))
    eps = 1e-12

    valid = np.ones_like(dist, dtype=bool)
    if search_radius is not None and search_radius > 0:
        valid = valid & (dist <= float(search_radius))
    if max_neighbors is not None and 0 < max_neighbors < n:
        k = int(max_neighbors)
        order = np.argsort(dist, axis=1)
        keep = np.zeros_like(valid)
        rows = np.arange(m)[:, None]
        keep[rows, order[:, :k]] = valid[rows, order[:, :k]]
        valid = valid & keep

    counts = valid.sum(axis=1)
    min_n = max(1, int(min_neighbors))
    weights = np.zeros_like(dist)
    np.divide(1.0, np.maximum(dist, eps) ** p, out=weights, where=valid)
    weights[~valid] = 0.0
    exact = (dist < eps) & valid
    weights[exact] = 0.0

    weight_sum = weights.sum(axis=1)
    out = np.full(m, np.nan)
    eligible = counts >= min_n
    positive = eligible & (weight_sum > 0)
    out[positive] = (weights[positive] * zs).sum(axis=1) / weight_sum[positive]
    hit_rows, hit_cols = np.nonzero(exact)
    for r, c in zip(hit_rows, hit_cols):
        if counts[r] >= min_n:
            out[r] = zs[c]
    return out


def _random_dataset(n: int = 15, seed: int = 7, *, lattice: bool = False) -> GeologicalFactorDataset:
    rng = np.random.default_rng(seed)
    dataset = GeologicalFactorDataset(
        factor_name="孔隙度", unit="%", target_horizon="T1", crs=_UTM49N
    )
    for index in range(n):
        if lattice:
            x = float((index % 5) * 100.0)
            y = float((index // 5) * 100.0)
        else:
            x = float(rng.uniform(0.0, 1000.0))
            y = float(rng.uniform(0.0, 1000.0))
        dataset.add_point(
            GeologicalFactor(
                name="孔隙度",
                value=float(8.0 + 30.0 * index / max(n - 1, 1)),
                unit="%",
                well_id=f"W{index + 1}",
                well_name=f"井-{index + 1}",
                x=x,
                y=y,
                crs=_UTM49N,
                formation="T1",
            )
        )
    return dataset


def _interpolated_grid(dataset: GeologicalFactorDataset, options: InterpolationOptions) -> np.ndarray:
    return np.asarray(IDWInterpolator().interpolate(dataset, options).grid_z, dtype=np.float64)


def _targets_for(dataset: GeologicalFactorDataset, grid_n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xmin, ymin, xmax, ymax = dataset.extent
    grid_x = np.linspace(xmin, xmax, grid_n, dtype=np.float64)
    grid_y = np.linspace(ymin, ymax, grid_n, dtype=np.float64)
    gx, gy = np.meshgrid(grid_x, grid_y)
    return np.stack([gx.ravel(), gy.ravel()], axis=1), grid_x, grid_y


def _assert_parity(dataset: GeologicalFactorDataset, grid_n: int, options: InterpolationOptions) -> None:
    target_pts, grid_x, grid_y = _targets_for(dataset, grid_n)
    xs, ys, zs = dataset.to_arrays()
    reference = _naive_idw(
        target_pts,
        np.stack([xs, ys], axis=1),
        zs,
        power=options.power,
        search_radius=options.search_radius,
        min_neighbors=options.min_neighbors,
        max_neighbors=options.max_neighbors,
    ).reshape(grid_n, grid_n)
    produced = _interpolated_grid(dataset, options)
    np.testing.assert_allclose(
        produced, reference, rtol=1e-5, atol=1e-4, equal_nan=True,
        err_msg=f"IDW parity failed for {options}",
    )


def test_idw_parity_default_all_neighbors() -> None:
    dataset = _random_dataset()
    _assert_parity(dataset, 13, InterpolationOptions(method="idw", grid_n=13, power=2.0))


def test_idw_parity_fractional_power() -> None:
    dataset = _random_dataset(seed=11)
    _assert_parity(dataset, 11, InterpolationOptions(method="idw", grid_n=11, power=1.5))


def test_idw_parity_max_neighbors() -> None:
    dataset = _random_dataset(seed=23)
    _assert_parity(
        dataset, 13, InterpolationOptions(method="idw", grid_n=13, max_neighbors=3)
    )


def test_idw_parity_search_radius_nodata_boundary() -> None:
    """Cells with no sample inside the radius must stay NaN nodata."""
    dataset = _random_dataset(seed=31)
    options = InterpolationOptions(method="idw", grid_n=17, search_radius=180.0)
    grid = _interpolated_grid(dataset, options)
    assert np.isnan(grid).any(), "radius pruning must leave nodata cells"
    _assert_parity(dataset, 17, options)


def test_idw_parity_radius_plus_knn() -> None:
    dataset = _random_dataset(seed=47)
    options = InterpolationOptions(
        method="idw", grid_n=15, search_radius=320.0, max_neighbors=4
    )
    _assert_parity(dataset, 15, options)


def test_idw_parity_min_neighbors_gate() -> None:
    dataset = _random_dataset(seed=59)
    options = InterpolationOptions(method="idw", grid_n=17, search_radius=260.0, min_neighbors=6)
    grid = _interpolated_grid(dataset, options)
    assert np.isnan(grid).any(), "min_neighbors gate must leave nodata cells"
    _assert_parity(dataset, 17, options)


def test_idw_exact_sample_hit_takes_sample_value() -> None:
    """A grid node coinciding with a well returns the well value (#1048
    boundary contract: exact hits skip the weighted mean and win over the
    weighted average of the remaining neighbours)."""
    from paleo_workbench.mapping.geological_pipeline.interpolator import _idw_all_neighbors

    samples = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [10.0, 10.0]])
    zs = np.array([8.0, 12.0, 16.0, 20.0])
    targets = np.array([[0.0, 0.0], [10.0, 10.0], [5.0, 5.0], [3.0, 4.0]])

    out = _idw_all_neighbors(targets, samples, zs, p=2.0, eps=1e-12, min_n=1)
    assert out[0] == pytest.approx(8.0)  # exact hit overrides the weighted mean
    assert out[1] == pytest.approx(20.0)
    assert out[2] == pytest.approx(14.0)  # symmetric centre: plain mean
    np.testing.assert_allclose(
        out, _naive_idw(targets, samples, zs), rtol=1e-12, equal_nan=True
    )

    engine = IDWInterpolator()
    out_knn = engine._idw_knn(targets, samples, zs, k=2, radius=None, p=2.0, eps=1e-12, min_n=1)
    assert out_knn[0] == pytest.approx(8.0)  # exact hit survives the k-NN cut
    assert out_knn[1] == pytest.approx(20.0)
    np.testing.assert_allclose(
        out_knn, _naive_idw(targets, samples, zs, max_neighbors=2),
        rtol=1e-12, equal_nan=True,
    )


def test_idw_performance_2000_wells_200x200_grid() -> None:
    """>#1048 regression: 2000 wells onto a 200×200 grid must stay well under
    the 5 s budget (the legacy (M, N) full-matrix path far exceeded it)."""
    dataset = _random_dataset(n=2000, seed=2024)
    options = InterpolationOptions(method="idw", grid_n=200, power=2.0)
    started = time.perf_counter()
    result = IDWInterpolator().interpolate(dataset, options)
    elapsed = time.perf_counter() - started
    assert result.grid_z.shape == (200, 200)
    assert np.isfinite(result.grid_z).any()
    assert elapsed < 5.0, f"IDW 2000×(200×200) took {elapsed:.2f}s (budget 5s)"


# ---------------------------------------------------------------------------
# #1051: fallback renderer CRS reprojection / warnings.
# ---------------------------------------------------------------------------


def test_make_crs_transformer_identity_and_mismatch() -> None:
    assert make_crs_transformer("EPSG:4326", "EPSG:4326") is None
    # Descriptive project spelling ("EPSG:4326 / WGS84") is the same CRS.
    assert make_crs_transformer("EPSG:4326", "EPSG:4326 / WGS84") is None
    transformer = make_crs_transformer("EPSG:4326", "EPSG:3857")
    assert transformer is not None


def test_make_crs_transformer_rejects_unresolvable_crs() -> None:
    with pytest.raises(ValueError):
        make_crs_transformer("DEFINITELY-NOT-A-CRS-42", "EPSG:3857")


def test_reproject_xy_known_points() -> None:
    """:func:`reproject_xy` converts lon/lat to Web Mercator: (0, 0) stays the
    origin and Beijing (116°E, 40°N) lands near (12.9 M, 4.87 M)."""
    transformer = make_crs_transformer("EPSG:4326", "EPSG:3857")
    assert transformer is not None
    out = reproject_xy(np.array([[0.0, 0.0], [116.0, 40.0]]), transformer)
    assert out.shape == (2, 2)
    assert out[0, 0] == pytest.approx(0.0, abs=1e-6)
    assert out[0, 1] == pytest.approx(0.0, abs=1e-6)
    assert out[1, 0] == pytest.approx(12_913_833.0, rel=1e-3)
    assert out[1, 1] == pytest.approx(4_865_942.0, rel=1e-3)


def _point_layer(crs: str, layer_id: str = "pts", name: str = "Points") -> MapLayerSnapshot:
    return MapLayerSnapshot(
        id=layer_id,
        name=name,
        layer_type="vector",
        extent=(115.9, 39.9, 116.1, 40.1),
        crs=crs,
        data_revision=1,
        style_revision=1,
        features=(
            {
                "id": "p1",
                "geometry": {"type": "Point", "coordinates": [116.0, 40.0]},
                "properties": {"name": "BJ"},
            },
        ),
        # Point markers paint through the stroke colour on the batch-dot
        # path — use an unmistakable marker colour for pixel assertions.
        style={"fill": "#ff5500", "stroke": "#ff5500", "marker_size": 8.0},
    )


def test_fallback_reprojects_foreign_crs_vector_layer() -> None:
    """A 4326 point layer in a 3857 project reprojects silently (no warning)
    and lands at the same pixel as the equivalent pre-projected layer."""
    projected = make_crs_transformer("EPSG:4326", "EPSG:3857").transform(116.0, 40.0)

    foreign = FallbackMapRenderBackend()
    foreign.initialize()
    foreign.set_layer_snapshot(
        MapRenderSnapshot(project_crs="EPSG:3857", layers=(_point_layer("EPSG:4326"),))
    )
    foreign.set_extent((projected[0] - 2000.0, projected[1] - 2000.0,
                        projected[0] + 2000.0, projected[1] + 2000.0))
    foreign.set_output_size(200, 200)
    foreign.set_dpi(96.0)
    frame_foreign = foreign.render_sync()
    assert foreign.crs_warnings == []

    equivalent = MapLayerSnapshot(
        id="pts3857",
        name="Points3857",
        layer_type="vector",
        extent=(projected[0] - 0.02, projected[1] - 0.02, projected[0] + 0.02, projected[1] + 0.02),
        crs="EPSG:3857",
        data_revision=1,
        style_revision=1,
        features=(
            {
                "id": "p1",
                "geometry": {"type": "Point", "coordinates": [float(projected[0]), float(projected[1])]},
                "properties": {"name": "BJ"},
            },
        ),
        style={"fill": "#ff5500", "stroke": "#ff5500", "marker_size": 8.0},
    )
    native = FallbackMapRenderBackend()
    native.initialize()
    native.set_layer_snapshot(
        MapRenderSnapshot(project_crs="EPSG:3857", layers=(equivalent,))
    )
    native.set_extent((projected[0] - 2000.0, projected[1] - 2000.0,
                       projected[0] + 2000.0, projected[1] + 2000.0))
    native.set_output_size(200, 200)
    native.set_dpi(96.0)
    frame_native = native.render_sync()
    assert native.crs_warnings == []

    # The reprojected marker must sit within 1 px of the native one.
    assert _marker_center(frame_foreign, 200) == pytest.approx(
        _marker_center(frame_native, 200), abs=1.0
    )


def _marker_center(frame, size: int) -> tuple[float, float]:
    array = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(frame.height, frame.stride // 4, 4)
    # Red marker on dark background: select strongly-red, weak-blue pixels.
    mask = (array[:, :, 0].astype(int) - array[:, :, 2].astype(int)) > 80
    ys, xs = np.nonzero(mask)
    assert xs.size > 0, "marker must be visible in the frame"
    return (float(xs.mean()), float(ys.mean()))


def test_fallback_warns_when_reprojection_unavailable() -> None:
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(
        MapRenderSnapshot(
            project_crs="EPSG:3857",
            layers=(_point_layer("DEFINITELY-NOT-A-CRS-42", name="BadLayer"),),
        )
    )
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(64, 64)
    backend.set_dpi(96.0)
    frame = backend.render_sync()
    # Degraded draw: the frame renders, but the mismatch is NOT silent.
    assert (frame.width, frame.height) == (64, 64)
    assert len(backend.crs_warnings) == 1
    assert "BadLayer" in backend.crs_warnings[0]
    assert "降级" in backend.crs_warnings[0]


def test_fallback_warns_raster_layer_not_reprojected() -> None:
    raster = MapLayerSnapshot(
        id="basemap",
        name="Basemap",
        layer_type="raster_source",
        extent=(115.9, 39.9, 116.1, 40.1),
        crs="EPSG:4326",
        data_revision=1,
        style_revision=1,
        features=(),
        renderer_payload="/nonexistent/basemap.tif",
    )
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(
        MapRenderSnapshot(project_crs="EPSG:3857", layers=(raster,))
    )
    backend.set_extent((0.0, 0.0, 20.0, 20.0))
    backend.set_output_size(64, 64)
    backend.set_dpi(96.0)
    backend.render_sync()
    assert len(backend.crs_warnings) == 1
    assert "Basemap" in backend.crs_warnings[0]
    assert "未重投影" in backend.crs_warnings[0]


def test_fallback_empty_layer_crs_counts_as_project_crs() -> None:
    """Empty layer.crs must not trigger reprojection or warnings."""
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(
        MapRenderSnapshot(
            project_crs="EPSG:3857", layers=(_point_layer("", name="Inherit"),)
        )
    )
    backend.set_extent((115.9, 39.9, 116.1, 40.1))
    backend.set_output_size(64, 64)
    backend.set_dpi(96.0)
    backend.render_sync()
    assert backend.crs_warnings == []


def test_fallback_crs_warnings_describe_current_frame_only() -> None:
    """Warnings are rebuilt per composition: replacing the foreign layer with
    a matching one clears the stale entry (and the frame cache key sees
    layer.crs, so a CRS-only change re-renders)."""
    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(
        MapRenderSnapshot(
            project_crs="EPSG:3857", layers=(_point_layer("EPSG:4326", name="Foreign"),)
        )
    )
    backend.set_extent((12_911_833.0, 4_863_942.0, 12_915_833.0, 4_867_942.0))
    backend.set_output_size(64, 64)
    backend.set_dpi(96.0)
    backend.render_sync()
    assert backend.crs_warnings == []
    # Swap to an unresolvable CRS on the SAME layer id: frame cache must not
    # hide it (layer.crs participates in the cache key).
    backend.set_layer_snapshot(
        MapRenderSnapshot(
            project_crs="EPSG:3857",
            layers=(_point_layer("DEFINITELY-NOT-A-CRS-42", name="Foreign"),),
        )
    )
    backend.render_sync()
    assert len(backend.crs_warnings) == 1
    # And back to a matching CRS clears the warning again.
    backend.set_layer_snapshot(
        MapRenderSnapshot(
            project_crs="EPSG:3857", layers=(_point_layer("EPSG:3857", name="Foreign"),)
        )
    )
    backend.render_sync()
    assert backend.crs_warnings == []


# ---------------------------------------------------------------------------
# #1049: engine-side kriging dispatch contract.
# ---------------------------------------------------------------------------


def _load_local_engine_interpolation():
    """Load THIS worktree's engine interpolation module by path.

    run_env.sh puts the shared main-worktree engine on PYTHONPATH, so a
    plain import could resolve elsewhere; the contract under test is the
    submodule copy shipped with this repository.
    """
    engine_file = (
        Path(__file__).resolve().parents[1]
        / "geo-viz-engine"
        / "packages"
        / "geoviz_plots"
        / "geoviz_plots"
        / "factor"
        / "interpolation.py"
    )
    assert engine_file.exists(), f"engine submodule missing at {engine_file}"
    spec = importlib.util.spec_from_file_location("_pwb_local_interpolation", engine_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_engine_kriging_labels_dispatch_to_real_kriging() -> None:
    module = _load_local_engine_interpolation()
    mapping = module._METHOD_BACKEND
    assert mapping["克里金"] == "kriging"
    assert mapping["克里金(MVP·线性)"] == "kriging"
    for label, backend in mapping.items():
        if "克里金" in label:
            assert backend == "kriging", (
                f"UI label {label!r} must dispatch to real kriging, got {backend!r}"
            )
    # Runtime dispatcher agrees with the table.
    assert module.method_to_backend("克里金") == "kriging"
    assert module.method_to_backend("克里金(MVP·线性)") == "kriging"
    # The SciPy linear backend stays reachable under its own engine name.
    assert module.method_to_backend("linear") == "linear"

