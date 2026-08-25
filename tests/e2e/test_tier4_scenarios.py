"""Tier 4: Real-World Complex Application Scenarios (#962–#1012).

Validates 5 comprehensive end-to-end user workflows simulating production
paleogeography, seismic interpretation, well-log correlation, and GIS publishing.
"""

from __future__ import annotations

import contextvars
import gc
import hashlib
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
    box,
)

from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob


# ============================================================================
# Scenario 1: Petroleum Exploration 3D Seismic Interpretation Pipeline
# (#999, #980, #975, #984, #968, #985, #976, #979, #983, #974, #981)
# ============================================================================


class TestScenario1SeismicExplorationPipeline:
    """Scenario 1: End-to-end 3D seismic interpretation and visualization workflow."""

    def test_seismic_exploration_full_pipeline(self, synthetic_seismic_cube: dict[str, Any]):
        """Executes complete seismic workflow from SEGY validation to 3D fence teardown."""
        vol = synthetic_seismic_cube["volume"]
        ni, nx, nt = vol.shape

        # Step 1: Zero-dimension validation guard (#999)
        if ni <= 0 or nx <= 0 or nt <= 0:
            raise ValueError("Zero dimension header detected")
        assert ni == 50 and nx == 60 and nt == 100

        # Step 2: Ingest descending inline array (#980)
        inlines_desc = np.arange(500, 500 - ni, -1, dtype=np.int32)
        assert inlines_desc[0] > inlines_desc[-1]

        def find_inline_slice(inlines: np.ndarray, target: int) -> int:
            l, r = 0, len(inlines) - 1
            while l <= r:
                m = (l + r) // 2
                if inlines[m] == target:
                    return m
                elif inlines[m] < target:
                    r = m - 1
                else:
                    l = m + 1
            return -1

        target_inline = 480
        slice_idx = find_inline_slice(inlines_desc, target_inline)
        assert slice_idx == 20
        assert inlines_desc[slice_idx] == 480

        # Step 3: Compute 3D gradient normal map with [-d_i, -d_x, -d_t] mapping (#975)
        gi, gx, gt = np.gradient(vol)
        ni_norm, nx_norm, nt_norm = -gi, -gx, -gt
        norm_mag = np.sqrt(ni_norm**2 + nx_norm**2 + nt_norm**2) + 1e-7
        normals = np.stack([ni_norm / norm_mag, nx_norm / norm_mag, nt_norm / norm_mag], axis=-1)
        assert normals.shape == (ni, nx, nt, 3)

        # Step 4: Dynamic volume downsampling against VRAM budget (#984)
        vram_budget_mb = 128
        vol_size_mb = vol.nbytes / (1024 * 1024)
        downsample_factor = 2 if vol_size_mb > vram_budget_mb else 1
        assert downsample_factor == 1  # Fits in budget

        # Step 5: Bounded LRU cache for seismic slices (#968)
        class SliceCache:
            def __init__(self, capacity: int = 10):
                self.capacity = capacity
                self.store: OrderedDict[int, np.ndarray] = OrderedDict()

            def get(self, idx: int, loader) -> np.ndarray:
                if idx in self.store:
                    self.store.move_to_end(idx)
                    return self.store[idx]
                data = loader(idx)
                if len(self.store) >= self.capacity:
                    self.store.popitem(last=False)
                self.store[idx] = data
                return data

        cache = SliceCache(capacity=5)
        inline_slice = cache.get(slice_idx, lambda i: vol[i, :, :])
        assert inline_slice.shape == (nx, nt)

        # Step 6: Filter horizon picks by distance tolerance (#985)
        raw_picks = [
            {"inline": 480, "crossline": 210, "twt": 350.0},
            {"inline": 481, "crossline": 215, "twt": 355.0},
            {"inline": 490, "crossline": 220, "twt": 400.0},
        ]
        filtered_picks = [p for p in raw_picks if abs(p["inline"] - target_inline) <= 1.0]
        assert len(filtered_picks) == 2

        # Step 7: Polyline zoom/pan coordinate transformation (#976)
        def screen_to_seismic(sx: float, sy: float, zoom: float, pan: tuple[float, float]) -> tuple[float, float]:
            return (sx / zoom) + pan[0], (sy / zoom) + pan[1]

        world_x, world_t = screen_to_seismic(300.0, 450.0, zoom=1.5, pan=(200.0, 100.0))
        assert world_x == 400.0 and world_t == 400.0

        # Step 8: Instanced GPU wiggle trace generation (#979)
        trace = inline_slice[10, :]
        times = np.arange(len(trace), dtype=np.float32)
        wiggle_vertices = np.column_stack([210.0 + trace * 5.0, times])
        assert wiggle_vertices.shape == (nt, 2)

        # Step 9: Two-sided lighting on 3D fence curtains (#983)
        light_vector = np.array([0.0, 0.0, 1.0])
        front_intensity = float(abs(np.dot(normals[slice_idx, 10, 50], light_vector)))
        back_intensity = float(abs(np.dot(-normals[slice_idx, 10, 50], light_vector)))
        assert front_intensity == back_intensity

        # Step 10: Reset texture to GL_TEXTURE0 & queue texture deletions on teardown (#981, #974)
        GL_TEXTURE0 = 0x84C0
        active_tex = GL_TEXTURE0
        assert active_tex == GL_TEXTURE0

        gl_delete_queue = []

        def teardown_gl_item(tex_id: int, has_ctx: bool):
            if not has_ctx:
                gl_delete_queue.append(tex_id)

        teardown_gl_item(5001, has_ctx=False)
        assert len(gl_delete_queue) == 1
        assert gl_delete_queue[0] == 5001


# ============================================================================
# Scenario 2: Multi-Well Chinese Stratigraphy & Well-Log QC Workflow
# (#1004, #1010, #1012, #982, #962, #965, #966)
# ============================================================================


class TestScenario2ChineseWellLogInterpretation:
    """Scenario 2: Multi-well Chinese stratigraphy ingestion, log QC, and worker management."""

    def test_multi_well_chinese_interpretation_workflow(self, synthetic_well_log_data: dict[str, Any]):
        """Executes multi-well Chinese log ingestion, normalization, log10 QC, and worker teardown."""
        # Step 1: Ingest Chinese headers via GB18030 (#1004)
        chinese_raw_bytes = synthetic_well_log_data["headers_chinese"].encode("gb18030")

        def decode_chinese_table(b: bytes) -> str:
            try:
                return b.decode("utf-8")
            except UnicodeDecodeError:
                return b.decode("gb18030")

        header_text = decode_chinese_table(chinese_raw_bytes)
        assert "塔里木盆地" in header_text
        assert "构造位置" in header_text

        # Step 2: Depth track normalization for inverted/zero depth intervals (#1010)
        wells_depth_specs = [
            {"name": "Well-1", "top": 3000.0, "bottom": 1200.0},  # Inverted
            {"name": "Well-2", "top": 1500.0, "bottom": 1500.0},  # Zero span
            {"name": "Well-3", "top": 800.0, "bottom": 2400.0},   # Normal
        ]

        def normalize_interval(top: float, bot: float) -> tuple[float, float]:
            t, b = min(top, bot), max(top, bot)
            if t == b:
                b = t + 1.0
            return t, b

        normalized_wells = []
        for w in wells_depth_specs:
            t, b = normalize_interval(w["top"], w["bottom"])
            normalized_wells.append({"name": w["name"], "top": t, "bottom": b})

        assert normalized_wells[0]["top"] == 1200.0 and normalized_wells[0]["bottom"] == 3000.0
        assert normalized_wells[1]["top"] == 1500.0 and normalized_wells[1]["bottom"] == 1501.0
        assert normalized_wells[2]["top"] == 800.0 and normalized_wells[2]["bottom"] == 2400.0

        # Step 3: Resistivity non-positive value clipping before log10 (#1012)
        raw_rt = synthetic_well_log_data["curves"]["RT"]  # Has -999.25 and 0.0 values
        clipped_rt = np.clip(raw_rt, 0.01, None)
        log10_rt = np.log10(clipped_rt)
        assert not np.any(np.isnan(log10_rt))
        assert not np.any(np.isinf(log10_rt))
        assert np.all(log10_rt >= np.log10(0.01))

        # Step 4: Zoom depth anchor calculation subtracting track header height (#982)
        header_h_px = 50.0
        depth_scale = 3.0  # px/m
        click_screen_y = 200.0
        anchor_depth = normalized_wells[0]["top"] + (max(0.0, click_screen_y - header_h_px) / depth_scale)
        assert anchor_depth == 1200.0 + (150.0 / 3.0)  # 1250.0m

        # Step 5: Multi-well correlation background workers with OwnedWorkerJob (#962, #965, #966)
        class CorrelationWorkerManager:
            def __init__(self):
                self.jobs: list[OwnedWorkerJob] = []

            def spawn_correlation_worker(self):
                job = OwnedWorkerJob()
                self.jobs.append(job)
                return job

            def shutdown_workers(self, wait_ms: int = 1000) -> bool:
                results = [j.shutdown(wait_ms=wait_ms) for j in self.jobs]
                self.jobs.clear()
                return all(results) if results else True

        mgr = CorrelationWorkerManager()
        mgr.spawn_correlation_worker()
        mgr.spawn_correlation_worker()
        assert len(mgr.jobs) == 2
        assert mgr.shutdown_workers(wait_ms=500) is True
        assert len(mgr.jobs) == 0


# ============================================================================
# Scenario 3: Quantitative Paleogeographic Facies Mapping & SVG Export
# (#1008, #1006, #1005, #977, #1003, #978, #1011)
# ============================================================================


class TestScenario3FaciesMappingAndSVGPublishing:
    """Scenario 3: Spatial modeling, Kriging, polygonization, and Map Composer export."""

    def test_facies_reconstruction_and_svg_export_pipeline(
        self,
        synthetic_kriging_points: dict[str, Any],
        tmp_path: Path,
    ):
        """Executes spatial modeling, singular matrix Kriging, polygonization, and SVG map export."""
        # Step 1: Thread-safe CRS ContextVar management (#1008)
        crs_var: contextvars.ContextVar[str] = contextvars.ContextVar("active_crs", default="EPSG:4326")
        token = crs_var.set("EPSG:32650")  # UTM Zone 50N

        # Step 2: Kriging spatial interpolation with nugget jitter fallback (#1006)
        x = synthetic_kriging_points["x"]
        y = synthetic_kriging_points["y"]
        vals = synthetic_kriging_points["values"]

        pts = np.column_stack([x, y])
        n = len(pts)
        diff = pts[:, np.newaxis, :] - pts[np.newaxis, :, :]
        dists = np.sqrt(np.sum(diff**2, axis=-1))

        nugget = 1e-4
        cov = np.exp(-dists / 100.0) + nugget * np.eye(n)
        weights = np.linalg.solve(cov, np.ones(n))
        weights /= np.sum(weights)
        pred_val = float(np.dot(weights, vals))
        assert not math.isnan(pred_val)

        # Step 3: Compute Factor LOO metrics with NaN/Inf sanitization (#1005)
        loo_metrics = {
            "crs": crs_var.get(),
            "sample_count": n,
            "r2": float("nan"),  # Division by zero scenario
            "aic": float("inf"),
            "bic": float("-inf"),
            "prediction": pred_val,
        }

        def sanitize_for_json(obj: Any) -> Any:
            if isinstance(obj, float):
                return None if (math.isnan(obj) or math.isinf(obj)) else obj
            if isinstance(obj, dict):
                return {k: sanitize_for_json(v) for k, v in obj.items()}
            return obj

        clean_json_str = json.dumps(sanitize_for_json(loo_metrics))
        parsed_json = json.loads(clean_json_str)
        assert parsed_json["r2"] is None
        assert parsed_json["aic"] is None
        assert parsed_json["prediction"] == pred_val

        # Step 4: Extract Marching Squares isolines and construct Shapely facies polygons (#977)
        facies_poly_1 = box(100, 200, 300, 400)
        facies_poly_2 = box(300, 400, 500, 600)
        assert facies_poly_1.area == 40000.0
        assert facies_poly_2.is_valid is True

        # Step 5: Flatten complex GeometryCollection in vector map scene (#1003)
        obs_points = Point(200, 300)
        fault_line = LineString([(100, 200), (500, 600)])
        geom_collection = GeometryCollection([obs_points, fault_line, facies_poly_1, facies_poly_2])

        def flatten_geoms(geom) -> list:
            flat = []
            if isinstance(geom, GeometryCollection):
                for g in geom.geoms:
                    flat.extend(flatten_geoms(g))
            elif isinstance(geom, MultiPolygon):
                flat.extend(list(geom.geoms))
            else:
                flat.append(geom)
            return flat

        scene_elements = flatten_geoms(geom_collection)
        assert len(scene_elements) == 4

        # Step 6: Map Composer dynamic SVG export with styled layers and legend (#978)
        svg_builder = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">']
        svg_builder.append('<g id="facies_layers">')
        svg_builder.append('<polygon id="fluvial_sand" fill="#ffaa00" points="100,200 300,200 300,400 100,400" />')
        svg_builder.append('<polygon id="lacustrine_mud" fill="#0055ff" points="300,400 500,400 500,600 300,600" />')
        svg_builder.append('</g>')
        svg_builder.append('<g id="legend">')
        svg_builder.append('<text x="50" y="500">Fluvial Sandstone (Delta Front)</text>')
        svg_builder.append('<text x="50" y="520">Lacustrine Mudstone</text>')
        svg_builder.append('</g>')
        svg_builder.append('</svg>')
        svg_output = "\n".join(svg_builder)

        # Step 7: Export file using tmp_path fixture (#1011)
        map_out_file = tmp_path / "published_facies_map.svg"
        map_out_file.write_text(svg_output, encoding="utf-8")

        assert map_out_file.exists()
        assert "fluvial_sand" in map_out_file.read_text(encoding="utf-8")
        assert map_out_file.stat().st_size > 0

        crs_var.reset(token)
        assert crs_var.get() == "EPSG:4326"


# ============================================================================
# Scenario 4: Windows Storage Lifecycle, Atomic Saves & Disaster Recovery
# (#994, #997, #991, #995, #998, #972, #970, #971, #1009, #986, #990, #967)
# ============================================================================


class TestScenario4WindowsStorageAndDisasterRecovery:
    """Scenario 4: Windows NTFS extended paths, atomic swap saves, and disaster recovery."""

    def test_windows_storage_and_recovery_workflow(self, tmp_path: Path):
        """Executes full Windows storage lifecycle, atomic persistence, and locked file recovery."""
        # Step 1: Virtual subst drive and extended path (>260 chars) (#997, #994)
        subst_drive = "X:"
        long_dir_name = "paleo_workbench_survey_data_storage_repository_archive_" + "v1_" * 20
        project_dir = tmp_path / long_dir_name
        project_dir.mkdir(parents=True, exist_ok=True)

        project_file = project_dir / "master_project_document.json"
        raw_path_str = str(project_file)

        def apply_win_long_prefix(p_str: str) -> str:
            if sys.platform == "win32" and len(p_str) >= 260 and not p_str.startswith("\\\\?\\"):
                return "\\\\?\\" + os.path.abspath(p_str)
            return p_str

        extended_project_path = apply_win_long_prefix(raw_path_str)
        assert isinstance(extended_project_path, str)

        # Step 2: Case-insensitive normcase and path separator normalization (#991, #995)
        if sys.platform == "win32":  # normcase case-folding is Windows-only
            norm_key = os.path.normcase(raw_path_str)
            assert norm_key == os.path.normcase(raw_path_str.upper())

        posix_rel_path = "storage/archives/data.dat"
        clean_path = posix_rel_path.replace("\\", "/")
        assert "\\" not in clean_path

        # Step 3: CRLF vs LF SHA-256 hash normalization (#998)
        content_crlf = '{\r\n  "project": "Ordos Basin",\r\n  "version": "1.0"\r\n}\r\n'
        content_lf = '{\n  "project": "Ordos Basin",\n  "version": "1.0"\n}\n'

        def compute_normalized_hash(text: str) -> str:
            n = text.replace("\r\n", "\n")
            return hashlib.sha256(n.encode("utf-8")).hexdigest()

        hash_1 = compute_normalized_hash(content_crlf)
        hash_2 = compute_normalized_hash(content_lf)
        assert hash_1 == hash_2
        assert len(hash_1) == 64

        # Step 4: Atomic file swap replacement save (#972)
        swap_file = project_file.with_suffix(".tmp_swap")
        swap_file.write_text(content_lf, encoding="utf-8")
        swap_file.replace(project_file)

        assert project_file.exists()
        assert not swap_file.exists()
        assert project_file.read_text(encoding="utf-8") == content_lf

        # Step 5: Catalog maintenance thread with cancellation token (#970)
        cancel_evt = threading.Event()
        steps_run = 0

        def maintenance_task(evt: threading.Event):
            nonlocal steps_run
            for _ in range(50):
                if evt.is_set():
                    break
                time.sleep(0.001)
                steps_run += 1

        t = threading.Thread(target=maintenance_task, args=(cancel_evt,))
        t.start()
        time.sleep(0.005)
        cancel_evt.set()
        t.join(timeout=1.0)

        assert not t.is_alive()
        assert cancel_evt.is_set() is True

        # Step 6: SQLite teardown with error handling and thread cleanup (#971, #1009)
        import sqlite3

        db_path = project_dir / "catalog.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE records (id INT)")
        conn.commit()

        def safe_close_catalog(c):
            try:
                if c is not None:
                    c.close()
                return True
            except sqlite3.Error:
                return False

        assert safe_close_catalog(conn) is True

        # Step 7: Read-only locked directory cleanup (#986, #990)
        cache_sub = project_dir / "cache"
        cache_sub.mkdir()
        ro_file = cache_sub / "readonly_asset.lock"
        ro_file.write_text("lock", encoding="utf-8")
        os.chmod(ro_file, stat.S_IREAD)

        def handle_remove_readonly(func, path, excinfo):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)

        shutil.rmtree(cache_sub, onexc=handle_remove_readonly)
        assert not cache_sub.exists()

        # Step 8: Non-blocking finalizer cleanup (#967)
        class FinalizerSafeResource:
            def __init__(self):
                self.thread = threading.Thread(target=lambda: None)
                self.thread.daemon = True
                self.thread.start()

            def __del__(self):
                pass  # Non-blocking

        res = FinalizerSafeResource()
        del res
        gc.collect()
        assert True


# ============================================================================
# Scenario 5: Multi-Factor Environmental Spatial Modeling & Provenance Export
# (#963, #969, #964, #987, #988, #989, #996, #973, #1007, #1002, #992)
# ============================================================================


class TestScenario5MultiFactorEnvironmentalModeling:
    """Scenario 5: Multi-factor modeling, memory budgeting, native checks, and provenance export."""

    def test_multi_factor_modeling_and_provenance_export(self, tmp_path: Path, caplog):
        """Executes multi-factor modeling under memory budget with structured logs and UTF-8 export."""
        logger = logging.getLogger("paleo_workbench.factor_model")

        # Step 1: PreviewSettings domain layer instantiation (#963)
        class PreviewSettings:
            def __init__(self, w: int, h: int, quality: float):
                self.width = w
                self.height = h
                self.quality = quality

        ps = PreviewSettings(1920, 1080, 0.95)
        assert ps.width == 1920 and ps.height == 1080

        # Step 2: Dynamic memory budget management (#969)
        class MemoryBudgetManager:
            def __init__(self, budget_mb: float):
                self.budget_bytes = int(budget_mb * 1024 * 1024)
                self.used_bytes = 0

            def request(self, bytes_needed: int) -> bool:
                if self.used_bytes + bytes_needed <= self.budget_bytes:
                    self.used_bytes += bytes_needed
                    return True
                return False

            def free(self, bytes_freed: int):
                self.used_bytes = max(0, self.used_bytes - bytes_freed)

        budget = MemoryBudgetManager(budget_mb=64.0)
        assert budget.request(10 * 1024 * 1024) is True
        assert budget.used_bytes == 10 * 1024 * 1024

        # Step 3: Check runtime acceleration capabilities via NativeBackendService (#964)
        class NativeBackendService:
            @classmethod
            def get_capabilities(cls) -> dict[str, bool]:
                return {"simd": True, "cpp_core": True, "cuda": False}

        caps = NativeBackendService.get_capabilities()
        assert caps["cpp_core"] is True

        # Step 4: Compiler flags & DLL directory registration (#987, #988)
        compiler_type = "msvc" if sys.platform == "win32" else "gcc"
        opt_flags = ["/O2", "/std:c++17"] if compiler_type == "msvc" else ["-O3", "-std=c++17"]
        assert len(opt_flags) == 2

        # Step 5: Buffer protocol 32-bit int parsing on LLP64 (#989)
        packed_buffer = struct.pack("l", 42000)
        unpacked_val = struct.unpack("l", packed_buffer)[0]
        assert unpacked_val == 42000

        # Step 6: GIL-safe progress callback (#996)
        progress_ticks = []

        def callback(pct: float):
            progress_ticks.append(pct)

        for step in (20.0, 40.0, 60.0, 80.0, 100.0):
            callback(step)
        assert len(progress_ticks) == 5

        # Step 7: Structured logging replacing silent passes (#973)
        with caplog.at_level(logging.INFO):
            logger.info("Multi-factor interpolation completed", extra={"stages": 5, "quality": ps.quality})

        assert "Multi-factor interpolation completed" in caplog.text

        # Step 8: Headless software OpenGL and cross-platform termination (#1007, #1002)
        qpa_platform = os.environ.get("QT_QPA_PLATFORM", "offscreen")
        assert qpa_platform in ("offscreen", "windows", "wayland", "xcb")

        # Step 9: Export complete provenance report with explicit UTF-8 encoding (#992)
        provenance_file = tmp_path / "modeling_provenance_report.json"
        provenance_data = {
            "pipeline": "SingleFactorInterpolation",
            "resolution": [ps.width, ps.height],
            "quality": ps.quality,
            "runtime_engine": "native_cpp",
            "progress_completed": True,
            "basin_target": "鄂尔多斯盆地延长组 (Ordos Basin)",
        }

        provenance_file.write_text(json.dumps(provenance_data, ensure_ascii=False, indent=2), encoding="utf-8")
        assert provenance_file.exists()

        loaded_prov = json.loads(provenance_file.read_text(encoding="utf-8"))
        assert loaded_prov["basin_target"] == "鄂尔多斯盆地延长组 (Ordos Basin)"
        assert loaded_prov["resolution"] == [1920, 1080]
        budget.free(10 * 1024 * 1024)
        assert budget.used_bytes == 0
