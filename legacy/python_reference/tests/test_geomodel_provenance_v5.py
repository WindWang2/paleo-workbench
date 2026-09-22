"""Catalog provenance wiring (G15) + V2 export flow from the page worker.

The catalog is exercised in-memory through its public lifecycle helpers, the
same seam the page uses — no UI/SQLite reach-ins.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.ui.pages.geological_modeling_workers import ExportWorker
from paleo_workbench.viz.geomodel.builders import (
    build_horizon_from_grid,
    build_volume_shell,
)
from paleo_workbench.viz.geomodel.domain import Provenance

CRS = "EPSG:32650"


@pytest.fixture()
def volume():
    tg = np.full((5, 5), 100.0)
    bg = np.full((5, 5), 150.0)
    top = build_horizon_from_grid("Top", tg, origin=(0, 0), spacing=(10.0, 10.0), crs=CRS)
    base = build_horizon_from_grid("Base", bg, origin=(0, 0), spacing=(10.0, 10.0), crs=CRS)
    vol, _ = build_volume_shell(
        top, base, [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)],
        object_id="volume:sand", name="Sand",
    )
    return vol, top, base


class TestExportWorkerV2:
    def test_volume_flac3d_export_with_validation(self, volume, tmp_path):
        vol, top, base = volume
        from paleo_workbench.viz.geomodel.models import GridSpec

        worker = ExportWorker(
            str(tmp_path / "sand.f3grid"), "flac3d", GridSpec(4, 4, 2),
            volume=vol, top=top, base=base,
        )
        results = []
        worker.completed.connect(results.append)
        worker.run()
        assert results == [str(tmp_path / "sand.f3grid")]
        # sidecar + parse-back
        from paleo_workbench.viz.geomodel.exporters import read_flac3d_grid

        parsed = read_flac3d_grid(tmp_path / "sand.f3grid")
        assert parsed["zone_count"] == 16 * 4
        assert (tmp_path / "sand.provenance.json").exists()

    def test_blocker_volume_fails_worker(self, tmp_path):
        from paleo_workbench.viz.geomodel.domain import StratigraphicVolume
        from paleo_workbench.viz.geomodel.models import GridSpec

        bad = StratigraphicVolume(
            object_id="volume:bad", name="bad", crs="unknown"
        )
        worker = ExportWorker(
            str(tmp_path / "bad.f3grid"), "flac3d", GridSpec(4, 4, 2), volume=bad
        )
        errors = []
        worker.failed.connect(errors.append)
        worker.run()
        assert errors, "QC blocker must fail the export worker"
        assert not (tmp_path / "bad.f3grid").exists()

    def test_surface_obj_export(self, volume, tmp_path):
        from paleo_workbench.viz.geomodel.models import GridSpec

        vol, _, _ = volume
        worker = ExportWorker(
            str(tmp_path / "sand.obj"), "obj", GridSpec(4, 4, 2), surface=vol
        )
        worker.run()
        assert (tmp_path / "sand.obj").exists()


class TestProvenanceLifecycle:
    def test_modeling_run_registers_with_honest_demo(self, tmp_path):
        """register_modeling_run: demo runs carry no output version (truth:
        the demo result is memory-only)."""
        from paleo_workbench.catalog.lifecycle import register_modeling_run

        run, version = register_modeling_run(
            name="3D 建模 (demo)",
            source="synthetic/demo",
            demo=True,
            parameters={"density": "中精度"},
            input_version_ids=[],
            output_path=None,
            output_format=None,
            catalog=None,
        )
        # best-effort without a live catalog service → None/None tolerated
        assert version is None

    def test_export_output_registration_is_best_effort(self, volume, tmp_path):
        """register_export_output never breaks the export flow (page contract)."""
        from paleo_workbench.catalog.lifecycle import register_export_output

        vol, _, _ = volume
        out = tmp_path / "sand.f3grid"
        from paleo_workbench.viz.geomodel.exporters import export_volume_flac3d

        export_volume_flac3d(vol, out)
        # no catalog configured → must not raise
        register_export_output(
            name="数值模拟网格模型 export",
            output_path=str(out),
            fmt="f3grid",
            source_version_ids=["hv1"],
            linked_id="geological_modeling_3d",
            catalog=None,
        )

    def test_provenance_sidecar_carries_qc_and_sources(self, volume, tmp_path):
        import json

        vol, _, _ = volume
        from paleo_workbench.viz.geomodel.exporters import export_volume_flac3d

        export_volume_flac3d(vol, tmp_path / "s.f3grid")
        sidecar = json.loads(
            (tmp_path / "s.provenance.json").read_text(encoding="utf-8")
        )
        assert sidecar["crs"] == CRS
        assert sidecar["qc"]["worst"] in ("info", "ok", "warning")
        assert sidecar["mesh"]["merge"] == "none"
        assert sidecar["indexing"].startswith("node/element ids")
