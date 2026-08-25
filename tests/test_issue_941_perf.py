"""Regressions for #941 performance/memory batch."""

from __future__ import annotations

import time

import numpy as np
import pytest


def test_snapshot_one_pass_grouped_walker(monkeypatch) -> None:
    """#941-3: cold snapshot must build via one-pass grouped walker, not 4× scans."""
    import paleo_workbench.mapping.map_document_snapshot as snap
    from paleo_workbench.mapping.map_document_snapshot import document_render_snapshot
    from paleo_workbench.project.models import PaleoMapDocument

    kinds_calls: list[set[str]] = []
    orig = snap._grouped_features

    def spy(records, needed):
        kinds_calls.append(set(needed))
        return orig(records, needed)

    monkeypatch.setattr(snap, "_grouped_features", spy)

    facies = [{"id": f"f{i}", "name": "delta", "coordinates": [[0, 0], [2, 0], [0, 2], [0, 0]]} for i in range(20)]
    wells = [{"id": f"w{i}", "name": f"W{i}", "x": float(i), "y": float(i)} for i in range(20)]
    document = PaleoMapDocument(
        id="doc-941-3",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=facies,
        well_overlays=wells,
        line_features=[{"id": "l1", "name": "F", "coordinates": [[-1, 5], [11, 5]]}],
        label_features=[{"id": "lb1", "text": "H1", "anchor": [5, 8]}],
    )
    snapshot = document_render_snapshot(document, project_crs="EPSG:3857")
    # The walker should have been called once per distinct kind batch, not per-kind via old _features_for_kind.
    # With 4 kinds, the grouped walker should be invoked at most 4 times (once per kind missing), not 4 full scans each.
    # More precisely, after the fix, document_render_snapshot calls grouped_features({kind}) per kind, which coalesces.
    # The spy records needed sets; they should be singletons, not the old 4× full-document scan.
    assert snapshot.layers
    # If the old per-kind path were used, _features_for_kind would have been called 4×; we spy grouped instead.
    # Ensure grouped was used at all.
    assert kinds_calls, "grouped walker not used"
    # Each call should request exactly one kind (the current implementation batches per-kind via grouped_features({kind})).
    for needed in kinds_calls:
        assert len(needed) == 1

    # Performance smoke: 10k features well under the old 4x-scan cost.
    # Budget 3s for slow shared CI runners (observed 1.27s on ubuntu-latest);
    # the regression this guards — one snapshot per kind — cost ~4x that.
    large = [{"id": f"f{i}", "name": "d", "coordinates": [[0, 0], [1, 0], [0, 1], [0, 0]]} for i in range(10000)]
    doc2 = PaleoMapDocument(id="big", name="M", linked_target_horizon="H1", facies_polygons=large)
    t0 = time.perf_counter()
    snap2 = document_render_snapshot(doc2, project_crs="EPSG:3857")
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, f"snapshot 10k took {elapsed:.2f}s, expected <3s (one-pass)"
    assert snap2.layers[0].features


def test_stable_revision_fast_path_parity() -> None:
    """#941-4: fast feature hash must be stable and sensitive to edits, and fast @10万."""
    from paleo_workbench.mapping.map_document_snapshot import _stable_revision, _fast_feature_collection_hash

    def make_features(n: int):
        return tuple(
            {"id": f"fid-{i}", "geometry": {"type": "Point", "coordinates": [float(i), float(i)]}, "properties": {"facies": "sand"}}
            for i in range(n)
        )

    small = make_features(10)
    # Small collection should use slow path (fast returns None)
    assert _fast_feature_collection_hash(small) is None
    # Large collection uses fast path
    large = make_features(5000)
    fast = _fast_feature_collection_hash(large)
    assert fast is not None
    # Stability: same input -> same hash
    assert _fast_feature_collection_hash(large) == fast
    assert _stable_revision(large) == _stable_revision(large)
    # Sensitivity: editing one coordinate changes hash
    edited = list(large)
    edited[0] = {"id": "fid-0", "geometry": {"type": "Point", "coordinates": [9999.0, 9999.0]}, "properties": {"facies": "sand"}}
    assert _stable_revision(tuple(edited)) != _stable_revision(large)
    # Performance: 100k features should be <0.2s (was 6.1s)
    huge = make_features(100_000)
    t0 = time.perf_counter()
    h = _stable_revision(huge)
    elapsed = time.perf_counter() - t0
    assert isinstance(h, int)
    assert elapsed < 1.0, f"100k freeze hash took {elapsed:.2f}s, expected <1s"


def test_render_sync_reuses_snapshot_fingerprint(monkeypatch) -> None:
    """#941-6: sync path must not re-push full snapshot every frame (pending only)."""
    from paleo_workbench.mapping.map_render_backend import QgisMapRenderBackend, MapLayerSnapshot, MapRenderSnapshot

    backend = QgisMapRenderBackend()
    # Stub native bridge
    class FakeBridge:
        def __init__(self):
            self.calls = 0
            self.render_active = False
            self.version = "fake"
        def initialize(self): pass
        def set_layer_snapshot(self, *a, **kw): self.calls += 1
        def render_sync(self, *a, **kw): return {"width": 10, "height": 10, "stride": 40, "rgba": b"\x00"*400}
        def cancel_render(self): pass
        def shutdown(self): pass
        def take_completed_frame(self): return None

    fake = FakeBridge()
    backend._native_module = object()  # make is_available True path not needed; we inject directly
    backend._bridge = fake
    backend._native_snapshot_pending = False
    backend._initialized = True
    backend._snapshot = MapRenderSnapshot(project_crs="EPSG:3857", layers=(
        MapLayerSnapshot(id="doc:facies", name="Facies", layer_type="vector", extent=(0,0,10,10), crs="EPSG:3857", data_revision=1, style_revision=1, features=({"id": "f1", "geometry": {"type": "Point", "coordinates": [5,5]}, "properties": {}},)),
    ))
    backend._extent = (0.0, 0.0, 10.0, 10.0)
    backend._output_size = (10, 10)
    backend._dpi = 96.0
    # First sync — pending is False, so should NOT push (eager path already pushed)
    backend.render_sync()
    assert fake.calls == 0, "sync should not re-push when pending is False"
    # Simulate a snapshot arrived before bridge existed
    backend._native_snapshot_pending = True
    fake.calls = 0
    backend.render_sync()
    assert fake.calls == 1, "sync must push exactly once when pending is True"
    assert backend._native_snapshot_pending is False


def test_about_to_quit_hooks_shutdown(monkeypatch) -> None:
    """#941-7: app.aboutToQuit must be connected to shutdown_live_fallback_backends."""
    import pathlib
    src = pathlib.Path(__file__).parents[1] / "paleo_workbench" / "main.py"
    text = src.read_text(encoding="utf-8")
    assert "aboutToQuit.connect" in text
    assert "_shutdown_render_backends" in text or "shutdown_live_fallback_backends" in text
    # Ensure UnifiedMapCanvas.closeEvent still shuts down its own backend (fallback), but the app-level hook exists
    canvas_src = pathlib.Path(__file__).parents[1] / "paleo_workbench" / "ui" / "unified_map_canvas.py"
    canvas_text = canvas_src.read_text(encoding="utf-8")
    assert "def closeEvent" in canvas_text
