# tests/test_datapage_stress.py
from __future__ import annotations

import os

# TEMP DEBUG (#917 follow-up): stage timings for update_state on CI
os.environ.setdefault("DATAPAGE_UPDATE_DEBUG", "1")

from PySide6.QtWidgets import QApplication

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.resources.import_service import import_folder
from paleo_workbench.resources.scanner import scan_resources
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.filter_index import FilterIndex
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController
from tests.perf.fixtures import make_mock_resources, make_tmp_tree, stress_n
from tests.perf.timing import print_stress, timed

# Ratio gates (mirroring tests/test_catalog_scale.py): timings are compared
# between a small and a large workload so the assertion is scale-relative, not
# a brittle absolute-millisecond bound. +FLOOR absorbs fixed overhead and
# machine noise (issue #851: these tests used to be print-only).
SCALE_CEILING = 5.0
FLOOR_MS = 25.0


class InstantProvider(PreviewProvider):
    def preview(self, asset):
        if asset is None:
            return super().preview(asset)
        return PreviewResult(
            mode="message",
            title=asset.name,
            path=asset.path,
            message=f"ok:{asset.name}",
        )


def _wait_controller_idle(qtbot, controller: PreviewRequestController, timeout: int = 10_000) -> None:
    """Block until in-flight preview workers finish (avoids Qt teardown aborts)."""
    qtbot.waitUntil(
        lambda: (
            controller._active_job.thread is None
            and controller._pending is None
        ),
        timeout=timeout,
    )


def test_stress_s1_update_state(qtbot):
    n = stress_n(2000)
    page = DataPage(ProjectDocument.new("Stress"))
    qtbot.addWidget(page)

    # Small workload first: gates below compare the per-row scaling.
    small = make_mock_resources(max(64, n // 8))
    timing_small, _ = timed("S1_update_small", lambda: page.update_state({}, small))

    resources = make_mock_resources(n)
    timing, _ = timed("S1_update", lambda: page.update_state({}, resources))

    # Superlinearity gate, per-row form: at 8x rows an O(N²) refresh costs
    # 8x more per row; the ceiling allows 4x per-row headroom for runner
    # memory-pressure noise (the absolute total form was machine-bound and
    # flaked on slow CI even though the code is linear — measured locally
    # 125..4000 rows at a constant ~21 µs/row; see FsProbeCache for the CI
    # stat-pressure half of #917).
    def per_row_scaling_breach(t_small, t_big):
        per_row_big = t_big.ms / n
        per_row_small = t_small.ms / max(1, n // 8)
        ok = per_row_big < 4.0 * per_row_small + 0.02
        return ok, (
            f"S1_update per-row scaling: {per_row_big * 1000:.1f}µs/row at n={n} vs "
            f"{per_row_small * 1000:.1f}µs/row at n={n // 8}"
        )

    # Timing gates get ONE re-measure on breach: two samples taken seconds
    # apart on a loaded shared runner can disagree by more than the slack
    # even for linear code (#1023). The retry runs on a fresh page so cache
    # warm-up from attempt one cannot flatter attempt two.
    ok, detail = per_row_scaling_breach(timing_small, timing)
    if not ok:
        page = DataPage(ProjectDocument.new("Stress"))
        qtbot.addWidget(page)
        timing_small, _ = timed(
            "S1_update_small_retry", lambda: page.update_state({}, make_mock_resources(max(64, n // 8)))
        )
        timing, _ = timed("S1_update_retry", lambda: page.update_state({}, make_mock_resources(n)))
        ok, detail = per_row_scaling_breach(timing_small, timing)

    print_stress("S1_update", n=n, ms=timing.ms)

    # Prefer public-ish access: asset table model row count
    model = page.asset_table.model
    assert model is not None
    assert model.rowCount() == n
    assert ok, detail
    # Keep the absolute ceiling as a backstop against gross regressions
    # (5x the extrapolated linear cost + a generous floor).
    assert timing.ms < SCALE_CEILING * timing_small.ms * 8 + FLOOR_MS, (
        f"S1_update total: {timing.ms:.1f}ms at n={n} vs "
        f"{timing_small.ms:.1f}ms at n={n // 8}"
    )


def test_stress_s2_filter_index():
    n = stress_n(2000)
    small_n = max(64, n // 8)
    small = make_mock_resources(small_n)
    idx_small = FilterIndex()
    idx_small.rebuild(small)
    timing_all_small, rows_all_small = timed(
        "S2_filter_all_small", lambda: idx_small.filter("全部", "")
    )
    timing_q_small, rows_q_small = timed(
        "S2_filter_search_small", lambda: idx_small.filter("测井", "asset_0000")
    )

    resources = make_mock_resources(n)
    idx = FilterIndex()
    idx.rebuild(resources)

    # FilterIndex categories are Chinese catalog labels ("全部", "测井", …)
    timing_all, rows_all = timed("S2_filter_all", lambda: idx.filter("全部", ""))
    print_stress("S2_filter_all", n=n, ms=timing_all.ms)
    assert len(rows_all) == n
    assert len(rows_all_small) == small_n
    assert timing_all.ms < SCALE_CEILING * timing_all_small.ms + FLOOR_MS, (
        f"S2_filter_all scaling: {timing_all.ms:.1f}ms at n={n} vs "
        f"{timing_all_small.ms:.1f}ms at n={small_n}"
    )

    timing_q, rows_q = timed(
        "S2_filter_search",
        lambda: idx.filter("测井", "asset_0000"),
    )
    print_stress("S2_filter_search", n=n, ms=timing_q.ms)
    assert len(rows_q) >= 1
    assert len(rows_q_small) >= 1
    assert timing_q.ms < SCALE_CEILING * timing_q_small.ms + FLOOR_MS, (
        f"S2_filter_search scaling: {timing_q.ms:.1f}ms at n={n} vs "
        f"{timing_q_small.ms:.1f}ms at n={small_n}"
    )


def test_stress_s3_rapid_select(qtbot):
    n_sel = 30
    resources = make_mock_resources(max(n_sel, 50))
    controller = PreviewRequestController(provider=InstantProvider())

    last: list[str] = []
    controller.result_ready.connect(lambda r: last.append(getattr(r, "title", "") or ""))

    try:
        def run():
            for i in range(n_sel):
                controller.request(resources[i])
            # Process events so async jobs drain
            app = QApplication.instance()
            for _ in range(50):
                app.processEvents()

        timing, _ = timed("S3_rapid_select", run)
        print_stress("S3_rapid_select", n=n_sel, ms=timing.ms)

        _wait_controller_idle(qtbot, controller, timeout=10_000)
        assert last  # got at least one result
        # Latest-only: final title should be last requested when instant provider
        assert last[-1] == resources[n_sel - 1].name
    finally:
        controller.shutdown(wait_ms=5_000)


def test_stress_s4_import_folder(tmp_path):
    n = 300
    small_n = max(64, n // 4)
    small_root = make_tmp_tree(tmp_path / "small", n=small_n)
    timing_small, small_report = timed(
        "S4_import_folder_small", lambda: import_folder(small_root, existing=[])
    )
    root = make_tmp_tree(tmp_path, n=n)
    timing, report = timed("S4_import_folder", lambda: import_folder(root, existing=[]))
    print_stress("S4_import_folder", n=n, ms=timing.ms)
    assert report.added_count == n
    assert small_report.added_count == small_n
    # The import folder path is currently Θ(N²) in catalog.json bytes because
    # each file is saved individually (tracked by #849, not this batch). The
    # current reality is ~16x for 4x files; this gate is deliberately loose
    # (25x + floor) so it only trips on blows WORSE than today while still
    # failing if a future regression makes the path super-quadratic.
    assert timing.ms < 25.0 * timing_small.ms + FLOOR_MS, (
        f"S4_import_folder scaling: {timing.ms:.1f}ms at n={n} vs "
        f"{timing_small.ms:.1f}ms at n={small_n}"
    )


def test_stress_s5_scan_concurrent_large(tmp_path):
    """N=10000 tiny files: concurrent vs serial scan timing (env-gated).

    Skipped unless DATAPAGE_STRESS_S5=1 to avoid slowing the default loop.
    """
    n = int(os.getenv("DATAPAGE_STRESS_S5_N", "10000"))
    if os.getenv("DATAPAGE_STRESS_S5") != "1":
        print(f"[datapage-stress] S5 SKIPPED (set DATAPAGE_STRESS_S5=1 to enable, N={n})", flush=True)
        return

    for i in range(n):
        (tmp_path / f"f{i:05d}.dat").write_bytes(b"x")

    timing_serial, serial_results = timed(
        "S5_scan_serial", lambda: scan_resources(tmp_path, max_workers=1)
    )
    print_stress("S5_scan_serial", n=n, ms=timing_serial.ms)

    timing_concurrent, concurrent_results = timed(
        "S5_scan_concurrent", lambda: scan_resources(tmp_path)
    )
    print_stress("S5_scan_concurrent", n=n, ms=timing_concurrent.ms)

    # Correctness: both scans return all files in sorted order
    assert len(serial_results) == n
    assert len(concurrent_results) == n
    assert serial_results[0].name == concurrent_results[0].name
    assert serial_results[-1].name == concurrent_results[-1].name
    # Concurrent scan must not be slower than serial by a large factor
    # (generous ceiling; the scan is I/O-bound and parallel workers should win).
    assert timing_concurrent.ms < 3.0 * timing_serial.ms + FLOOR_MS, (
        f"S5 concurrent {timing_concurrent.ms:.1f}ms vs serial "
        f"{timing_serial.ms:.1f}ms at n={n}"
    )
