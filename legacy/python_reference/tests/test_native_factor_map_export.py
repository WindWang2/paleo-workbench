"""Native factor-map snapshot export uses the shared OUTPUT lifecycle path."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.catalog import CoreCatalogAdapter, DataCatalogService, DataStage
from paleo_workbench.catalog.lifecycle import register_persisted_factor_grids
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.resources.export_service import (
    export_widget_snapshot,
    view_export_capabilities,
)
from paleo_workbench.ui.native_map_canvas import NativeMapCanvas

from tests.test_factor_grid_project_lifecycle import _completed_task
from paleo_workbench.viz.native_factor_map import scene_from_factor_task


def test_native_factor_map_png_export_registers_output_lineage(qtbot, tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    project = ProjectDocument.new("Demo")
    project.factor_map_tasks.append(_completed_task())
    ProjectManager(project_path).save(project)

    service = DataCatalogService.open(project_path)
    adapter = CoreCatalogAdapter(service)
    set_catalog(adapter)
    try:
        grid_version = register_persisted_factor_grids(project)[0]
        scene = scene_from_factor_task(project.factor_map_tasks[0])
        canvas = NativeMapCanvas(scene)
        canvas.resize(320, 220)
        qtbot.addWidget(canvas)
        canvas.show()
        qtbot.wait(10)

        output_path = tmp_path / "demo.artifacts" / "exports" / "factor-map.png"
        exported = export_widget_snapshot(
            canvas,
            output_path,
            "PNG",
            project=project,
            project_path=project_path,
            linked_id=project.factor_map_tasks[0].id,
            source_task_ids=[project.factor_map_tasks[0].id],
        )

        assert view_export_capabilities(canvas) == frozenset({"PNG"})
        assert exported.success is True
        assert output_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert exported.artifact is not None
        assert exported.artifact.catalog_version_id
        assert "native_factor_map" in exported.artifact.included_map_elements
        output_version = adapter.resolve_version(exported.artifact.catalog_version_id)
        assert output_version is not None and output_version.stage is DataStage.OUTPUT
        ancestors = adapter.query_lineage(output_version.version_id)
        assert grid_version.version_id in {item.version_id for item in ancestors}
    finally:
        reset_catalog()
        service.close()
