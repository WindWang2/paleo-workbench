"""Regression tests for #897 (misc batch).

Each case pins one fix from the batch: well-tie descending axis, DTW
unreachable band, sculpt radius guard, advisor plane normalization,
Unicode search parity, freshness rule-4 content tolerance, raster-failure
logging, preview warnings and the XML row off-by-one.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest


# 1. well_tie_host: descending depth axis integrates to the same positive TWT.
def test_twt_from_sonic_descending_axis_matches_ascending():
    from paleo_workbench.viz.hosts.well_tie_host import _twt_from_sonic

    depths_up = np.linspace(1000.0, 2000.0, 101)
    sonic = np.full_like(depths_up, 100.0)  # µs/m
    twt_up = _twt_from_sonic(depths_up, sonic, depth_unit="m")
    twt_down = _twt_from_sonic(depths_up[::-1].copy(), sonic[::-1].copy(), depth_unit="m")
    assert twt_up[-1] == pytest.approx(200.0)  # 1000 m @ 100 µs/m → 200 ms
    assert twt_down[0] == pytest.approx(200.0)  # same boundary in file order
    assert np.allclose(twt_down, twt_up[::-1])


# 2. DTW: |n_ref − n_tgt| > window is infeasible → empty path, inf cost.
def test_dtw_unreachable_band_returns_empty_path():
    from paleo_workbench.viz.dtw_log_matcher import DTWLogMatcher

    ref = np.sin(np.linspace(0.0, 6.28, 10))
    tgt = np.sin(np.linspace(0.0, 6.28, 50))
    result = DTWLogMatcher().match_curves(ref, tgt, window=3)
    assert result.cost == float("inf")
    assert result.path_ref == [] and result.path_target == []


# 3. Sculpt: non-positive radius is a no-op, not ZeroDivisionError.
def test_sculpt_nonpositive_radius_is_noop():
    from paleo_workbench.viz.horizon_sculpting import SculptableHorizonMesh

    verts = np.array([[0.0, 0.0, 10.0], [1.0, 0.0, 10.0], [0.0, 1.0, 10.0]], dtype=np.float32)
    mesh = SculptableHorizonMesh(verts, grid_shape=(1, 1))
    out = mesh.sculpt_surface((0.5, 0.5), delta_z=-3.0, radius=0.0)
    assert np.array_equal(out, verts)
    assert mesh.sculpt_surface((0.5, 0.5), delta_z=-3.0, radius=-1.0) is not None


# 4. Advisor: plane distance uses d/|n| — far planes clear, near ones warn.
def test_advisor_coplanar_normalizes_plane_offset():
    from paleo_workbench.viz.geomodel.advisor import check_coplanar_faults
    from paleo_workbench.viz.geomodel.models import FaultRecord

    def fault(name, nx, d):
        return FaultRecord(name=name, normal=(nx, 0.0, 0.0), d=d)

    # Non-unit normals: planes physically 80 m apart must NOT warn.
    far = check_coplanar_faults([fault("F1", 10.0, 100.0), fault("F2", 10.0, 900.0)])
    assert not any("coplanar" in i.get("message", "") for i in far["issues"])
    # Planes physically 0.5 m apart MUST warn.
    near = check_coplanar_faults([fault("F3", 10.0, 100.0), fault("F4", 10.0, 105.0)])
    assert any("coplanar" in i.get("message", "") for i in near["issues"])


# 5. Catalog search: index and scan agree for non-ASCII case variants.
def test_asset_search_unicode_casefold_parity(tmp_path):
    from paleo_workbench.catalog.db import normalize_asset_search_name
    from paleo_workbench.catalog.queries import search_assets
    from paleo_workbench.catalog.service import DataCatalogService

    assert "grünfeld" in normalize_asset_search_name("GRÜNFELD 油田")

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    src = tmp_path / "src" / "grün.las"
    src.parent.mkdir()
    src.write_text("~Version\n", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    try:
        svc.import_raw(src, name="Grünfeld 油田")
        # Index path (index fresh after save).
        via_index = [a.name for a in search_assets(svc, text="GRÜNFELD")]
        assert via_index == ["Grünfeld 油田"]
    finally:
        svc.close()


# 6. Freshness rule 4: byte-identical branch-off does not invalidate.
def test_freshness_rule4_tolerates_identical_branch():
    from types import SimpleNamespace

    from paleo_workbench.workflow.freshness import FreshnessService

    vid, sel = "ver_p", "ver_q"
    graph = SimpleNamespace(
        producing_run={vid: "run_orig", sel: "run_branch"},
        runs={
            "run_orig": SimpleNamespace(
                domain_task_id=None, parameters={}
            ),
            "run_branch": SimpleNamespace(
                domain_task_id="task_copy",
                parameters={"parent_version_id": vid},
            ),
        },
        asset_id_for=lambda _v: None,
        versions={
            vid: SimpleNamespace(checksum="sha-identical", trashed=False),
            sel: SimpleNamespace(checksum="sha-identical", trashed=False),
        },
    )
    context = SimpleNamespace(
        current_by_domain_task={},
        current_for_asset=lambda _a: None,
        selected_version_ids={sel},
    )
    service = FreshnessService(graph, context)
    # sel is a selected branch-off of vid with identical bytes: rule 4 must
    # tolerate it like rules 1-3 (previously returned a false STALE).
    assert service._selection_mismatch(vid) is None
    # A branch-off with DIFFERENT bytes still supersedes.
    graph.versions[sel].checksum = "sha-different"
    service.clear_cache()
    assert service._selection_mismatch(vid) == (sel, None)


# 7. NativeMapCanvas raster failure logs once per layer+key.
def test_raster_failure_is_logged(qtbot, caplog):
    from types import SimpleNamespace

    from paleo_workbench.ui.native_map_canvas import NativeMapCanvas

    canvas = NativeMapCanvas()
    qtbot.addWidget(canvas)
    request = SimpleNamespace(
        scene_epoch=canvas._scene_epoch, layer_id="layer-1", raster_key=(8, 8)
    )
    with caplog.at_level(logging.WARNING, logger="paleo_workbench.ui.native_map_canvas"):
        canvas._on_raster_failed(request, "boom")
        canvas._on_raster_failed(request, "boom")
    warnings = [r for r in caplog.records if "栅格化失败" in r.message]
    assert len(warnings) == 1  # deduped per layer+raster_key


# 12a. SEGY preview: volume-load failure surfaces in warning, not silence.
def test_segy_preview_volume_failure_visible(tmp_path, monkeypatch):
    import paleo_workbench.resources.preview_parsers.seismic_parsers as sp
    from paleo_workbench.project.models import ResourceItem
    from paleo_workbench.ui.pages.preview_settings import PreviewSettings

    try:
        import segyio  # noqa: F401
    except ImportError:
        pytest.skip("segyio unavailable")

    # A minimal valid single-trace SEGY so the metadata read succeeds.
    import segyio

    path = tmp_path / "shot.sgy"
    spec = segyio.spec()
    spec.ilines = [1]
    spec.xlines = [1]
    spec.samples = range(4)
    spec.format = 1
    with segyio.create(str(path), spec) as cube:
        cube.trace[0] = [0.0, 1.0, 0.0, -1.0]

    resource = ResourceItem(
        name="shot.sgy", type="seismic", format="segy", path=str(path)
    )

    def _boom(_p):
        raise RuntimeError("synthetic loader failure")

    monkeypatch.setattr(
        "paleo_workbench.viz.seismic_load.load_seismic_volume_from_path",
        _boom,
        raising=False,
    )
    result = sp.segy_preview(resource, PreviewSettings())
    assert result.warning, "volume loader failure must be visible in warning"


# 13. XML well-log preview: every sheet shows max_preview_rows data rows.
def test_xml_well_log_preview_full_row_budget():
    from paleo_workbench.resources.preview_parsers.well_log_parsers import (
        xml_well_log_preview,
    )
    from paleo_workbench.project.models import ResourceItem
    from paleo_workbench.ui.pages.preview_settings import PreviewSettings

    max_rows = 20
    rows_xml = ['<Row><Cell><Data ss:Type="Number">%d</Data></Cell>'
                '<Cell><Data ss:Type="Number">%d</Data></Cell></Row>' % (i, i * 10)
                for i in range(max_rows + 2)]
    doc = (
        '<?xml version="1.0"?>'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        "<Worksheet ss:Name=\"Sheet1\"><Table>"
        + "<Row><Cell><Data ss:Type=\"String\">MD</Data></Cell>"
        "<Cell><Data ss:Type=\"String\">GR</Data></Cell></Row>"
        + "".join(rows_xml)
        + "</Table></Worksheet></Workbook>"
    )
    path = Path("/tmp/issue897_sheet.xml")
    path.write_text(doc, encoding="utf-8")
    resource = ResourceItem(
        name="sheet.xml", type="well_log", format="xml", path=str(path)
    )
    settings = PreviewSettings(table_max_rows=max_rows)
    result = xml_well_log_preview(resource, settings)
    assert result is not None and len(result.data_rows) == max_rows, (
        f"expected {max_rows} data rows, got "
        f"{len(result.data_rows) if result else 'None'}"
    )
