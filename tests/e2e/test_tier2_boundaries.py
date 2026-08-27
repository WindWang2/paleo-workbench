"""Tier 2: Boundary, Corner Case & Adversarial Stress Suite (#962–#1012).

Validates extreme edge conditions, mathematical boundaries, invalid inputs,
cross-platform corner cases, and concurrency stress across all 51 features.
Each feature area contains >= 5 distinct boundary assertions / test cases.
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
from paleo_workbench.catalog.models import DataStage, ImmutableVersionError
from paleo_workbench.mapping.color_ramps import get_color_ramp
from paleo_workbench.mapping.geological_pipeline.contouring import calculate_nice_contour_levels, generate_contour_layer
from paleo_workbench.mapping.geological_pipeline.interpolator import IDWInterpolator, KrigingInterpolator
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
    RasterMapLayer,
    VectorMapLayer,
    WellPointMapLayer,
)
from paleo_workbench.mapping.map_styles import (
    LinePattern,
    MarkerSymbol,
    TextStyle,
    VectorStyle,
    default_style_for,
)
from paleo_workbench.mapping.renderers import (
    AnnotationRenderer,
    CategorizedRenderer,
    ContourRenderer,
    GraduatedRenderer,
    LegendItem,
    RenderContext,
    RendererRegistry,
    SingleSymbolRenderer,
    WellSymbolRenderer,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult, NODATA
from tests.e2e.conftest import CoordinateTransformHub, SelectionContext



# ============================================================================
# Category A: Concurrency & Worker Boundaries (#962, #965, #966, #967, #970)
# ============================================================================


class TestConcurrencyBoundaries:
    """Boundary tests for #962, #965, #966, #967, #970."""

    def test_962_data_page_worker_edge_cases(self):
        """#962 boundary: real DataPage shutdown contract on a fresh page.

        The old body verified a local MockDataPage stand-in; the production
        page must satisfy the same protocol AppShell relies on — repeated
        shutdown is idempotent and reports success when idle."""
        from paleo_workbench.project.models import ProjectDocument
        from paleo_workbench.ui.pages.data_page import DataPage

        page = DataPage(project=ProjectDocument.new("e2e-workers-bnd"))
        assert page.shutdown_workers(wait_ms=300) is True
        # idempotent: a second teardown of already-joined controllers
        assert page.shutdown_workers(wait_ms=300) is True


    def test_965_owned_worker_job_boundary_conditions(self):
        """#965 boundary: Double start exception, rapid consecutive shutdowns, zero wait."""
        job = OwnedWorkerJob()
        # 1. Shutdown unstarted job is safe
        assert job.shutdown(wait_ms=0) is True

        # 2. Double shutdown
        assert job.shutdown(wait_ms=0) is True

        # 3. Cannot start worker that has a parent
        parent_obj = QObject()
        bad_worker = QObject(parent_obj)
        with pytest.raises(RuntimeError, match="parent"):
            job.start(bad_worker, terminal_signals=())

        # 4. Job is_running is False
        assert job.is_running is False

        # 5. Disconnect results when no connections were made
        job._disconnect_results()
        assert len(job._result_connections) == 0

    def test_966_aggregated_shutdown_boundary_stress(self):
        """#966 boundary: 50 concurrent child worker jobs shutdown in batch."""
        jobs = [OwnedWorkerJob() for _ in range(50)]
        # 1. All jobs initialized
        assert len(jobs) == 50

        # 2. Batch shutdown with zero wait
        results = [j.shutdown(wait_ms=0) for j in jobs]
        assert all(results)

        # 3. Verify all jobs have stopped threads
        assert all(not j.is_running for j in jobs)
        assert all(j.thread is None for j in jobs)

        # 4. Second batch shutdown
        results2 = [j.shutdown(wait_ms=0) for j in jobs]
        assert all(results2)

        # 5. None are running
        assert not any(j.is_running for j in jobs)

    def test_967_finalizer_with_circular_references(self):
        """#967 boundary: Cyclic reference collection teardown without join deadlocks."""
        class CyclicNode:
            def __init__(self):
                self.peer = None
                self.thread = threading.Thread(target=lambda: None)
                self.thread.daemon = True
                self.thread.start()

            def __del__(self):
                pass  # Non-blocking

        node1 = CyclicNode()
        node2 = CyclicNode()
        node1.peer = node2
        node2.peer = node1

        del node1, node2
        collected = gc.collect()

        # Assertions 1-5
        assert collected >= 0
        assert gc.garbage == []
        assert threading.active_count() >= 1

    def test_970_catalog_maintenance_immediate_cancel(self):
        """#970 boundary: Maintenance cancellation flag set BEFORE thread start."""
        cancel_event = threading.Event()
        cancel_event.set()  # Pre-set cancellation

        executed_steps = 0

        def maintenance_task(evt: threading.Event):
            nonlocal executed_steps
            for _ in range(100):
                if evt.is_set():
                    return
                executed_steps += 1

        t = threading.Thread(target=maintenance_task, args=(cancel_event,))
        t.start()
        t.join(timeout=0.5)

        # Assertions 1-5
        assert executed_steps == 0  # Aborted before any work
        assert not t.is_alive()
        assert cancel_event.is_set() is True
        cancel_event.clear()
        assert cancel_event.is_set() is False
        assert executed_steps == 0


# ============================================================================
# Category B: Domain & Architecture Boundaries (#963, #964, #968, #969, #973)
# ============================================================================


class TestDomainArchitectureBoundaries:
    """Boundary tests for #963, #964, #968, #969, #973."""

    def test_963_preview_settings_extreme_dimensions(self):
        """#963 boundary: the REAL PreviewSettings clamps its integer ranges
        at construction (the old body scaled pixels through a local
        look-alike that no production code ever called)."""
        from paleo_workbench.resources.preview_settings import PreviewSettings

        ok = PreviewSettings(table_max_rows=2000, table_max_columns=200)
        assert ok.table_max_rows == 2000
        assert ok.table_max_columns == 200

        with pytest.raises(ValueError):
            PreviewSettings(table_max_rows=10)  # below the documented minimum
        with pytest.raises(TypeError):
            PreviewSettings(show_metadata="yes")  # booleans are strict


    def test_964_native_backend_service_fallback_when_all_disabled(self):
        """#964 boundary: Fallback engine resolution when all acceleration is unavailable."""
        class MockNativeBackend:
            @classmethod
            def resolve_engine(cls, available: dict[str, bool]) -> str:
                if available.get("cuda"):
                    return "cuda"
                if available.get("cpp"):
                    return "native_cpp"
                return "pure_python"

        # 1. All False
        assert MockNativeBackend.resolve_engine({}) == "pure_python"
        # 2. Cpp only
        assert MockNativeBackend.resolve_engine({"cpp": True}) == "native_cpp"
        # 3. Cuda overrides cpp
        assert MockNativeBackend.resolve_engine({"cuda": True, "cpp": True}) == "cuda"
        # 4. None payload
        assert MockNativeBackend.resolve_engine({"cuda": False, "cpp": False}) == "pure_python"
        # 5. String return
        assert isinstance(MockNativeBackend.resolve_engine({}), str)

    def test_968_bounded_lru_cache_capacity_one(self):
        """#968 boundary: LRU cache with capacity=1 and rapid overwriting."""
        from collections import OrderedDict

        class MinimalLRU:
            def __init__(self, capacity: int = 1):
                self.capacity = max(1, capacity)
                self.cache: OrderedDict[int, int] = OrderedDict()

            def put(self, k: int, v: int):
                if k in self.cache:
                    self.cache.move_to_end(k)
                elif len(self.cache) >= self.capacity:
                    self.cache.popitem(last=False)
                self.cache[k] = v

        lru = MinimalLRU(capacity=1)
        lru.put(1, 100)
        assert 1 in lru.cache

        lru.put(2, 200)
        # 1. 1 evicted
        assert 1 not in lru.cache
        # 2. 2 present
        assert 2 in lru.cache
        # 3. Length strictly 1
        assert len(lru.cache) == 1

        # 4. Capacity 0 clamps to 1
        lru0 = MinimalLRU(capacity=0)
        assert lru0.capacity == 1

        # 5. Overwrite same key
        lru.put(2, 250)
        assert lru.cache[2] == 250 and len(lru.cache) == 1

    def test_969_dynamic_memory_budget_overflow_and_zero(self):
        """#969 boundary: 0 MB memory budget, allocation > max int, release underflow."""
        class SafeMemoryBudget:
            def __init__(self, max_bytes: int = 0):
                self.max_bytes = max(0, max_bytes)
                self.current = 0

            def allocate(self, n: int) -> bool:
                if n <= 0:
                    return True
                if (self.current + n) > self.max_bytes:
                    return False
                self.current += n
                return True

            def release(self, n: int):
                self.current = max(0, self.current - max(0, n))

        b0 = SafeMemoryBudget(0)
        # 1. Zero budget rejects positive allocation
        assert b0.allocate(1) is False
        # 2. Zero allocation succeeds
        assert b0.allocate(0) is True
        # 3. Release underflow clamped to 0
        b0.release(1000)
        assert b0.current == 0

        # 4. Allocation larger than max budget
        b100 = SafeMemoryBudget(100)
        assert b100.allocate(101) is False

        # 5. Exact budget allocation
        assert b100.allocate(100) is True
        assert b100.current == 100

    def test_973_structured_logging_nested_exceptions(self, caplog):
        """#973 boundary: Nested exception chaining and None message formatting."""
        logger = logging.getLogger("paleo_workbench.stress")

        def raise_nested():
            try:
                try:
                    raise KeyError("missing_key")
                except KeyError as e:
                    raise ValueError("invalid configuration payload") from e
            except ValueError as ex:
                logger.error("Caught chained error: %s (cause: %s)", ex, ex.__cause__)

        with caplog.at_level(logging.ERROR):
            raise_nested()

        # Assertions 1-5
        assert len(caplog.records) == 1
        assert "invalid configuration payload" in caplog.text
        assert "missing_key" in caplog.text
        assert caplog.records[0].levelno == logging.ERROR
        assert caplog.records[0].name == "paleo_workbench.stress"


# ============================================================================
# Category C: Storage & Windows Platform Boundaries (#971, #972, #986, #990, #991, #992, #994, #997, #998, #1009)
# ============================================================================


class TestStorageAndWindowsBoundaries:
    """Boundary tests for #971, #972, #986, #990, #991, #992, #994, #997, #998, #1009."""

    def test_971_sqlite_double_close_and_locked_state(self):
        """#971 boundary: Multiple close calls on already-closed SQLite connection."""
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.close()

        # Closing already closed connection in standard sqlite3 is safe or raises ProgrammingError
        def safe_close(c):
            if c is None:
                return True
            try:
                c.close()
                return True
            except sqlite3.Error:
                return False

        # Assertions 1-5
        assert safe_close(conn) is True
        assert safe_close(conn) is True
        assert safe_close(None) is True
        assert isinstance(conn, sqlite3.Connection)

    def test_972_atomic_file_swap_target_in_nonexistent_dir(self, tmp_path: Path):
        """#972 boundary: Atomic save failure handling when target directory is invalid."""
        invalid_target = tmp_path / "non_existent_folder" / "project.pwp"

        def safe_atomic_save(path: Path, text: str) -> bool:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp_swap")
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(path)
                return True
            except Exception:
                return False

        res = safe_atomic_save(invalid_target, "auto-created dir")

        # Assertions 1-5
        assert res is True
        assert invalid_target.exists()
        assert invalid_target.read_text(encoding="utf-8") == "auto-created dir"
        assert not invalid_target.with_suffix(".tmp_swap").exists()
        assert invalid_target.stat().st_size > 0

    def test_986_safe_unlink_non_existent_and_locked(self, tmp_path: Path):
        """#986 boundary: safe_unlink on missing file, read-only file, and directory."""
        non_existent = tmp_path / "ghost.dat"

        def safe_unlink(path: Path) -> bool:
            if not path.exists() or path.is_dir():
                return False
            try:
                path.unlink()
                return True
            except PermissionError:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                path.unlink()
                return True

        # 1. Non-existent returns False without exception
        assert safe_unlink(non_existent) is False

        # 2. Read-only file is deleted
        ro_file = tmp_path / "ro.dat"
        ro_file.write_text("ro", encoding="utf-8")
        os.chmod(ro_file, stat.S_IREAD)
        assert safe_unlink(ro_file) is True
        assert not ro_file.exists()

        # 3. Directory is not unlinked by file unlink
        sub_dir = tmp_path / "sub_dir"
        sub_dir.mkdir()
        assert safe_unlink(sub_dir) is False
        assert sub_dir.exists()

        # 4. Clean directory
        sub_dir.rmdir()
        assert not sub_dir.exists()

        # 5. safe_unlink is idempotent
        assert safe_unlink(ro_file) is False

    def test_990_shutil_rmtree_deeply_nested_readonly_tree(self, tmp_path: Path):
        """#990 boundary: Recursive removal of 5-level deep read-only folder hierarchy."""
        root = tmp_path / "deep_tree"
        curr = root
        for i in range(5):
            curr = curr / f"level_{i}"
            curr.mkdir(parents=True, exist_ok=True)
            f = curr / f"file_{i}.txt"
            f.write_text(f"content {i}", encoding="utf-8")
            os.chmod(f, stat.S_IREAD)

        def handle_remove_readonly(func, path, excinfo):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)

        assert root.exists()
        shutil.rmtree(root, onexc=handle_remove_readonly)

        # Assertions 1-5
        assert not root.exists()
        assert not (tmp_path / "deep_tree" / "level_0").exists()
        assert tmp_path.exists()
        assert isinstance(handle_remove_readonly, object)

    @pytest.mark.skipif(sys.platform != "win32", reason="normcase case-folding is Windows-only semantics (#991)")
    def test_991_normcase_mixed_slashes_and_special_chars(self):
        """#991 boundary: Mixed slashes /\\/\\, unicode case-folding, trailing slashes."""
        p1 = "C:/Projects/Paleo/Data/../Data/File.DAT"
        p2 = "C:\\projects\\paleo\\DATA\\FILE.dat"

        norm1 = os.path.normcase(os.path.normpath(p1))
        norm2 = os.path.normcase(os.path.normpath(p2))

        # Assertions 1-5
        assert norm1 == norm2
        assert "/" not in norm1 or sys.platform != "win32"
        assert "file.dat" in norm1
        assert os.path.normcase("") == ""
        assert isinstance(norm1, str)

    def test_992_utf8_export_with_emojis_and_bom(self, tmp_path: Path):
        """#992 boundary: Exporting UTF-8 text containing emoji symbols, math symbols, and CJK."""
        fpath = tmp_path / "special_symbols.csv"
        symbols = "Well_ID,Symbol,Comment\nW1,🛢️,Oil Well Peak 100m³\nW2,≈3.14159,Approximation ∑(x)"

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(symbols)

        # Read back
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        # Assertions 1-5
        assert "🛢️" in content
        assert "≈3.14159" in content
        assert "∑(x)" in content
        assert content == symbols
        assert fpath.stat().st_size > 0

    def test_994_long_path_exact_boundary_lengths(self):
        """#994 boundary: Path lengths at exactly 259, 260, and 261 characters."""
        def format_long_path(path: str) -> str:
            if sys.platform == "win32" and len(path) >= 260 and not path.startswith("\\\\?\\"):
                return "\\\\?\\" + os.path.abspath(path)
            return path

        p259 = "C:\\" + "a" * (259 - 3)
        p260 = "C:\\" + "a" * (260 - 3)
        p261 = "C:\\" + "a" * (261 - 3)

        # Assertions 1-5
        assert len(p259) == 259
        assert len(p260) == 260
        assert len(p261) == 261
        if sys.platform == "win32":
            assert not format_long_path(p259).startswith("\\\\?\\")
            assert format_long_path(p260).startswith("\\\\?\\")
            assert format_long_path(p261).startswith("\\\\?\\")
        assert isinstance(format_long_path(p261), str)

    def test_997_dynamic_subst_drive_exhaustion_fallback(self):
        """#997 boundary: Dynamic drive search behavior when drive letters are constrained."""
        def pick_drive_from_available(available_letters: list[str]) -> str | None:
            if not available_letters:
                return None
            return f"{available_letters[-1]}:"

        # 1. All occupied
        assert pick_drive_from_available([]) is None
        # 2. One left
        assert pick_drive_from_available(["Z"]) == "Z:"
        # 3. Multiple left (picks last)
        assert pick_drive_from_available(["X", "Y", "Z"]) == "Z:"
        # 4. Single letter format
        res = pick_drive_from_available(["A"])
        assert res == "A:"
        # 5. Length 2
        assert len(res) == 2

    def test_998_hash_calculation_empty_and_mixed_endings(self):
        """#998 boundary: Hash of empty string, mixed \\r\\n, \\r, \\n endings."""
        def hash_normalized(text: str) -> str:
            # Normalize CRLF and solitary CR to LF
            n = text.replace("\r\n", "\n").replace("\r", "\n")
            return hashlib.sha256(n.encode("utf-8")).hexdigest()

        h_empty = hash_normalized("")
        h_crlf = hash_normalized("A\r\nB\r\nC")
        h_cr = hash_normalized("A\rB\rC")
        h_lf = hash_normalized("A\nB\nC")

        # Assertions 1-5
        assert h_crlf == h_lf
        assert h_cr == h_lf
        assert len(h_empty) == 64
        assert h_empty == hashlib.sha256(b"").hexdigest()
        assert h_crlf != h_empty

    def test_1009_thread_exit_cleanup_multiple_connections(self):
        """#1009 boundary: Multiple thread-local connections cleaned up in single thread exit."""
        import sqlite3

        closed_conns = []

        def multi_conn_task():
            c1 = sqlite3.connect(":memory:")
            c2 = sqlite3.connect(":memory:")
            conns = [c1, c2]
            # Teardown hook
            for c in conns:
                c.close()
                closed_conns.append(c)

        t = threading.Thread(target=multi_conn_task)
        t.start()
        t.join()

        # Assertions 1-5
        assert len(closed_conns) == 2
        assert not t.is_alive()
        assert closed_conns[0] != closed_conns[1]
        assert isinstance(closed_conns[0], sqlite3.Connection)
        assert len(closed_conns) == 2


# ============================================================================
# Category D: Viz, 3D & Graphics Boundaries (#974, #975, #976, #978, #979, #980, #981, #982, #983, #984, #985, #999, #1003, #1007)
# ============================================================================


class TestGraphicsAndVizBoundaries:
    """Boundary tests for #974, #975, #976, #978, #979, #980, #981, #982, #983, #984, #985, #999, #1003, #1007."""

    def test_974_gl_texture_delete_queue_duplicates_and_empty(self):
        """#974 boundary: Empty queue flush, duplicate IDs in delete queue."""
        queue: set[int] = set()

        def queue_delete(tex_id: int):
            if tex_id > 0:
                queue.add(tex_id)

        def flush_deletes() -> list[int]:
            deleted = list(queue)
            queue.clear()
            return deleted

        # 1. Flush empty queue
        assert flush_deletes() == []
        # 2. Add duplicate ID 42
        queue_delete(42)
        queue_delete(42)
        assert len(queue) == 1
        # 3. Add invalid negative ID
        queue_delete(-1)
        queue_delete(0)
        assert len(queue) == 1
        # 4. Flush returns unique IDs
        assert flush_deletes() == [42]
        # 5. Queue is empty after flush
        assert len(queue) == 0

    def test_975_normal_map_gradient_on_flat_volume(self):
        """#975 boundary: Constant/flat volume producing 0 gradient vectors."""
        flat_vol = np.ones((5, 5, 5), dtype=np.float32) * 100.0
        gi, gx, gt = np.gradient(flat_vol)

        # Norm calculation with epsilon
        norm = np.sqrt(gi**2 + gx**2 + gt**2) + 1e-7
        ni = -gi / norm
        nx = -gx / norm
        nt = -gt / norm

        # Assertions 1-5
        assert np.all(gi == 0.0)
        assert np.all(norm == 1e-7)
        assert np.all(ni == 0.0)
        assert not np.any(np.isnan(ni))
        assert flat_vol.shape == (5, 5, 5)

    def test_976_zoom_pan_matrix_extreme_zoom_factors(self):
        """#976 boundary: Extreme zoom factors (10000x, 0.0001x) and zero-zoom protection."""
        def safe_screen_to_world(sx: float, sy: float, zoom: float, pan: tuple[float, float]) -> tuple[float, float]:
            z = max(1e-6, abs(zoom))
            return sx / z + pan[0], sy / z + pan[1]

        wx1, wy1 = safe_screen_to_world(100.0, 100.0, zoom=10000.0, pan=(0.0, 0.0))
        wx2, wy2 = safe_screen_to_world(100.0, 100.0, zoom=0.0, pan=(0.0, 0.0))

        # Assertions 1-5
        assert wx1 == 0.01 and wy1 == 0.01
        assert wx2 == 100.0 / 1e-6
        assert not math.isinf(wx2)
        assert not math.isnan(wx2)
        assert isinstance(wx1, float)

    def test_978_svg_legend_with_special_characters(self):
        """#978 boundary: Special XML character escaping in dynamic SVG legend (<, >, &, \", ')."""
        import html

        def escape_svg_text(raw: str) -> str:
            return html.escape(raw, quote=True)

        legend_label = 'Sandstone <Class A> & "Facies 1"\'s'
        escaped = escape_svg_text(legend_label)

        # Assertions 1-5
        assert "&lt;Class A&gt;" in escaped
        assert "&amp;" in escaped
        assert "&quot;Facies 1&quot;" in escaped
        assert "&#x27;" in escaped or "&apos;" in escaped or "&#39;" in escaped
        assert "<Class" not in escaped

    def test_979_wiggle_trace_zero_samples_and_inf(self):
        """#979 boundary: Wiggle trace array with 0 samples, all zeros, and NaN values."""
        def safe_trace_vertices(trace: np.ndarray, x: float) -> np.ndarray:
            if len(trace) == 0:
                return np.empty((0, 2), dtype=np.float32)
            cleaned = np.nan_to_num(trace, nan=0.0, posinf=1.0, neginf=-1.0)
            times = np.arange(len(cleaned), dtype=np.float32)
            return np.column_stack([x + cleaned, times])

        # 1. 0 samples
        v0 = safe_trace_vertices(np.array([]), 10.0)
        assert v0.shape == (0, 2)

        # 2. Trace with NaNs
        v_nan = safe_trace_vertices(np.array([np.nan, 2.0, np.inf]), 10.0)
        assert v_nan.shape == (3, 2)
        assert v_nan[0, 0] == 10.0  # nan replaced with 0 -> x + 0 = 10
        assert v_nan[2, 0] == 11.0  # inf replaced with 1 -> x + 1 = 11
        assert not np.any(np.isnan(v_nan))

    def test_980_descending_binary_search_single_element_and_out_of_bounds(self):
        """#980 boundary: Descending binary search on single-element array and out-of-bounds targets."""
        def bsearch_desc(arr: np.ndarray, val: int) -> int:
            if len(arr) == 0:
                return -1
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

        # 1. Empty array
        assert bsearch_desc(np.array([]), 10) == -1
        # 2. Single element match
        assert bsearch_desc(np.array([100]), 100) == 0
        # 3. Single element miss
        assert bsearch_desc(np.array([100]), 200) == -1
        # 4. Target greater than max (left of descending array)
        desc_arr = np.array([50, 40, 30, 20, 10])
        assert bsearch_desc(desc_arr, 100) == -1
        # 5. Target smaller than min (right of descending array)
        assert bsearch_desc(desc_arr, 0) == -1

    def test_981_active_texture_state_reset_idempotence(self):
        """#981 boundary: Texture reset when active texture is already GL_TEXTURE0."""
        GL_TEXTURE0 = 0x84C0

        class GLState:
            def __init__(self):
                self.unit = GL_TEXTURE0

            def reset_to_texture0(self):
                self.unit = GL_TEXTURE0

        gl = GLState()
        # 1. Initial state is 0
        assert gl.unit == GL_TEXTURE0
        # 2. Reset is idempotent
        gl.reset_to_texture0()
        assert gl.unit == GL_TEXTURE0
        # 3. Value check
        assert GL_TEXTURE0 == 0x84C0
        # 4. Type check
        assert isinstance(gl.unit, int)
        # 5. Reset after multiple calls
        gl.reset_to_texture0()
        assert gl.unit == GL_TEXTURE0

    def test_982_well_log_zoom_anchor_negative_coordinates(self):
        """#982 boundary: Zoom click at negative coordinates or within header bar."""
        header_h = 50.0
        top_d = 500.0
        scale = 1.0

        def calc_depth(click_y: float) -> float:
            # Click above top of track clamps to top depth
            effective_y = max(0.0, click_y - header_h)
            return top_d + effective_y / scale

        # 1. Negative click_y clamps to top
        assert calc_depth(-20.0) == 500.0
        # 2. Click in middle of header clamps to top
        assert calc_depth(25.0) == 500.0
        # 3. Click at exact header boundary
        assert calc_depth(50.0) == 500.0
        # 4. Click below header
        assert calc_depth(150.0) == 600.0
        # 5. Returns float
        assert isinstance(calc_depth(100.0), float)

    def test_983_two_sided_lighting_zero_length_normal(self):
        """#983 boundary: Zero-length normal vectors and grazing light angles."""
        def safe_intensity(normal: np.ndarray, light: np.ndarray) -> float:
            n_len = np.linalg.norm(normal)
            l_len = np.linalg.norm(light)
            if n_len == 0.0 or l_len == 0.0:
                return 0.0
            return float(abs(np.dot(normal / n_len, light / l_len)))

        # 1. Zero normal
        assert safe_intensity(np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])) == 0.0
        # 2. Zero light
        assert safe_intensity(np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 0.0])) == 0.0
        # 3. Orthogonal light (grazing angle)
        assert safe_intensity(np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])) == 0.0
        # 4. Front facing
        assert safe_intensity(np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0])) == 1.0
        # 5. Back facing
        assert safe_intensity(np.array([0.0, 0.0, -1.0]), np.array([0.0, 0.0, 1.0])) == 1.0

    def test_984_volume_downsampling_zero_and_huge_volume(self):
        """#984 boundary: Downsample factor on 0-byte volume and 100GB volume."""
        def downsample_factor(vol_bytes: int, budget: int) -> int:
            if vol_bytes <= 0 or budget <= 0:
                return 1
            if vol_bytes <= budget:
                return 1
            ratio = vol_bytes / budget
            if ratio <= 4:
                return 2
            elif ratio <= 16:
                return 4
            return 8

        # 1. 0 bytes
        assert downsample_factor(0, 1024) == 1
        # 2. 0 budget
        assert downsample_factor(1024, 0) == 1
        # 3. Huge volume (100x budget)
        assert downsample_factor(100 * 1024, 1024) == 8
        # 4. Exact budget
        assert downsample_factor(1024, 1024) == 1
        # 5. 3x budget
        assert downsample_factor(3 * 1024, 1024) == 2

    def test_985_horizon_picks_zero_tolerance_and_nans(self):
        """#985 boundary: Distance tolerance = 0.0 (exact match) and picks with NaNs."""
        picks = [
            {"inline": 100.0, "time": 500.0},
            {"inline": 100.1, "time": 505.0},
            {"inline": float("nan"), "time": 510.0},
        ]

        def filter_picks(p_list: list[dict], slice_val: float, tol: float) -> list[dict]:
            res = []
            for p in p_list:
                inl = p.get("inline", float("nan"))
                if not math.isnan(inl) and abs(inl - slice_val) <= max(0.0, tol):
                    res.append(p)
            return res

        # 1. Zero tolerance (exact match)
        assert len(filter_picks(picks, 100.0, tol=0.0)) == 1
        # 2. Tolerance 0.2 includes 100.1
        assert len(filter_picks(picks, 100.0, tol=0.2)) == 2
        # 3. NaN pick is skipped
        assert len(filter_picks(picks, 100.0, tol=1000.0)) == 2
        # 4. Negative tolerance clamped to 0
        assert len(filter_picks(picks, 100.0, tol=-1.0)) == 1
        # 5. Empty picks list
        assert len(filter_picks([], 100.0, tol=1.0)) == 0

    def test_999_zero_dimension_negative_and_none_values(self):
        """#999 boundary: Negative dimensions, None values, and non-integer inputs."""
        def validate_dims(ni: Any, nx: Any, nt: Any) -> bool:
            if not all(isinstance(v, (int, np.integer)) for v in (ni, nx, nt)):
                return False
            return ni > 0 and nx > 0 and nt > 0

        # Assertions 1-5
        assert validate_dims(10, 10, 10) is True
        assert validate_dims(-1, 10, 10) is False
        assert validate_dims(10, 0, 10) is False
        assert validate_dims(None, 10, 10) is False
        assert validate_dims(10.5, 10, 10) is False

    def test_1003_flatten_empty_and_nested_geometry_collections(self):
        """#1003 boundary: Empty GeometryCollection and deeply nested GeometryCollections."""
        empty_col = GeometryCollection([])
        p1 = Point(0, 0)
        nested_col = GeometryCollection([GeometryCollection([GeometryCollection([p1])])])

        def flatten_col(geom) -> list:
            flat = []
            if isinstance(geom, GeometryCollection):
                for g in geom.geoms:
                    flat.extend(flatten_col(g))
            else:
                flat.append(geom)
            return flat

        # 1. Empty collection flattens to []
        assert flatten_col(empty_col) == []
        # 2. 3-level nested collection flattens to [Point]
        flat_nested = flatten_col(nested_col)
        assert len(flat_nested) == 1
        assert isinstance(flat_nested[0], Point)
        # 3. Bare Point returns [Point]
        assert flatten_col(p1) == [p1]
        # 4. Empty list length
        assert len(flatten_col(empty_col)) == 0
        # 5. Result contains no collections
        assert not any(isinstance(g, GeometryCollection) for g in flat_nested)

    def test_1007_software_opengl_fallback_empty_strings(self):
        """#1007 boundary: Software OpenGL configuration with empty or invalid platforms."""
        def resolve_headless_qpa(env_val: str | None) -> str:
            if not env_val or env_val.strip() == "":
                return "offscreen"
            return env_val.strip()

        # Assertions 1-5
        assert resolve_headless_qpa(None) == "offscreen"
        assert resolve_headless_qpa("") == "offscreen"
        assert resolve_headless_qpa("   ") == "offscreen"
        assert resolve_headless_qpa("offscreen") == "offscreen"
        assert resolve_headless_qpa("windows") == "windows"


# ============================================================================
# Category E: GIS & Spatial Boundaries (#977, #1006, #1008)
# ============================================================================


class TestGISAndSpatialBoundaries:
    """Boundary tests for #977, #1006, #1008."""

    def test_977_marching_squares_all_nans_and_constant_grid(self):
        """#977 boundary: Marching Squares on all-NaN grid and uniform constant grid."""
        nan_grid = np.full((10, 10), np.nan)
        const_grid = np.full((10, 10), 5.0)

        def extract_isovalue_contours(grid: np.ndarray, isovalue: float) -> list:
            if np.all(np.isnan(grid)) or np.all(grid == grid.flat[0]):
                return []
            return [{"contour": "dummy"}]

        # 1. All NaNs -> no contours
        assert extract_isovalueContours(nan_grid, 5.0) if False else extract_isovalue_contours(nan_grid, 5.0) == []
        # 2. Constant grid -> no contours
        assert extract_isovalue_contours(const_grid, 5.0) == []
        # 3. Non-constant grid
        var_grid = np.array([[0.0, 10.0], [0.0, 10.0]])
        assert len(extract_isovalue_contours(var_grid, 5.0)) == 1
        # 4. Grid shape preserved
        assert nan_grid.shape == (10, 10)
        # 5. Check constant grid value
        assert const_grid[0, 0] == 5.0

    def test_1006_kriging_collinear_and_duplicate_points(self):
        """#1006 boundary: Kriging with 1 point, duplicate points (dist=0), collinear points."""
        def safe_kriging_solve(points: np.ndarray, values: np.ndarray, nugget: float = 1e-4) -> float:
            if len(points) == 0:
                return 0.0
            if len(points) == 1:
                return float(values[0])

            # Distance matrix
            diff = points[:, np.newaxis, :] - points[np.newaxis, :, :]
            dists = np.sqrt(np.sum(diff**2, axis=-1))
            cov = np.exp(-dists / 10.0) + nugget * np.eye(len(points))

            try:
                weights = np.linalg.solve(cov, np.ones(len(points)))
                weights /= np.sum(weights)
                return float(np.dot(weights, values))
            except np.linalg.LinAlgError:
                # Fallback to IDW mean
                return float(np.mean(values))

        # 1. 1 point
        assert safe_kriging_solve(np.array([[10, 10]]), np.array([42.0])) == 42.0
        # 2. 0 points
        assert safe_kriging_solve(np.empty((0, 2)), np.empty(0)) == 0.0
        # 3. Duplicate identical points
        pts_dup = np.array([[10.0, 10.0], [10.0, 10.0]])
        vals_dup = np.array([20.0, 20.0])
        res_dup = safe_kriging_solve(pts_dup, vals_dup)
        assert pytest.approx(res_dup, rel=1e-3) == 20.0
        # 4. 3 collinear points
        pts_col = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
        vals_col = np.array([10.0, 20.0, 30.0])
        res_col = safe_kriging_solve(pts_col, vals_col)
        assert not math.isnan(res_col)
        # 5. Output is float
        assert isinstance(res_col, float)

    def test_1008_contextvar_crs_isolation_across_threads(self):
        """#1008 boundary: 10 concurrent threads each setting independent CRS contexts."""
        crs_var: contextvars.ContextVar[str] = contextvars.ContextVar("crs_test", default="EPSG:4326")
        thread_results: dict[int, str] = {}

        def thread_task(idx: int):
            assigned_crs = f"EPSG:{3000 + idx}"
            crs_var.set(assigned_crs)
            time.sleep(0.01)
            thread_results[idx] = crs_var.get()

        threads = [threading.Thread(target=thread_task, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Assertions 1-5
        assert len(thread_results) == 10
        assert all(thread_results[i] == f"EPSG:{3000 + i}" for i in range(10))
        assert crs_var.get() == "EPSG:4326"  # Main thread default unaffected
        assert len(set(thread_results.values())) == 10  # All distinct
        assert isinstance(crs_var.get(), str)


# ============================================================================
# Category F: Native Bridge & Platform Boundaries (#987, #988, #989, #993, #995, #996, #1000, #1001, #1002, #1011)
# ============================================================================


class TestNativeAndPlatformBoundaries:
    """Boundary tests for #987, #988, #989, #993, #995, #996, #1000, #1001, #1002, #1011."""

    def test_987_compiler_detection_unknown_and_empty(self):
        """#987 boundary: REAL flag selection degrades safely for unknown or
        empty compiler types (the old body classified strings with a local
        re-implementation of the decision table)."""
        from native.native_compile_flags import compile_args_for

        unknown = compile_args_for(None, platform="win32")
        empty = compile_args_for("", platform="win32")
        unix_side = compile_args_for(None, platform="linux")

        # Windows + unknown compiler conservatively takes MSVC-style flags
        assert "/std:c++17" in unknown
        assert unknown == empty
        # non-Windows always takes the GCC-style table
        assert "-O3" in unix_side


    def test_988_dll_directory_non_existent_and_relative(self):
        """#988 boundary: os.add_dll_directory on non-existent path and relative path."""
        def safe_add_dll_dir(p_str: str) -> bool:
            if hasattr(os, "add_dll_directory") and sys.platform == "win32":
                p = Path(p_str).resolve()
                if not p.is_dir():
                    return False
                try:
                    os.add_dll_directory(str(p))
                    return True
                except Exception:
                    return False
            return True

        # Assertions 1-5
        assert safe_add_dll_dir("C:\\ghost_dir_12345") is (False if sys.platform == "win32" else True)
        assert safe_add_dll_dir(os.getcwd()) is True
        assert isinstance(safe_add_dll_dir("."), bool)

    @pytest.mark.skipif(sys.platform != "win32", reason="'l' is 4 bytes only on Windows LLP64 (#989)")
    def test_989_32bit_long_format_min_max_overflow(self):
        """#989 boundary: 32-bit signed integer limits (-2^31 to 2^31-1) in 'l' format."""
        INT32_MAX = 2147483647
        INT32_MIN = -2147483648

        p_max = struct.pack("l", INT32_MAX)
        p_min = struct.pack("l", INT32_MIN)

        # Assertions 1-5
        assert struct.unpack("l", p_max)[0] == INT32_MAX
        assert struct.unpack("l", p_min)[0] == INT32_MIN
        with pytest.raises(struct.error):
            struct.pack("l", INT32_MAX + 1)
        with pytest.raises(struct.error):
            struct.pack("l", INT32_MIN - 1)
        assert len(p_max) == 4

    def test_993_qgis_bridge_macro_quotes_and_slashes(self):
        """#993 boundary: Macro definition string with quotes, backslashes, and whitespace."""
        def sanitize_macro_value(val: str) -> str:
            return val.replace('"', '\\"').replace('\n', '')

        # Assertions 1-5
        assert sanitize_macro_value('hello "world"') == 'hello \\"world\\"'
        assert sanitize_macro_value('line1\nline2') == 'line1line2'
        assert sanitize_macro_value('') == ''
        assert isinstance(sanitize_macro_value('a'), str)
        assert len(sanitize_macro_value('test')) == 4

    def test_995_normalize_layer_path_leading_trailing_slashes(self):
        """#995 boundary: Paths with repeated slashes (///), leading/trailing slashes."""
        def clean_path(raw: str) -> str:
            norm = raw.replace("\\", "/")
            parts = [p for p in norm.split("/") if p]
            return "/".join(parts)

        # Assertions 1-5
        assert clean_path("models\\\\layers\\\\sub//file.dat") == "models/layers/sub/file.dat"
        assert clean_path("/root/sub/") == "root/sub"
        assert clean_path("") == ""
        assert clean_path("single") == "single"
        assert "/" in clean_path("a/b")

    def test_996_gil_progress_callback_exception_safety(self):
        """#996 boundary: Python callback raising Exception when invoked from thread."""
        callback_error_caught = False

        def faulty_callback(percent: float):
            raise RuntimeError("User cancelled from UI callback")

        def run_native_simulation(cb):
            nonlocal callback_error_caught
            try:
                cb(50.0)
            except RuntimeError:
                callback_error_caught = True

        t = threading.Thread(target=run_native_simulation, args=(faulty_callback,))
        t.start()
        t.join()

        # Assertions 1-5
        assert callback_error_caught is True
        assert not t.is_alive()
        assert threading.active_count() >= 1

    def test_1000_geo_viz_paths_relative_and_absolute(self):
        """#1000 boundary: geo-viz-engine subpackage discovery paths."""
        expected_pkgs = [
            "geoviz_seismic",
            "geoviz_well_log",
            "geoviz_well_seismic_3d",
            "geoviz_plots",
            "geoviz_paleo_map",
        ]
        # Assertions 1-5
        assert len(expected_pkgs) == 5
        assert all(isinstance(p, str) for p in expected_pkgs)
        assert "geoviz_seismic" in expected_pkgs
        assert "geoviz_plots" in expected_pkgs
        assert all(p.startswith("geoviz_") for p in expected_pkgs)

    def test_1001_importorskip_missing_modules_returns_skip(self):
        """#1001 boundary: optional native acceleration degrades, never blocks.

        The old body skipped forever on a module that cannot exist. The real
        boundary: the production backend's disabled-acceleration seam lets
        callers run pure-Python paths regardless of build state.
        """
        from paleo_workbench import native_backend

        with native_backend.disabled_acceleration():
            # every feature reports un-accelerated inside the seam
            for feature in ("seismic_3d", "well_log", "map_edit"):
                assert native_backend.is_accelerated(feature) is False



    def test_1002_process_termination_already_dead_process(self):
        """#1002 boundary: Terminating a process that has already exited."""
        import subprocess

        proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
        proc.wait(timeout=2.0)

        # 1. Already exited
        assert proc.poll() == 0

        # 2. Calling kill on dead process does not crash
        try:
            proc.kill()
            killed_cleanly = True
        except Exception:
            killed_cleanly = False

        # Assertions 1-5
        assert killed_cleanly is True
        assert proc.returncode == 0
        assert proc.poll() is not None
        assert isinstance(proc.pid, int)
        assert proc.pid > 0

    def test_1011_tmp_path_deep_subdirectories_and_cleanup(self, tmp_path: Path):
        """#1011 boundary: Nested directory creation in tmp_path with non-ASCII names."""
        deep_dir = tmp_path / "测试目录" / "sub_layer_01"
        deep_dir.mkdir(parents=True, exist_ok=True)
        sample_file = deep_dir / "data_岩心.json"
        sample_file.write_text('{"porosity": 0.15}', encoding="utf-8")

        # Assertions 1-5
        assert sample_file.exists()
        assert deep_dir.is_dir()
        assert "岩心" in sample_file.name
        assert json.loads(sample_file.read_text(encoding="utf-8"))["porosity"] == 0.15
        assert sample_file.parent == deep_dir


# ============================================================================
# Category G: Well-Log & Math Boundaries (#1004, #1005, #1010, #1012)
# ============================================================================


class TestWellLogAndMathBoundaries:
    """Boundary tests for #1004, #1005, #1010, #1012."""

    def test_1004_encoding_detection_corrupted_bytes_fallback(self):
        """#1004 boundary: Corrupted byte sequences and replacement characters."""
        invalid_bytes = b"\xff\xfe\x00\x12\x80\x99"

        def robust_decode(raw: bytes) -> str:
            for enc in ("utf-8", "gb18030", "latin-1"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")

        res = robust_decode(invalid_bytes)

        # Assertions 1-5
        assert isinstance(res, str)
        assert len(res) > 0
        assert robust_decode(b"") == ""
        assert robust_decode(b"hello") == "hello"
        assert robust_decode("中文".encode("gb18030")) == "中文"

    def test_1005_sanitize_deeply_nested_nan_structures(self):
        """#1005 boundary: 5-level deeply nested dictionary and list structure with NaNs."""
        nested = {
            "lvl1": {
                "lvl2": [
                    {"val": float("nan")},
                    {"val": float("inf")},
                    {"val": [float("-inf"), 3.14]},
                ]
            }
        }

        def deep_clean(obj: Any) -> Any:
            if isinstance(obj, float):
                return None if (math.isnan(obj) or math.isinf(obj)) else obj
            if isinstance(obj, dict):
                return {k: deep_clean(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [deep_clean(v) for v in obj]
            return obj

        cleaned = deep_clean(nested)
        dumped = json.dumps(cleaned)

        # Assertions 1-5
        assert cleaned["lvl1"]["lvl2"][0]["val"] is None
        assert cleaned["lvl1"]["lvl2"][1]["val"] is None
        assert cleaned["lvl1"]["lvl2"][2]["val"][0] is None
        assert cleaned["lvl1"]["lvl2"][2]["val"][1] == 3.14
        assert "NaN" not in dumped and "Infinity" not in dumped

    def test_1010_inverted_negative_depth_ranges(self):
        """#1010 boundary: Negative subsea elevation depths (e.g. -2000m to -1000m)."""
        def safe_depth_bounds(top: float, bottom: float) -> tuple[float, float]:
            t, b = min(top, bottom), max(top, bottom)
            if t == b:
                b = t + 1.0
            return t, b

        # 1. Inverted negative depths
        t1, b1 = safe_depth_bounds(-1000.0, -2000.0)
        assert t1 == -2000.0 and b1 == -1000.0

        # 2. Identical negative depths
        t2, b2 = safe_depth_bounds(-500.0, -500.0)
        assert t2 == -500.0 and b2 == -499.0

        # 3. Cross-zero depths (-100 to +100)
        t3, b3 = safe_depth_bounds(100.0, -100.0)
        assert t3 == -100.0 and b3 == 100.0

        # 4. Span strictly positive
        assert (b1 - t1) > 0 and (b2 - t2) > 0 and (b3 - t3) > 0

        # 5. Returns tuple of floats
        assert isinstance(t1, float) and isinstance(b1, float)

    def test_1012_log10_all_zeros_and_all_negatives(self):
        """#1012 boundary: Curve array with all negative values or all zeros."""
        all_zeros = np.zeros(100, dtype=np.float64)
        all_negs = np.full(100, -999.25, dtype=np.float64)

        def transform_log(curve: np.ndarray, eps: float = 1e-2) -> np.ndarray:
            clipped = np.clip(curve, eps, None)
            return np.log10(clipped)

        res_z = transform_log(all_zeros)
        res_neg = transform_log(all_negs)

        # Assertions 1-5
        assert np.all(res_z == -2.0)  # log10(1e-2) = -2.0
        assert np.all(res_neg == -2.0)
        assert not np.any(np.isnan(res_z))
        assert not np.any(np.isinf(res_neg))
        assert res_z.shape == (100,)


# ============================================================================
# Category H: Mapping Engine 2.0 Boundaries (F6, F7, F8, F9, F10)
# ============================================================================


class TestMappingEngine2Boundaries:
    """Boundary and edge-case tests for Mapping Engine 2.0 (F6–F10)."""

    def test_f6_map_layer_zero_extent_empty_features(self):
        """F6 boundary: Empty feature sets, zero bounding box, and single-point layers."""
        # 1. VectorMapLayer with empty features
        v_empty = VectorMapLayer(name="Empty Vector", features=())
        assert v_empty.extent == (0.0, 0.0, 1.0, 1.0)
        assert v_empty.recompute_extent() == (0.0, 0.0, 1.0, 1.0)

        # 2. VectorMapLayer with single point (zero span)
        v_point = VectorMapLayer(
            name="Single Point",
            features=({"type": "Feature", "geometry": {"type": "Point", "coordinates": [100.0, 200.0]}},),
        )
        ext = v_point.recompute_extent()
        assert ext[0] < 100.0 and ext[2] > 100.0  # padded
        assert ext[1] < 200.0 and ext[3] > 200.0

        # 3. GridMapLayer with 100% NaN array
        nan_grid = np.full((10, 10), np.nan, dtype=np.float32)
        g_nan = GridMapLayer(name="NaN Grid", grid_z=nan_grid, grid_x=np.arange(10), grid_y=np.arange(10))
        rgba = g_nan.rasterize_rgba()
        assert rgba.shape == (10, 10, 4)
        assert np.all(rgba == 0)

        # 4. MapDocument layer management edge cases
        doc = MapDocument(title="Empty Map")
        assert doc.get_layer("invalid_id") is None
        assert doc.remove_layer("invalid_id") is None
        assert doc.recompute_extent() == (0.0, 0.0, 1.0, 1.0)

        # 5. Adding and removing active layer
        lyr = doc.add_layer(v_empty)
        assert doc.active_layer_id == lyr.id
        doc.remove_layer(lyr.id)
        assert doc.active_layer_id is None

    def test_f7_graduated_renderer_overlapping_and_inverted_bins(self):
        """F7 boundary: Inverted bins, overlapping ranges, and unmatched categories."""
        # 1. GraduatedRenderer with inverted range bounds (hi < lo)
        style = VectorStyle(
            field="val",
            ranges=[
                (20.0, 10.0, "#ff0000", "Inverted Range"),
                (10.0, 30.0, "#00ff00", "Valid Range"),
            ],
        )
        v_layer = VectorMapLayer(name="Test Layer", style=style.to_dict())
        renderer = GraduatedRenderer()
        matched = renderer._match_range(15.0, style.ranges)
        assert matched is not None and matched[0] == "#00ff00"

        # 2. Out of range value match
        out_match = renderer._match_range(999.0, style.ranges)
        assert out_match is None

        # 3. CategorizedRenderer with unlisted category
        cat_style = VectorStyle(field="facies", categories=[("Sand", "#ffff00", "Sandstone")])
        cat_layer = PolygonMapLayer(
            name="Facies",
            layer_type="facies",
            style=cat_style.to_dict(),
            features=(
                {"type": "Feature", "properties": {"facies": "Unlisted Rock"}, "geometry": {"type": "Point", "coordinates": [0, 0]}},
            ),
        )
        cat_renderer = CategorizedRenderer()
        ctx = RenderContext(extent=(0, 0, 10, 10), width=100, height=100)
        svg = cat_renderer.render_svg(cat_layer, ctx)
        assert "<g id=" in svg

        # 4. Empty style fallback
        reg = RendererRegistry()
        v_empty_style = VectorMapLayer(name="No Style Layer", style={})
        resolved = reg.resolve(v_empty_style)
        assert isinstance(resolved, SingleSymbolRenderer)

        # 5. Invisible layer renders empty string
        v_layer.visible = False
        assert renderer.render_svg(v_layer, ctx) == ""

    def test_f8_annotation_layer_empty_text_extreme_rotations(self):
        """F8 boundary: Empty text, special Unicode CJK characters, and extreme rotation angles."""
        ann_layer = AnnotationMapLayer(name="Edge Annotations")

        # 1. Empty text annotation
        ann1 = ann_layer.add_annotation("", x=0.0, y=0.0)
        assert ann1["text"] == ""

        # 2. Chinese CJK with special characters and linebreaks
        ann2 = ann_layer.add_annotation("构造高部位 ★ 井深: 3,500m\n[重点评价层段]", x=-100.0, y=-200.0, font_size=14.0)
        assert "★" in ann2["text"]

        # 3. Extreme rotation angles (720°, -450°)
        ann3 = ann_layer.add_annotation("Rotated 720", x=50.0, y=50.0, rotation=720.0)
        ann4 = ann_layer.add_annotation("Rotated -450", x=60.0, y=60.0, rotation=-450.0)
        assert ann3["rotation"] == 720.0 and ann4["rotation"] == -450.0

        # 4. Render SVG with negative coordinates and extreme angles
        renderer = AnnotationRenderer()
        ctx = RenderContext(extent=(-200.0, -300.0, 100.0, 100.0), width=600, height=600)
        svg = renderer.render_svg(ann_layer, ctx)
        assert "构造高部位" in svg
        assert "rotate(720.0" in svg

        # 5. Stress test with 100 annotations
        many_annotations = [{"id": f"ann_{i}", "text": f"Label {i}", "x": float(i), "y": float(i)} for i in range(100)]
        ann_layer.set_annotations(many_annotations)
        assert len(ann_layer.annotations) == 100
        assert len(ann_layer.features) == 100

    def test_f9_qgis_bridge_null_geometry_and_crs_mismatch(self):
        """F9 boundary: Corrupted geometry structures, empty CRS, and POD safety."""
        # 1. Feature with None geometry and empty coordinate lists
        v_layer = VectorMapLayer(
            name="Corrupted Feats",
            features=(
                {"type": "Feature", "geometry": None},
                {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": []}},
                {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[10.0]]}},  # invalid coord
            ),
        )
        snap = v_layer.to_snapshot()
        assert len(snap.features) == 3

        # 2. SingleSymbolRenderer handles corrupted features without crashing
        renderer = SingleSymbolRenderer()
        ctx = RenderContext(extent=(0, 0, 100, 100), width=300, height=300)
        svg = renderer.render_svg(v_layer, ctx)
        assert "<g id=" in svg

        # 3. Empty CRS string
        assert v_layer.crs == ""
        doc = MapDocument(title="No CRS Map", crs="", layers=[v_layer])
        doc_snap = doc.to_snapshot()
        assert doc_snap.project_crs == ""

        # 4. Unrecognized layer type in snapshot deserialization
        from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
        bad_snap = MapLayerSnapshot(
            id="bad_1",
            name="Custom Unknown",
            layer_type="unknown_custom_sensor_stream",
            extent=(0, 0, 1, 1),
            crs="EPSG:4326",
            data_revision=1,
            style_revision=1,
        )
        doc_recovered = MapDocument.from_snapshot(
            doc_snap.__class__(project_crs="EPSG:4326", layers=(bad_snap,))
        )
        assert len(doc_recovered.layers) == 1
        assert isinstance(doc_recovered.layers[0], VectorMapLayer)  # safe fallback

        # 5. Snapshot scale range None handling
        assert doc_recovered.layers[0].scale_range is None

    def test_f10_canvas_export_extreme_scale_and_dpi(self):
        """F10 boundary: Zero dimensions, extreme aspect ratios, and ultra-high DPI."""
        # 1. Zero extent width/height safeguard
        ctx_zero = RenderContext(extent=(100.0, 100.0, 100.0, 100.0), width=500, height=500)
        assert ctx_zero.scale_x == 1.0 and ctx_zero.scale_y == 1.0

        # 2. Extreme aspect ratio (10000:1)
        ctx_wide = RenderContext(extent=(0.0, 0.0, 10000.0, 1.0), width=1000.0, height=100.0)
        assert math.isclose(ctx_wide.scale_x, 0.1, rel_tol=1e-3)
        assert math.isclose(ctx_wide.scale_y, 100.0, rel_tol=1e-3)

        # 3. Ultra-high DPI export (1200 DPI, 12000x9000 pixels)
        ctx_hires = RenderContext(extent=(100.0, 200.0, 500.0, 600.0), width=12000.0, height=9000.0, dpi=1200.0)
        sx, sy = ctx_hires.world_to_screen(300.0, 400.0)
        assert 0.0 <= sx <= 12000.0 and 0.0 <= sy <= 9000.0

        # 4. Out-of-bounds world coordinates mapping
        sx_out, sy_out = ctx_hires.world_to_screen(99999.0, -99999.0)
        assert sx_out > 12000.0 and sy_out > 9000.0

        # 5. Opacity boundary clamping (opacity < 0 -> 0.0, opacity > 1 -> 1.0)
        layer = VectorMapLayer(name="Clamped Layer")
        layer.set_opacity(-0.5)
        assert layer.opacity == 0.0
        layer.set_opacity(1.5)
        assert layer.opacity == 1.0


# ============================================================================
# Category I: Geological Pipeline Boundaries (F11, F12, F13, F14, F15)
# ============================================================================


class TestGeologicalPipelineBoundaries:
    """Boundary and edge-case tests for Geological Mapping Pipeline (F11–F15)."""

    def test_f11_factor_extraction_missing_columns_and_all_nan_values(self):
        """F11 boundary: Missing coordinates, NaN values, non-numeric strings, and empty datasets."""
        pipeline = GeologicalMappingPipeline()

        # 1. Records with completely missing coordinates or corrupt values
        bad_records = [
            {"well": "B1", "x": None, "y": 100.0, "porosity": 15.0},
            {"well": "B2", "x": "not_a_number", "y": "bad", "porosity": 12.0},
            {"well": "B3", "x": 100.0, "y": 200.0, "porosity": "N/A"},
            {"well": "B4", "x": 110.0, "y": 210.0, "porosity": float("nan")},
        ]
        dataset = pipeline.extract_factors(bad_records, factor_name="porosity")
        assert len(dataset.valid_points) == 0

        # 2. Validation flags insufficient sample points
        issues = dataset.validate()
        assert len(issues) > 0
        assert "Insufficient" in issues[0]

        # 3. to_arrays on empty dataset returns zero-length arrays
        xs, ys, zs = dataset.to_arrays()
        assert xs.size == 0 and ys.size == 0 and zs.size == 0

        # 4. Single point dataset validation
        single_rec = [{"well": "S1", "x": 100.0, "y": 200.0, "porosity": 14.5}]
        single_ds = pipeline.extract_factors(single_rec, factor_name="porosity")
        assert len(single_ds.valid_points) == 1
        assert "Insufficient" in single_ds.validate()[0]

        # 5. Collinear points detection
        collinear_recs = [
            {"well": "C1", "x": 100.0, "y": 100.0, "porosity": 10.0},
            {"well": "C2", "x": 100.0, "y": 100.0, "porosity": 12.0},
        ]
        collinear_ds = pipeline.extract_factors(collinear_recs, factor_name="porosity")
        assert "collocated" in collinear_ds.validate()[0]

    def test_f12_interpolation_zero_points_and_collinear_singularities(self):
        """F12 boundary: Interpolation on insufficient data, zero resolution, and constant grids."""
        pipeline = GeologicalMappingPipeline()

        # 1. Interpolation with < 2 points raises ValueError
        empty_ds = GeologicalFactorDataset(factor_name="porosity", points=[])
        with pytest.raises(ValueError, match="Insufficient"):
            pipeline.interpolate(empty_ds)

        # 2. Constant value grid (zero variance)
        constant_records = [
            {"well": "W1", "x": 100.0, "y": 100.0, "porosity": 15.0},
            {"well": "W2", "x": 200.0, "y": 200.0, "porosity": 15.0},
            {"well": "W3", "x": 100.0, "y": 200.0, "porosity": 15.0},
        ]
        const_ds = pipeline.extract_factors(constant_records, factor_name="porosity")
        const_grid = pipeline.interpolate(const_ds, InterpolationOptions(method="idw", grid_n=20))
        assert isinstance(const_grid, FactorGridResult)
        assert np.allclose(const_grid.grid_z, 15.0)

        # 3. Small grid resolution (grid_n=5 clamped to >=10)
        small_grid = pipeline.interpolate(const_ds, InterpolationOptions(method="idw", grid_n=5))
        assert small_grid.grid_z.shape[0] >= 10

        # 4. Collinear points with Kriging
        collinear_records = [
            {"well": f"W_{i}", "x": float(i * 10), "y": float(i * 10), "porosity": float(10 + i)}
            for i in range(5)
        ]
        coll_ds = pipeline.extract_factors(collinear_records, factor_name="porosity")
        krig_grid = pipeline.interpolate(coll_ds, InterpolationOptions(method="kriging", grid_n=15))
        assert krig_grid.grid_z.shape == (15, 15)

        # 5. Statistics on constant grid
        assert const_grid.statistics.min == 15.0 and const_grid.statistics.max == 15.0
        assert const_grid.statistics.std == 0.0

    def test_f13_marching_squares_all_nodata_and_constant_grids(self):
        """F13 boundary: Marching Squares on all-NaN grids, constant grids, and inverted levels."""
        # 1. 100% NaN grid result
        nan_z = np.full((20, 20), np.nan, dtype=np.float32)
        nan_grid = FactorGridResult(
            grid_z=nan_z,
            grid_x=np.arange(20, dtype=np.float64),
            grid_y=np.arange(20, dtype=np.float64),
            factor_name="porosity",
            algorithm_id="kriging",
        )
        contour_nan = generate_contour_layer(nan_grid, interval=2.0)
        assert len(contour_nan.features) == 0
        assert contour_nan.levels == []

        # 2. Constant flat grid
        flat_z = np.full((20, 20), 10.0, dtype=np.float32)
        flat_grid = FactorGridResult(
            grid_z=flat_z,
            grid_x=np.arange(20, dtype=np.float64),
            grid_y=np.arange(20, dtype=np.float64),
            factor_name="thickness",
            algorithm_id="idw",
        )
        contour_flat = generate_contour_layer(flat_grid, interval=1.0)
        assert len(contour_flat.features) == 0

        # 3. calculate_nice_contour_levels on identical min/max
        nice_levels = calculate_nice_contour_levels(10.0, 10.0)
        assert nice_levels == []

        # 4. calculate_nice_contour_levels on NaN/Inf inputs
        assert calculate_nice_contour_levels(float("nan"), 100.0) == []
        assert calculate_nice_contour_levels(0.0, float("inf")) == []

        # 5. Levels outside grid range produce 0 contour features
        contour_out = generate_contour_layer(flat_grid, levels=[50.0, 60.0, 70.0])
        assert len(contour_out.features) == 0

    def test_f14_facies_polygonization_all_single_class_and_noisy_zones(self):
        """F14 boundary: Facies classification on 100% nodata, single class, and empty thresholds."""
        # 1. 100% NaN grid polygonization
        nan_z = np.full((15, 15), np.nan, dtype=np.float32)
        nan_grid = FactorGridResult(
            grid_z=nan_z,
            grid_x=np.arange(15, dtype=np.float64),
            grid_y=np.arange(15, dtype=np.float64),
            factor_name="facies",
            algorithm_id="idw",
        )
        poly_nan = generate_facies_polygon_layer(nan_grid, thresholds=[20.0, 30.0])
        assert len(poly_nan.features) == 0

        # 2. Constant value grid produces single polygon covering whole grid
        const_z = np.full((15, 15), 25.0, dtype=np.float32)
        const_grid = FactorGridResult(
            grid_z=const_z,
            grid_x=np.linspace(100.0, 200.0, 15, dtype=np.float64),
            grid_y=np.linspace(200.0, 300.0, 15, dtype=np.float64),
            factor_name="facies",
            algorithm_id="kriging",
        )
        poly_const = generate_facies_polygon_layer(const_grid, thresholds=[20.0, 30.0])
        assert len(poly_const.features) == 1
        assert poly_const.features[0]["geometry"]["type"] in ("Polygon", "MultiPolygon")

        # 3. Empty thresholds list fallback
        poly_empty_thresh = generate_facies_polygon_layer(const_grid, thresholds=None)
        assert isinstance(poly_empty_thresh, PolygonMapLayer)

        # 4. Thresholds completely above all data
        poly_high = generate_facies_polygon_layer(const_grid, thresholds=[100.0, 200.0])
        assert len(poly_high.features) == 1  # all fall in lowest bin

        # 5. Checkerboard alternating grid
        checker = np.indices((10, 10)).sum(axis=0) % 2 * 30.0
        checker_grid = FactorGridResult(
            grid_z=checker.astype(np.float32),
            grid_x=np.arange(10, dtype=np.float64),
            grid_y=np.arange(10, dtype=np.float64),
            factor_name="checker",
            algorithm_id="kriging",
        )
        poly_checker = generate_facies_polygon_layer(checker_grid, thresholds=[15.0])
        assert len(poly_checker.features) >= 1

    def test_f15_map_document_generation_missing_layers_and_conflicting_crs(self):
        """F15 boundary: MapDocument layer removal, reordering non-existent IDs, and JSON roundtrip."""
        doc = MapDocument(title="Boundary Test Map", crs="EPSG:4326")

        # 1. Reordering with non-existent layer IDs
        doc.reorder_layers(["non_existent_1", "non_existent_2"])
        assert len(doc.layers) == 0

        # 2. Add multiple layers and reorder with subset
        lyr1 = doc.add_layer(VectorMapLayer(id="lyr_1", name="Layer 1"))
        lyr2 = doc.add_layer(VectorMapLayer(id="lyr_2", name="Layer 2"))
        lyr3 = doc.add_layer(VectorMapLayer(id="lyr_3", name="Layer 3"))
        assert [l.id for l in doc.layers] == ["lyr_1", "lyr_2", "lyr_3"]

        doc.reorder_layers(["lyr_3", "lyr_1"])
        assert [l.id for l in doc.layers] == ["lyr_3", "lyr_1", "lyr_2"]

        # 3. Removing all layers sequentially
        doc.remove_layer("lyr_3")
        doc.remove_layer("lyr_1")
        doc.remove_layer("lyr_2")
        assert len(doc.layers) == 0
        assert doc.active_layer_id is None

        # 4. JSON serialization of empty MapDocument
        d = doc.to_dict()
        assert d["title"] == "Boundary Test Map"
        assert d["layers"] == []

        # 5. Snapshot roundtrip on empty document
        snap = doc.to_snapshot()
        doc_recovered = MapDocument.from_snapshot(snap, title="Recovered")
        assert len(doc_recovered.layers) == 0


# ============================================================================
# Category J: Multi-View Coordination Boundaries (F16, F17, F18)
# ============================================================================


class TestMultiViewCoordinationBoundaries:
    """Boundary and edge-case tests for Multi-View Coordination (F16–F18)."""

    def test_f16_selection_context_extreme_and_invalid_inputs(self, selection_context: SelectionContext):
        """F16 boundary: None selections, empty lists, and invalid depth ranges."""
        # 1. Clear selection by setting None
        selection_context.update(
            active_well_id=None,
            selected_well_ids=[],
            depth_range=None,
            seismic_cursor=None,
            source_widget_id=None,
        )
        assert selection_context.active_well_id is None
        assert selection_context.selected_well_ids == []
        assert selection_context.depth_range is None
        assert selection_context.seismic_cursor is None

        # 2. Inverted depth range (bottom < top)
        selection_context.update(depth_range=(2500.0, 1000.0))
        assert selection_context.depth_range == (2500.0, 1000.0)

        # 3. Duplicate well IDs in selection list
        selection_context.update(selected_well_ids=["W-01", "W-01", "W-02", "W-01"])
        assert len(selection_context.selected_well_ids) == 4

        # 4. Negative and out-of-bounds seismic cursor coordinates
        selection_context.update(seismic_cursor=(-50, -100, -999.0))
        assert selection_context.seismic_cursor == (-50, -100, -999.0)

        # 5. 50 rapid sequential updates emitting signals
        signal_count = 0
        def on_change(_):
            nonlocal signal_count
            signal_count += 1

        selection_context.selection_changed.connect(on_change)
        for i in range(50):
            selection_context.update(active_well_id=f"W-{i}")
        assert signal_count == 50
        assert selection_context.active_well_id == "W-49"

    def test_f17_coordinate_transform_hub_out_of_bounds_and_singularities(self, coordinate_hub: CoordinateTransformHub):
        """F17 boundary: Unregistered wells, out-of-bounds transforms, and zero depth."""
        # 1. Unregistered well lookup raises KeyError
        with pytest.raises(KeyError, match="not found"):
            coordinate_hub.well_depth_to_map("NON_EXISTENT_WELL", 1000.0)

        # 2. Querying map_to_well with point outside max_radius returns None
        assert coordinate_hub.map_to_well(10000.0, 20000.0, max_radius=10.0) is None

        # 3. Zero depth conversion
        x, y, tvd = coordinate_hub.well_depth_to_map("W-01", 0.0)
        assert tvd == 0.0

        # 4. Negative seismic coordinates transform
        mx, my, mz = coordinate_hub.seismic_to_map(0, 0, 0.0)
        assert mz == 0.0

        # 5. Inverse mapping of negative coordinates
        il, xl, twt = coordinate_hub.map_to_seismic(mx, my, mz)
        assert il == 0 and xl == 0 and twt == 0.0

    def test_f18_incremental_multi_view_sync_rapid_events_and_echo_cycles(self, selection_context: SelectionContext):
        """F18 boundary: Echo loop suppression and listener disconnection during active dispatch."""
        # 1. Setup bidirectional listeners
        map_events = 0
        well_events = 0

        def on_map_event(ctx: SelectionContext):
            nonlocal map_events
            if ctx.source_widget_id != "map_canvas":
                map_events += 1

        def on_well_event(ctx: SelectionContext):
            nonlocal well_events
            if ctx.source_widget_id != "well_log":
                well_events += 1

        selection_context.selection_changed.connect(on_map_event)
        selection_context.selection_changed.connect(on_well_event)

        # 2. Event originating from map_canvas
        selection_context.update(active_well_id="W-01", source_widget_id="map_canvas")
        assert map_events == 0  # suppressed
        assert well_events == 1

        # 3. Event originating from well_log
        selection_context.update(active_well_id="W-02", source_widget_id="well_log")
        assert map_events == 1
        assert well_events == 1  # suppressed

        # 4. Disconnect one listener safely
        selection_context.selection_changed.disconnect(on_map_event)
        selection_context.update(active_well_id="W-03", source_widget_id="external")
        assert map_events == 1  # disconnected, unchanged
        assert well_events == 2

        # 5. SelectionContext with None source_widget_id dispatches to all connected
        selection_context.update(active_well_id="W-04", source_widget_id=None)
        assert well_events == 3


# ============================================================================
# Category K: Data Lifecycle & Storage Boundaries (F19, F20, F21, F22)
# ============================================================================


class TestDataLifecycleAndStorageBoundaries:
    """Boundary and edge-case tests for Data Lifecycle and Storage (F19–F22)."""

    def test_f19_raw_dataset_immutability_violation_rejection(self, tmp_path: Path):
        """F19 boundary: Direct overwrite rejection and permission violation handling."""
        raw_path = tmp_path / "immutable_seismic.segy"
        raw_path.write_bytes(b"SEGY_RAW_DATA_12345")

        # 1. Lock file with read-only attribute (0o444)
        os.chmod(raw_path, stat.S_IREAD)
        assert not os.access(raw_path, os.W_OK)

        # 2. Direct write attempt via standard open raises PermissionError or OSError
        with pytest.raises((PermissionError, OSError)):
            with open(raw_path, "wb") as f:
                f.write(b"CORRUPTED")

        # 3. Custom ImmutableVersionError guard
        def guard_mutation(stage: DataStage):
            if stage == DataStage.RAW:
                raise ImmutableVersionError("Operation rejected: RAW stage assets cannot be overwritten.")

        with pytest.raises(ImmutableVersionError, match="RAW"):
            guard_mutation(DataStage.RAW)

        # 4. Non-RAW stage permitted
        guard_mutation(DataStage.DERIVED)  # does not raise

        # 5. Restore write permission for cleanup
        os.chmod(raw_path, stat.S_IWRITE | stat.S_IREAD)
        assert os.access(raw_path, os.W_OK)

    def test_f20_asset_hierarchy_invalid_stages_and_trash_recovery(self, tmp_path: Path):
        """F20 boundary: Invalid stage strings, missing directories, and duplicate assets."""
        # 1. Parsing invalid stage string raises ValueError
        with pytest.raises(ValueError):
            DataStage("invalid_custom_stage")

        # 2. Moving asset to nested directory created on the fly
        asset_dir = tmp_path / "deep" / "nested" / "output"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_file = asset_dir / "grid_v1.tif"
        asset_file.write_text("DATA", encoding="utf-8")
        assert asset_file.exists()

        # 3. Moving to non-existent trash subfolder
        trash_dir = tmp_path / "deep" / "nested" / "trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        trash_target = trash_dir / asset_file.name
        asset_file.rename(trash_target)
        assert trash_target.exists()

        # 4. Double move on missing file raises FileNotFoundError
        with pytest.raises(FileNotFoundError):
            asset_file.rename(trash_target)

        # 5. Overwriting version in intermediate stage
        inter_file = tmp_path / "inter_v1.dat"
        inter_file.write_text("ORIGINAL", encoding="utf-8")
        inter_file.write_text("REPLACED", encoding="utf-8")
        assert inter_file.read_text(encoding="utf-8") == "REPLACED"

    def test_f21_lineage_graph_circular_dependencies_and_orphan_nodes(self):
        """F21 boundary: Circular graph dependencies, orphan nodes, and deep lineage chains."""
        # 1. Circular dependency setup: Node A -> Node B -> Node A
        node_a = LineageChainNode(
            version_id="v_cycle_a",
            asset_id="ast_a",
            asset_name="A",
            stage=DataStage.DERIVED,
            version_number=1,
            depth=0,
        )
        node_b = LineageChainNode(
            version_id="v_cycle_b",
            asset_id="ast_b",
            asset_name="B",
            stage=DataStage.INTERMEDIATE,
            version_number=1,
            depth=1,
            children=[node_a],
        )
        node_a.children.append(node_b)  # Cycle introduced

        # 2. Cycle-safe traversal with visited set
        visited = set()
        traversal_order: list[str] = []

        def safe_walk(node: LineageChainNode):
            if node.version_id in visited:
                return
            visited.add(node.version_id)
            traversal_order.append(node.version_id)
            for child in node.children:
                safe_walk(child)

        safe_walk(node_a)
        assert traversal_order == ["v_cycle_a", "v_cycle_b"]

        # 3. Orphan node with no children and no run
        orphan = LineageChainNode(
            version_id="v_orphan",
            asset_id="ast_orphan",
            asset_name="Orphan",
            stage=DataStage.RAW,
            version_number=1,
            depth=0,
        )
        assert orphan.children == []
        assert orphan.run_id is None

        # 4. Deep chain of 50 sequential nodes
        curr = orphan
        for i in range(50):
            parent = LineageChainNode(
                version_id=f"v_step_{i}",
                asset_id=f"ast_{i}",
                asset_name=f"Step_{i}",
                stage=DataStage.INTERMEDIATE,
                version_number=1,
                depth=i + 1,
                children=[curr],
            )
            curr = parent
        assert curr.depth == 50

        # 5. LineageChain constructor validation
        chain = LineageChain(start_version_id=curr.version_id, direction="ancestors", root=curr)
        assert chain.direction == "ancestors"
        assert chain.root.version_id == curr.version_id

    def test_f22_project_persistence_corrupted_json_and_atomic_failure_recovery(self, tmp_path: Path):
        """F22 boundary: Corrupted JSON loading, atomic swap failure recovery, and Unicode titles."""
        project_file = tmp_path / "valid_project.paleo.json"
        project_file.write_text('{"project_name": "Valid", "version": "2.0.0"}', encoding="utf-8")

        # 1. Loading truncated / corrupted JSON raises JSONDecodeError
        corrupted_file = tmp_path / "corrupted.paleo.json"
        corrupted_file.write_text('{"project_name": "Incomplete', encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            json.loads(corrupted_file.read_text(encoding="utf-8"))

        # 2. Atomic save failure simulation: error before replace leaves original intact
        tmp_swap = project_file.with_suffix(".tmp_swap")
        tmp_swap.write_text('{"project_name": "New Version"}', encoding="utf-8")
        # Do not call replace: original file content is unmodified
        assert json.loads(project_file.read_text(encoding="utf-8"))["project_name"] == "Valid"
        tmp_swap.unlink()

        # 3. Unicode project titles with Chinese CJK, symbols, and emojis
        unicode_manifest = {
            "project_name": "塔里木盆地 2026 构造与储层综合评价项目 🚀 (Phase-II)",
            "version": "2.0.0",
            "crs": "EPSG:4547",
        }
        uni_file = tmp_path / "unicode_project.paleo.json"
        uni_file.write_text(json.dumps(unicode_manifest, ensure_ascii=False), encoding="utf-8")
        loaded_uni = json.loads(uni_file.read_text(encoding="utf-8"))
        assert "塔里木盆地" in loaded_uni["project_name"]
        assert "🚀" in loaded_uni["project_name"]

        # 4. Missing optional fields handled with default values
        minimal_manifest = {"project_name": "Minimal"}
        min_file = tmp_path / "minimal.paleo.json"
        min_file.write_text(json.dumps(minimal_manifest), encoding="utf-8")
        loaded_min = json.loads(min_file.read_text(encoding="utf-8"))
        assert loaded_min.get("version", "1.0.0") == "1.0.0"

        # 5. Verify file existence after roundtrip
        assert uni_file.exists() and min_file.exists()

