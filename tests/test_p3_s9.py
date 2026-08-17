"""P3 session-9 regressions: coherence fallback, authoring dirty path, LAS load."""

from __future__ import annotations

import inspect
import threading
import time

import numpy as np
import pytest
from PySide6.QtCore import Qt

from geoviz import CurveData, WellLogData

from paleo_workbench.mapping.map_authoring import MapAuthoringDocument
from paleo_workbench.mapping.map_document_snapshot import document_render_snapshot
from paleo_workbench.mapping.map_scene_adapter import LegacyDocumentSceneAdapter
from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.native_backend import _py_compute_coherence_3d, disabled_acceleration
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.stratigraphy_correlation_page import StratigraphyCorrelationPage
from paleo_workbench.viz.seismic_3d_api import HAS_CPP_SEISMIC, compute_coherence_3d


def _independent_window_coherence(volume, inline_window, crossline_window, sample_window):
    """Reference: per-window recompute (the pre-#621 k-loop math)."""
    vol = np.asarray(volume, dtype=np.float32)
    ni, nx, nt = vol.shape
    coh = np.ones_like(vol, dtype=np.float32)
    hi = inline_window // 2
    hx = crossline_window // 2
    ht = sample_window // 2
    n_spatial = float((2 * hi + 1) * (2 * hx + 1))
    for i in range(hi, ni - hi):
        for j in range(hx, nx - hx):
            sub = vol[i - hi : i + hi + 1, j - hx : j + hx + 1, :].astype(np.float64)
            mean_sq = (np.sum(sub, axis=(0, 1)) / n_spatial) ** 2
            sum_sq = np.sum(sub**2, axis=(0, 1))
            for k in range(nt):
                k0 = max(0, k - ht)
                k1 = min(nt - 1, k + ht)
                vert_len = float(k1 - k0 + 1)
                run_num = np.sum(mean_sq[k0 : k1 + 1])
                run_den = np.sum(sum_sq[k0 : k1 + 1]) / vert_len + 1e-12
                value = run_num / run_den
                if isinstance(value, float) and value != value:
                    coh[i, j, k] = 0.0
                else:
                    coh[i, j, k] = float(np.clip(value, 0.0, 1.0))
    return coh


def test_python_coherence_fallback_has_no_per_sample_k_loop():
    """#621: the fallback must not re-reduce every sample in a Python k-loop."""
    src = inspect.getsource(_py_compute_coherence_3d)
    assert "for k in range(nt)" not in src
    assert "for k in range(" not in src


def test_python_coherence_overflow_recovers_like_independent_windows():
    """#621: prefix-sum carry of 1e40 must not wipe later finite windows."""
    vol = np.arange(5 * 5 * 12, dtype=np.float32).reshape(5, 5, 12) / 100.0
    vol[2, 2, 6] = 1e20
    out = _py_compute_coherence_3d(vol, 3, 3, 3)
    ref = _independent_window_coherence(vol, 3, 3, 3)
    np.testing.assert_allclose(out, ref, rtol=1e-6, atol=1e-6)
    assert out[2, 2, 8:].min() > 0.0


def test_python_coherence_inf_and_nan_recover_like_independent_windows():
    vol = np.arange(5 * 5 * 12, dtype=np.float32).reshape(5, 5, 12) / 100.0
    poisoned = vol.copy()
    poisoned[2, 2, 6] = np.inf
    out = _py_compute_coherence_3d(poisoned, 3, 3, 3)
    ref = _independent_window_coherence(poisoned, 3, 3, 3)
    np.testing.assert_allclose(out, ref, rtol=1e-6, atol=1e-6)
    assert (out == 0.0).sum() == 9 * 3
    assert out[2, 2, 8:].min() > 0.0

    poisoned[2, 2, 6] = np.nan
    out = _py_compute_coherence_3d(poisoned, 3, 3, 3)
    ref = _independent_window_coherence(poisoned, 3, 3, 3)
    np.testing.assert_allclose(out, ref, rtol=1e-6, atol=1e-6)
    assert out[2, 2, 8:].min() > 0.0


@pytest.mark.skipif(not HAS_CPP_SEISMIC, reason="seismic_3d_core not built")
def test_python_coherence_overflow_matches_cpp_outside_window():
    """Keep C++ overflow-recovery parity (the s8 prefix-sum regression)."""
    vol = np.arange(5 * 5 * 12, dtype=np.float32).reshape(5, 5, 12) / 100.0
    vol[2, 2, 6] = 1e20
    cpp = compute_coherence_3d(vol, 3, 3, 3)
    with disabled_acceleration():
        py = compute_coherence_3d(vol, 3, 3, 3)
    np.testing.assert_allclose(cpp[:, :, :5], py[:, :, :5], rtol=1e-5, atol=1e-6)
    np.testing.assert_allclose(cpp[:, :, 8:], py[:, :, 8:], rtol=1e-5, atol=1e-6)
    assert cpp[2, 2, 8:].min() > 0.0
    assert py[2, 2, 8:].min() > 0.0


def test_python_coherence_fallback_stays_under_two_seconds_at_scale():
    """#621: 64x64x400 must not pay a Python k-loop (~minutes at survey scale)."""
    rng = np.random.default_rng(4)
    vol = rng.standard_normal((64, 64, 400)).astype(np.float32)
    t0 = time.perf_counter()
    out = _py_compute_coherence_3d(vol, 3, 3, 3)
    elapsed = time.perf_counter() - t0
    assert out.shape == vol.shape
    assert out.dtype == np.float32
    assert elapsed < 2.0, f"fallback took {elapsed:.2f}s"


def test_records_materialize_only_the_dirty_layer(monkeypatch):
    """#625: one-layer edit must not _thaw every feature in the document."""
    import paleo_workbench.mapping.map_authoring as ma

    kinds: list[str] = []
    orig = ma.feature_to_record

    def spy(feature, *, kind):
        kinds.append(kind)
        return orig(feature, kind=kind)

    monkeypatch.setattr(ma, "feature_to_record", spy)
    records = [
        {
            "id": f"f{i}",
            "kind": "facies",
            "name": "delta",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]],
            },
        }
        for i in range(80)
    ]
    authoring = MapAuthoringDocument(document_id="map-p3", records=records)
    authoring.records()
    kinds.clear()
    session = authoring.start_editing("well")
    session.add_feature(VectorFeature("w1", {"type": "Point", "coordinates": [1.0, 2.0]}))
    converted = authoring.records()
    assert "facies" not in kinds
    assert kinds.count("well") == 1
    assert any(row["id"] == "w1" for row in converted)


def test_snapshot_and_adapter_rebuild_only_the_edited_layer(monkeypatch):
    """#625: unchanged layer revisions reuse features; no full-document walk."""
    import paleo_workbench.mapping.map_document_snapshot as snap

    kinds: list[str] = []
    orig = snap._features_for_kind

    def spy(records, kind):
        kinds.append(kind)
        return orig(records, kind)

    monkeypatch.setattr(snap, "_features_for_kind", spy)

    facies = [
        {
            "id": f"f{i}",
            "name": "delta",
            "coordinates": [[0, 0], [2, 0], [0, 2], [0, 0]],
        }
        for i in range(40)
    ]
    document = PaleoMapDocument(
        id="map-p3",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=facies,
    )
    authoring = MapAuthoringDocument.from_document(document)
    adapter = LegacyDocumentSceneAdapter()
    adapter.sync(
        document,
        project_crs="EPSG:3857",
        records=authoring.records(),
        layer_revisions=authoring.data_revisions(),
    )
    kinds.clear()
    session = authoring.start_editing("well")
    session.add_feature(VectorFeature("w1", {"type": "Point", "coordinates": [3.0, 4.0]}))
    adapter.sync(
        document,
        project_crs="EPSG:3857",
        records=authoring.records(),
        layer_revisions=authoring.data_revisions(),
    )
    assert kinds == ["well"]

    # Pure function path: explicit previous_layers also skips unchanged kinds.
    kinds.clear()
    first = document_render_snapshot(
        document,
        project_crs="EPSG:3857",
        records=authoring.records(),
        layer_revisions=authoring.data_revisions(),
    )
    kinds.clear()
    document_render_snapshot(
        document,
        project_crs="EPSG:3857",
        records=authoring.records(),
        layer_revisions=authoring.data_revisions(),
        previous_layers=first.layers,
    )
    assert kinds == []


def test_load_section_parses_las_off_gui_thread(qtbot, monkeypatch):
    """#659: load_correlation_wells must not run inside the click slot."""
    import paleo_workbench.ui.pages.stratigraphy_correlation_page as mod

    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    started = threading.Event()
    release = threading.Event()
    threads: list[str] = []

    known = WellLogData(
        well_name="A1",
        top_depth=0.0,
        bottom_depth=10.0,
        curves=[CurveData(name="GR", unit="GAPI", depth=[0.0, 10.0], values=[1.0, 2.0])],
    )

    def _slow_load(project, resource_ids=None, max_wells=8):
        threads.append(threading.current_thread().name)
        started.set()
        release.wait(timeout=5)
        return ([known], ["A1"], ["id-a1"], [])

    monkeypatch.setattr(mod, "load_correlation_wells", _slow_load)

    project = ProjectDocument.new("Load")
    project.resources.append(
        ResourceItem(name="A1.las", path="/a1.las", type="well_log", format="las")
    )
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_backend("legacy")
    page.set_project(project)
    page.update_state(project)
    page.well_list.item(0).setCheckState(Qt.CheckState.Checked)

    gui_thread = threading.current_thread().name
    page.load_section()
    assert threads == []
    assert page.load_btn.isEnabled() is False
    assert "加载" in page.status_label.text()
    qtbot.waitUntil(started.is_set, timeout=5_000)
    assert threads[0] != gui_thread
    release.set()
    qtbot.waitUntil(lambda: bool(page._loaded_logs), timeout=10_000)
    assert page._loaded_names == ["A1"]
    qtbot.waitUntil(lambda: page.load_btn.isEnabled(), timeout=5_000)
    page.shutdown_workers(2_000)
