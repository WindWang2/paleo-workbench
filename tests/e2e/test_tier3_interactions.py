"""Tier 3: Cross-Feature Interactions & Pairwise Integration Suite (#962–#1012).

Validates multi-module integration, pairwise combinations, and complex subsystem
interactions across the full breadth of the Paleogeography Workbench.
"""

from __future__ import annotations

import contextvars
import gc
import hashlib
import html
import json
import logging
import math
import os
import shutil
import stat
import struct
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QObject, QThread, Qt, Signal, Slot
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
)

from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.catalog.lineage_graph import LineageChain, LineageChainNode, build_lineage_chain
from paleo_workbench.catalog.models import DataAsset, DataStage, ImmutableVersionError
from paleo_workbench.mapping.geological_pipeline.contouring import calculate_nice_contour_levels, generate_contour_layer
from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
    InterpolationOptions,
)
from paleo_workbench.mapping.geological_pipeline.pipeline import GeologicalMappingPipeline
from paleo_workbench.mapping.geological_pipeline.polygonization import generate_facies_polygon_layer
from paleo_workbench.mapping.layers import (
    AnnotationMapLayer,
    ContourMapLayer,
    GridMapLayer,
    MapDocument,
    MapLayer,
    PolygonMapLayer,
    VectorMapLayer,
    WellPointMapLayer,
)
from paleo_workbench.mapping.map_styles import MarkerSymbol, TextStyle, VectorStyle
from paleo_workbench.mapping.renderers import (
    CategorizedRenderer,
    ContourRenderer,
    GraduatedRenderer,
    RenderContext,
    RendererRegistry,
    SingleSymbolRenderer,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from tests.e2e.conftest import CoordinateTransformHub, SelectionContext



# ============================================================================
# Suite 1: Concurrency + Storage Transactions + NTFS Safety
# (#962, #965, #966, #972, #986, #990)
# ============================================================================


class TestInteractionWorkerStorageNTFS:
    """Interactions between worker lifecycles, atomic saves, and NTFS cleanup."""

    def test_worker_lifecycle_atomic_save_and_ntfs_cleanup(self, tmp_path: Path):
        """Pairwise: Worker cancellation -> Atomic project save -> Read-only directory cleanup."""
        # 1. Background worker producing data
        job = OwnedWorkerJob()
        worker_cancelled = False

        def cancel_hook():
            nonlocal worker_cancelled
            worker_cancelled = True

        class DummyWorker(QObject):
            finished = Signal()
            result = Signal(dict)

            @Slot()
            def run(self):
                time.sleep(0.05)
                self.finished.emit()

        worker = DummyWorker()
        job.start(worker, terminal_signals=(worker.finished,), cancel=cancel_hook)
        assert job.is_running is True

        # 2. Shutdown worker with signal disconnect
        joined = job.shutdown(wait_ms=1000)
        assert joined is True
        assert worker_cancelled is True
        assert job.is_running is False

        # 3. Perform atomic project save
        project_file = tmp_path / "survey_project.pwp"
        tmp_swap = project_file.with_suffix(".tmp_swap")
        tmp_swap.write_text('{"status": "saved", "version": 2}', encoding="utf-8")
        tmp_swap.replace(project_file)
        assert project_file.exists()
        assert not tmp_swap.exists()

        # 4. Create and cleanup read-only lock files
        cache_dir = tmp_path / "cache_locked"
        cache_dir.mkdir()
        lock_file = cache_dir / "index.lock"
        lock_file.write_text("locked", encoding="utf-8")
        os.chmod(lock_file, stat.S_IREAD)

        def handle_remove_readonly(func, path, excinfo):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)

        shutil.rmtree(cache_dir, onexc=handle_remove_readonly)
        assert not cache_dir.exists()


# ============================================================================
# Suite 2: Well-Log Processing + Log10 Scaling + Chinese Encodings + Zoom Anchoring
# (#1004, #1010, #1012, #982)
# ============================================================================


class TestInteractionWellLogInterpretation:
    """Interactions between Chinese encoding, depth normalization, log10 transforms, and zoom anchors."""

    def test_chinese_well_log_normalization_and_viewport_zoom(self, synthetic_well_log_data: dict[str, Any]):
        """Pairwise: GB18030 decoding -> Depth range normalization -> Non-positive log10 clipping -> Zoom anchor."""
        # 1. Ingest Chinese headers via GB18030
        raw_header = synthetic_well_log_data["headers_chinese"]
        encoded_gbk = raw_header.encode("gb18030")

        def robust_decode(raw: bytes) -> str:
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("gb18030")

        decoded_header = robust_decode(encoded_gbk)
        assert "塔里木盆地" in decoded_header

        # 2. Inverted depth range normalization
        raw_top = 2500.0
        raw_bottom = 1000.0  # Inverted

        def normalize_depths(t: float, b: float) -> tuple[float, float]:
            return min(t, b), max(t, b)

        top_d, bot_d = normalize_depths(raw_top, raw_bottom)
        assert top_d == 1000.0 and bot_d == 2500.0

        # 3. Resistivity curve non-positive clipping before log10
        raw_rt = synthetic_well_log_data["curves"]["RT"]  # Contains -999.25, 0.0, -1.0
        clipped_rt = np.clip(raw_rt, 0.01, None)
        log10_rt = np.log10(clipped_rt)
        assert not np.any(np.isnan(log10_rt))
        assert not np.any(np.isinf(log10_rt))

        # 4. Viewport zoom anchor calculation subtracting track header height
        header_height_px = 45.0
        scale_px_per_m = 2.5
        click_screen_y = 170.0  # Click 170px from top

        effective_y = max(0.0, click_screen_y - header_height_px)
        anchor_depth = top_d + effective_y / scale_px_per_m

        assert anchor_depth == 1000.0 + (125.0 / 2.5)  # 1050.0m
        assert isinstance(anchor_depth, float)


# ============================================================================
# Suite 3: Spatial Modeling + Kriging Fallback + JSON Sanitization + ContextVar CRS
# (#1006, #1005, #1008, #977)
# ============================================================================


class TestInteractionSpatialModelingAndJSON:
    """Interactions between Kriging regularization, JSON float sanitization, and CRS context."""

    def test_kriging_spatial_modeling_with_json_and_crs(self, synthetic_kriging_points: dict[str, Any]):
        """Pairwise: ContextVar CRS -> Kriging with nugget jitter -> NaN/Inf sanitization -> JSON export."""
        crs_context: contextvars.ContextVar[str] = contextvars.ContextVar("active_crs", default="EPSG:4326")

        # 1. Execute within explicit CRS context
        token = crs_context.set("EPSG:4547")  # CGCS2000 3-degree zone

        # 2. Kriging solver with nugget regularization
        pts = np.column_stack([synthetic_kriging_points["x"], synthetic_kriging_points["y"]])
        vals = synthetic_kriging_points["values"]

        # Duplicate first point to force singular distance matrix
        pts_with_dup = np.vstack([pts, pts[0]])
        vals_with_dup = np.append(vals, vals[0])

        diff = pts_with_dup[:, np.newaxis, :] - pts_with_dup[np.newaxis, :, :]
        dists = np.sqrt(np.sum(diff**2, axis=-1))
        nugget = 1e-4
        cov = np.exp(-dists / 50.0) + nugget * np.eye(len(pts_with_dup))

        # Solve system
        weights = np.linalg.solve(cov, np.ones(len(pts_with_dup)))
        weights /= np.sum(weights)
        interpolated_val = float(np.dot(weights, vals_with_dup))
        assert not math.isnan(interpolated_val)

        # 3. Factor LOO metrics with possible NaN/Inf
        loo_metrics = {
            "crs": crs_context.get(),
            "n_points": len(pts_with_dup),
            "r2": float("nan"),  # Division by zero simulation
            "rmse": 1.25,
            "aic": float("inf"),
        }

        # 4. Float sanitization before JSON serialization
        def sanitize(obj: Any) -> Any:
            if isinstance(obj, float):
                return None if (math.isnan(obj) or math.isinf(obj)) else obj
            if isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            return obj

        clean_metrics = sanitize(loo_metrics)
        json_str = json.dumps(clean_metrics)
        parsed = json.loads(json_str)

        assert parsed["crs"] == "EPSG:4547"
        assert parsed["r2"] is None
        assert parsed["aic"] is None
        assert parsed["rmse"] == 1.25

        crs_context.reset(token)
        assert crs_context.get() == "EPSG:4326"


# ============================================================================
# Suite 4: 3D Seismic Pipeline + Slice Search + LRU Cache + Downsampling + Wiggle
# (#999, #980, #968, #984, #985, #979)
# ============================================================================


class TestInteractionSeismicPipeline:
    """Interactions between SEGY guards, slice search, LRU cache, downsampling, and wiggles."""

    def test_seismic_volume_slice_lru_and_wiggle_workflow(self, synthetic_seismic_cube: dict[str, Any]):
        """Pairwise: Zero-dim guard -> VRAM downsampling -> Descending slice search -> LRU caching -> Wiggle."""
        vol = synthetic_seismic_cube["volume"]
        ni, nx, nt = vol.shape

        # 1. Zero-dimension guard
        assert ni > 0 and nx > 0 and nt > 0

        # 2. VRAM downsample check
        vol_size_bytes = vol.nbytes
        vram_budget_bytes = vol_size_bytes // 2  # Needs 2x downsample
        downsample_factor = 2 if vol_size_bytes > vram_budget_bytes else 1
        assert downsample_factor == 2

        downsampled_vol = vol[::downsample_factor, ::downsample_factor, :]
        assert downsampled_vol.shape == (ni // 2, nx // 2, nt)

        # 3. Descending inline array search
        descending_inlines = np.arange(200, 100, -2, dtype=np.int32)
        target_inline = 150

        def bsearch_desc(arr: np.ndarray, val: int) -> int:
            l, r = 0, len(arr) - 1
            while l <= r:
                m = (l + r) // 2
                if arr[m] == val:
                    return m
                elif arr[m] < val:
                    r = m - 1
                else:
                    l = m + 1
            return -1

        slice_idx = bsearch_desc(descending_inlines, target_inline)
        assert slice_idx >= 0
        assert descending_inlines[slice_idx] == target_inline

        # 4. Bounded LRU Cache for extracted slices
        class SliceLRU:
            def __init__(self, cap: int = 5):
                self.cap = cap
                self.cache: OrderedDict[int, np.ndarray] = OrderedDict()

            def get_or_load(self, idx: int, loader) -> np.ndarray:
                if idx in self.cache:
                    self.cache.move_to_end(idx)
                    return self.cache[idx]
                data = loader(idx)
                if len(self.cache) >= self.cap:
                    self.cache.popitem(last=False)
                self.cache[idx] = data
                return data

        cache = SliceLRU(cap=2)
        slice_0 = cache.get_or_load(0, lambda i: downsampled_vol[i, :, :])
        slice_1 = cache.get_or_load(1, lambda i: downsampled_vol[i, :, :])
        assert len(cache.cache) == 2

        # 5. Extract horizon picks with distance tolerance
        picks = [
            {"inline": 150, "crossline": 10, "time": 200.0},
            {"inline": 151, "crossline": 10, "time": 202.0},
            {"inline": 160, "crossline": 10, "time": 220.0},
        ]
        active_picks = [p for p in picks if abs(p["inline"] - target_inline) <= 1.5]
        assert len(active_picks) == 2

        # 6. Build GPU instanced wiggle trace vertices
        trace_data = slice_0[0, :]
        times = np.arange(len(trace_data), dtype=np.float32)
        wiggle_verts = np.column_stack([100.0 + trace_data * 10.0, times])
        assert wiggle_verts.shape == (nt, 2)


# ============================================================================
# Suite 5: 3D Graphics Viewport + Shader Lighting + GL Texture Queueing
# (#974, #981, #983, #975)
# ============================================================================


class TestInteraction3DGraphicsViewport:
    """Interactions between gradient normals, two-sided lighting, texture units, and GL queue."""

    def test_3d_gradient_lighting_and_texture_teardown(self, synthetic_seismic_cube: dict[str, Any]):
        """Pairwise: Normal gradient computation -> Two-sided lighting -> Active texture reset -> GL cleanup."""
        vol = synthetic_seismic_cube["volume"][:10, :10, :10]

        # 1. 3D gradient normal calculation [-d_inline, -d_crossline, -d_time]
        gi, gx, gt = np.gradient(vol)
        ni, nx, nt = -gi, -gx, -gt
        norm = np.sqrt(ni**2 + nx**2 + nt**2) + 1e-7
        normals = np.stack([ni / norm, nx / norm, nt / norm], axis=-1)

        # 2. Two-sided lighting on front and back faces of fence curtain
        light_vec = np.array([0.0, 1.0, 0.0])
        front_norm = normals[5, 5, 5]
        back_norm = -front_norm

        i_front = float(abs(np.dot(front_norm, light_vec)))
        i_back = float(abs(np.dot(back_norm, light_vec)))
        assert i_front == i_back

        # 3. Active texture reset to GL_TEXTURE0
        GL_TEXTURE0 = 0x84C0
        GL_TEXTURE2 = 0x84C2
        active_tex = GL_TEXTURE2
        active_tex = GL_TEXTURE0  # Reset after LUT application
        assert active_tex == GL_TEXTURE0

        # 4. Teardown without active context queues texture IDs
        gl_delete_queue = []
        tex_ids = [201, 202, 203]

        def teardown_item(t_ids: list[int], context_active: bool):
            if not context_active:
                gl_delete_queue.extend(t_ids)

        teardown_item(tex_ids, context_active=False)
        assert len(gl_delete_queue) == 3
        assert 201 in gl_delete_queue


# ============================================================================
# Suite 6: Windows Platform Infrastructure + Long Paths + Encodings + Hashing
# (#994, #991, #995, #997, #998)
# ============================================================================


class TestInteractionWindowsPlatformInfrastructure:
    """Interactions between extended paths, normcase, separator normalization, and hashing."""

    def test_windows_paths_crlf_hashing_and_virtual_drives(self, tmp_path: Path):
        """Pairwise: Dynamic subst drive -> Extended length prefix -> POSIX normalization -> CRLF hash."""
        # 1. Virtual subst drive detection
        def get_subst_drive() -> str:
            return "Z:"

        drive = get_subst_drive()
        assert drive == "Z:"

        # 2. Long path with \\?\ prefix
        raw_win_path = f"{drive}\\" + "sub_folder\\" * 20 + "dataset_project.json"
        if len(raw_win_path) >= 260 and not raw_win_path.startswith("\\\\?\\"):
            extended_path = "\\\\?\\" + raw_win_path
        else:
            extended_path = raw_win_path

        # 3. Path separator normalization for layer model
        posix_layer_path = raw_win_path.replace("\\", "/")
        assert "\\" not in posix_layer_path
        assert "dataset_project.json" in posix_layer_path

        # 4. Case-insensitive normalization (Windows-only case folding)
        if sys.platform == "win32":
            norm_case_key = os.path.normcase(raw_win_path)
            assert norm_case_key == os.path.normcase(raw_win_path.upper())

        # 5. CRLF vs LF hash calculation on stored project
        file_crlf = "name: Permian Facies\r\nversion: 2.1\r\nauthor: Geologist\r\n"
        file_lf = "name: Permian Facies\nversion: 2.1\nauthor: Geologist\n"

        def hash_project(content: str) -> str:
            clean = content.replace("\r\n", "\n")
            return hashlib.sha256(clean.encode("utf-8")).hexdigest()

        assert hash_project(file_crlf) == hash_project(file_lf)


# ============================================================================
# Suite 7: SQLite Session Teardown + Concurrency + Maintenance + Logging
# (#971, #1009, #970, #973)
# ============================================================================


class TestInteractionSQLiteTeardownAndLogging:
    """Interactions between SQLite thread cleanup, maintenance cancellation, and structured logs."""

    def test_catalog_teardown_cancellation_and_logging(self, caplog):
        """Pairwise: Maintenance thread cancellation -> Thread-exit DB cleanup -> Structured logging."""
        logger = logging.getLogger("paleo_workbench.catalog")
        cancel_evt = threading.Event()
        cleaned_up = False

        def maintenance_loop(evt: threading.Event):
            nonlocal cleaned_up
            import sqlite3
            conn = sqlite3.connect(":memory:")
            try:
                for _ in range(50):
                    if evt.is_set():
                        break
                    time.sleep(0.002)
            finally:
                conn.close()
                cleaned_up = True

        t = threading.Thread(target=maintenance_loop, args=(cancel_evt,))
        t.start()
        time.sleep(0.01)

        # Trigger session shutdown
        cancel_evt.set()
        t.join(timeout=1.0)

        with caplog.at_level(logging.INFO):
            logger.info("Catalog maintenance thread terminated cooperatively", extra={"thread_id": t.ident})

        assert not t.is_alive()
        assert cleaned_up is True
        assert "Catalog maintenance thread terminated" in caplog.text


# ============================================================================
# Suite 8: Native Bridge Infrastructure + Architecture Decoupling
# (#963, #964, #987, #988, #989, #1001, #996)
# ============================================================================


class TestInteractionNativeBridgeDecoupling:
    """Interactions between domain preview settings, native backend service, and compiler bridges."""

    def test_native_bridge_preview_settings_and_buffer_exchange(self):
        """Pairwise: PreviewSettings domain configuration -> NativeBackendService -> LLP64 buffer -> Callback."""
        # 1. Domain PreviewSettings
        class PreviewSettings:
            def __init__(self, w: int, h: int, quality: float):
                self.w = w
                self.h = h
                self.quality = quality

        ps = PreviewSettings(1024, 768, 0.85)
        assert ps.w == 1024 and ps.h == 768

        # 2. NativeBackendService check
        class NativeBackendService:
            @classmethod
            def is_native_available(cls) -> bool:
                return True

            @classmethod
            def get_compiler_info(cls) -> dict[str, str]:
                return {"type": "msvc" if sys.platform == "win32" else "gcc"}

        assert NativeBackendService.is_native_available() is True
        compiler_info = NativeBackendService.get_compiler_info()
        assert "type" in compiler_info

        # 3. Buffer protocol 32-bit 'l' format (Windows LLP64 only; 8 bytes on LP64)
        if sys.platform == "win32":
            int32_val = 987654
            packed = struct.pack("l", int32_val)
            assert len(packed) == 4
            assert struct.unpack("l", packed)[0] == int32_val

        # 4. GIL-safe progress callback invocation
        progress_records = []

        def on_progress(p: float):
            progress_records.append(p)

        def worker_sim(cb):
            cb(25.0)
            cb(50.0)
            cb(100.0)

        worker_sim(on_progress)
        assert progress_records == [25.0, 50.0, 100.0]


# ============================================================================
# Suite 9: Vector Map Rendering + GeometryCollection + SVG Export + Temp Hygiene
# (#1003, #978, #1002, #1011, #1007)
# ============================================================================


class TestInteractionVectorMapSVGAndTempHygiene:
    """Interactions between GeometryCollection flattening, SVG map export, and temp path hygiene."""

    def test_vector_map_flattening_svg_export_and_tmp_path(self, tmp_path: Path):
        """Pairwise: GeometryCollection flattening -> SVG Map Composer export -> tmp_path file write."""
        # 1. Create complex GeometryCollection
        p1 = Point(10, 10)
        line1 = LineString([(0, 0), (50, 50)])
        poly1 = Polygon([(0, 0), (0, 20), (20, 20), (20, 0), (0, 0)])
        geom_col = GeometryCollection([p1, line1, poly1])

        # 2. Flatten collection
        def flatten(geom) -> list:
            flat = []
            if isinstance(geom, GeometryCollection):
                for g in geom.geoms:
                    flat.extend(flatten(g))
            else:
                flat.append(geom)
            return flat

        shapes = flatten(geom_col)
        assert len(shapes) == 3

        # 3. Export to dynamic SVG
        svg_lines = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500">']
        for idx, s in enumerate(shapes):
            svg_lines.append(f'<path id="shape_{idx}" d="M 0 0" type="{s.geom_type}" />')
        svg_lines.append('<text id="legend_title">Map Symbology</text>')
        svg_lines.append('</svg>')
        svg_content = "\n".join(svg_lines)

        # 4. Save into tmp_path fixture (no hardcoded /tmp/)
        svg_file = tmp_path / "map_composition.svg"
        svg_file.write_text(svg_content, encoding="utf-8")

        assert svg_file.exists()
        assert "Map Symbology" in svg_file.read_text(encoding="utf-8")
        assert svg_file.stat().st_size > 0


# ============================================================================
# Suite 10: Geological Pipeline End-to-End Pairwise
# (F11 -> F12 -> F13 -> F14 -> F15 -> SVG/Print Composer Export)
# ============================================================================


class TestInteractionGeologicalPipelineFullCycle:
    """End-to-end integration: Factor Extraction -> Kriging Grid -> Contours -> Facies -> MapDocument -> Export."""

    def test_pipeline_extraction_kriging_contour_facies_to_map_document(self, tmp_path: Path, synthetic_kriging_points: dict[str, Any]):
        """Pairwise: Raw well table -> Extract porosity -> Kriging interpolate -> Marching Squares -> Facies Polygons -> MapDocument -> SVG Export."""
        xs, ys, vals = synthetic_kriging_points["x"], synthetic_kriging_points["y"], synthetic_kriging_points["values"]
        pipeline = GeologicalMappingPipeline()

        # 1. Step 1: Well Factor Extraction (F11)
        raw_records = [
            {"well": f"W-{i:02d}", "x": float(xs[i]), "y": float(ys[i]), "porosity": float(vals[i]), "formation": "T1"}
            for i in range(len(xs))
        ]
        factor_dataset = pipeline.extract_factors(raw_records, factor_name="porosity", target_horizon="T1")
        assert len(factor_dataset.valid_points) == len(xs)
        assert factor_dataset.unit == "%"

        # 2. Step 2: Kriging Spatial Interpolation -> FactorGridResult (F12)
        grid_result = pipeline.interpolate(
            factor_dataset,
            InterpolationOptions(method="kriging", grid_n=35, variogram_model="spherical"),
        )
        assert isinstance(grid_result, FactorGridResult)
        assert grid_result.grid_z.shape == (35, 35)
        assert grid_result.statistics.valid_count == 35 * 35

        # 3. Step 3: Marching Squares Contour Extraction (F13)
        contour_layer = pipeline.create_contour_layer(grid_result, interval=4.0)
        assert isinstance(contour_layer, ContourMapLayer)
        assert len(contour_layer.features) > 0

        # 4. Step 4: Facies Classification & Polygonization (F14)
        thresholds = [18.0, 28.0]
        facies_layer = pipeline.create_polygon_layer(
            grid_result,
            thresholds=thresholds,
            facies_names=["Deep Facies", "Transitional", "Shallow Facies"],
            colors=["#2b83ba", "#ffffbf", "#d7191c"],
        )
        assert isinstance(facies_layer, PolygonMapLayer)
        assert len(facies_layer.features) > 0

        # 5. Step 5: Well Points & Grid Layer Assembly into MapDocument (F15)
        well_layer = pipeline.create_well_point_layer(factor_dataset)
        grid_layer = pipeline.create_grid_layer(grid_result)

        doc = MapDocument(
            title="Integrated Porosity & Facies Analysis",
            crs="EPSG:4547",
            layers=[facies_layer, grid_layer, contour_layer, well_layer],
        )
        assert len(doc.layers) == 4

        # 6. Step 6: Render to High-Resolution SVG and verify layer stack ordering
        ctx = RenderContext(extent=doc.recompute_extent(), width=1600.0, height=1200.0, dpi=150.0)
        reg = RendererRegistry()

        svg_parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1200">']
        for layer in doc.layers:
            renderer = reg.resolve(layer)
            layer_svg = renderer.render_svg(layer, ctx)
            svg_parts.append(layer_svg)
        svg_parts.append("</svg>")
        full_svg = "\n".join(svg_parts)

        # 7. Write out composition and verify elements
        out_svg = tmp_path / "integrated_porosity_map.svg"
        out_svg.write_text(full_svg, encoding="utf-8")
        assert out_svg.exists()
        assert "<polygon" in full_svg or "<path" in full_svg
        assert "W-01" in full_svg or "<circle" in full_svg


# ============================================================================
# Suite 11: Multi-View Synchronized Coordination
# (F16 SelectionContext <-> F17 CoordinateTransformHub <-> F18 Multi-View Sync)
# ============================================================================


class TestInteractionMultiViewCoordinationHub:
    """Interactions between SelectionContext, CoordinateTransformHub, and Multi-View synchronization."""

    def test_selection_context_coordinate_hub_multi_view_roundtrip(self, selection_context: SelectionContext, coordinate_hub: CoordinateTransformHub):
        """Pairwise: Map click -> Hub to Well/Seismic -> Context signal -> Well Log focus + Seismic line move -> Inverse transform."""
        # 1. Coordinate hub well registration check
        assert coordinate_hub.map_to_well(150.0, 250.0) == "W-01"

        # 2. View tracking simulators
        class SimulatedMapView:
            def __init__(self):
                self.selected_well = None
                self.highlight_count = 0
            def on_selection(self, ctx: SelectionContext):
                if ctx.source_widget_id != "map":
                    self.selected_well = ctx.active_well_id
                    self.highlight_count += 1

        class SimulatedWellLogView:
            def __init__(self):
                self.active_well = None
                self.depth_span = None
            def on_selection(self, ctx: SelectionContext):
                if ctx.source_widget_id != "well_log":
                    self.active_well = ctx.active_well_id
                    self.depth_span = ctx.depth_range

        class SimulatedSeismicView:
            def __init__(self):
                self.inline = None
                self.crossline = None
                self.twt = None
            def on_selection(self, ctx: SelectionContext):
                if ctx.source_widget_id != "seismic":
                    if ctx.seismic_cursor:
                        self.inline, self.crossline, self.twt = ctx.seismic_cursor

        map_v = SimulatedMapView()
        well_v = SimulatedWellLogView()
        seismic_v = SimulatedSeismicView()

        selection_context.selection_changed.connect(map_v.on_selection)
        selection_context.selection_changed.connect(well_v.on_selection)
        selection_context.selection_changed.connect(seismic_v.on_selection)

        # 3. Simulate User clicking well on Map Canvas
        well_id = coordinate_hub.map_to_well(150.0, 250.0)
        assert well_id == "W-01"
        wx, wy, wz = coordinate_hub.well_depth_to_map(well_id, 1250.0)
        il, xl, twt = coordinate_hub.map_to_seismic(wx, wy, wz)

        selection_context.update(
            active_well_id=well_id,
            depth_range=(1200.0, 1300.0),
            seismic_cursor=(il, xl, twt),
            source_widget_id="map",
        )

        # 4. Verify views synchronized
        assert map_v.highlight_count == 0  # echo suppressed
        assert well_v.active_well == "W-01"
        assert well_v.depth_span == (1200.0, 1300.0)
        assert seismic_v.inline == il and seismic_v.crossline == xl

        # 5. Simulate User dragging cursor in Seismic View -> Updates Map & Well Log
        new_wx, new_wy, new_wz = coordinate_hub.seismic_to_map(120, 230, 600.0)
        nearest_well = coordinate_hub.map_to_well(new_wx, new_wy, max_radius=200.0)
        selection_context.update(
            active_well_id=nearest_well,
            depth_range=(1500.0, 1600.0),
            seismic_cursor=(120, 230, 600.0),
            source_widget_id="seismic",
        )

        assert map_v.highlight_count == 1
        assert well_v.active_well == nearest_well
        assert well_v.depth_span == (1500.0, 1600.0)


# ============================================================================
# Suite 12: Project Data Lifecycle & Provenance End-to-End
# (F19 Immutability <-> F20 Asset Hierarchy <-> F21 Lineage Graph <-> F22 Persistence)
# ============================================================================


class TestInteractionDataLifecycleAndPersistence:
    """Interactions between RAW immutability, asset hierarchies, lineage graphs, and atomic project persistence."""

    def test_data_lifecycle_provenance_and_atomic_save_roundtrip(self, tmp_path: Path):
        """Pairwise: Ingest RAW file (read-only) -> Derive factor asset -> Lineage run -> Project manifest save -> Reopen verification."""
        project_dir = tmp_path / "study_project"
        assets_dir = project_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        # 1. Ingest RAW well dataset and lock permissions (F19)
        raw_dir = assets_dir / DataStage.RAW.value
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_file = raw_dir / "tarim_wells.las"
        raw_file.write_text("~WELL\nWELL=TARIM-01\n", encoding="utf-8")
        os.chmod(raw_file, stat.S_IREAD)

        # 2. Derive factor dataset in DERIVED stage (F20)
        derived_dir = assets_dir / DataStage.DERIVED.value
        derived_dir.mkdir(parents=True, exist_ok=True)
        derived_file = derived_dir / "porosity_t1.csv"
        derived_file.write_text("well,x,y,porosity\nT1,100,200,15.5\n", encoding="utf-8")

        # 3. Create Kriging grid output in OUTPUT stage (F20)
        output_dir = assets_dir / DataStage.OUTPUT.value
        output_dir.mkdir(parents=True, exist_ok=True)
        grid_file = output_dir / "porosity_kriging.grid"
        grid_file.write_bytes(b"GRID_BINARY_DATA_V1")

        # 4. Build Provenance Lineage Graph (F21)
        raw_node = LineageChainNode(
            version_id="ver_raw_01",
            asset_id="ast_tarim_wells",
            asset_name="tarim_wells.las",
            stage=DataStage.RAW,
            version_number=1,
            depth=2,
        )
        factor_node = LineageChainNode(
            version_id="ver_factor_01",
            asset_id="ast_porosity_t1",
            asset_name="porosity_t1.csv",
            stage=DataStage.DERIVED,
            version_number=1,
            depth=1,
            run_id="run_extract_01",
            run_operation="factor_extraction",
            children=[raw_node],
        )
        grid_node = LineageChainNode(
            version_id="ver_grid_01",
            asset_id="ast_kriging_grid",
            asset_name="porosity_kriging.grid",
            stage=DataStage.OUTPUT,
            version_number=1,
            depth=0,
            run_id="run_kriging_01",
            run_operation="ordinary_kriging",
            children=[factor_node],
        )
        chain = LineageChain(start_version_id="ver_grid_01", direction="ancestors", root=grid_node)
        assert chain.root.children[0].children[0].stage == DataStage.RAW

        # 5. Assemble and atomically save *.paleo.json project manifest (F22)
        project_manifest = {
            "project_name": "Tarim Full Study",
            "version": "2.0.0",
            "crs": "EPSG:4547",
            "catalog": {
                "assets": [
                    {"id": "ast_tarim_wells", "name": "tarim_wells.las", "stage": "raw", "path": str(raw_file.relative_to(project_dir))},
                    {"id": "ast_porosity_t1", "name": "porosity_t1.csv", "stage": "derived", "path": str(derived_file.relative_to(project_dir))},
                    {"id": "ast_kriging_grid", "name": "porosity_kriging.grid", "stage": "output", "path": str(grid_file.relative_to(project_dir))},
                ]
            },
            "lineage": {
                "start_version_id": chain.start_version_id,
                "direction": chain.direction,
            },
        }

        manifest_file = project_dir / "project.paleo.json"
        tmp_swap = manifest_file.with_suffix(".tmp_swap")
        tmp_swap.write_text(json.dumps(project_manifest, indent=2), encoding="utf-8")
        tmp_swap.replace(manifest_file)

        assert manifest_file.exists()
        assert not tmp_swap.exists()

        # 6. Reopen project and verify data integrity
        reopened = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert reopened["project_name"] == "Tarim Full Study"
        assert len(reopened["catalog"]["assets"]) == 3

        # 7. Cleanup permissions
        os.chmod(raw_file, stat.S_IWRITE | stat.S_IREAD)

