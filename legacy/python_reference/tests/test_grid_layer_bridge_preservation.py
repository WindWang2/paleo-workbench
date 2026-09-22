"""#1034 — the continuous raster must survive the MapDocument bridge.

Bridging ``MapDocument`` (GIS layer stack) to the legacy
``PaleoMapDocument`` record only carried contour/well-point/polygon vector
features; the ``GridMapLayer`` produced by interpolation was silently
dropped, so the authored map lost its continuous raster. The fix preserves
the raster through the artifact-first factor task: the compatibility record
carries ``linked_factor_task_id``, the same linkage pattern as the existing
``linked_prediction_task_id`` / ``linked_contour_draft_id`` seams, and the
grid stays resolvable for rendering without duplicuting megabytes into
``.paleo.json``.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.mapping.geological_pipeline.models import (
    GeologicalFactor,
    GeologicalFactorDataset,
)
from paleo_workbench.mapping.layers import GridMapLayer, MapDocument
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ProjectMeta
from paleo_workbench.services.geological_mapping_service import (
    GeologicalMappingService,
)


def _project() -> ProjectDocument:
    return ProjectDocument(meta=ProjectMeta(name="grid-bridge"))


def _dataset() -> GeologicalFactorDataset:
    dataset = GeologicalFactorDataset(
        factor_name="孔隙度", unit="%", target_horizon="H1", crs="EPSG:4326"
    )
    for i in range(6):
        dataset.add_point(
            GeologicalFactor(
                name="孔隙度",
                value=10.0 + 2.0 * i,
                unit="%",
                well_id=f"W{i}",
                well_name=f"井-{i}",
                x=114.0 + 0.05 * i,
                y=22.5 + 0.04 * i,
                crs="EPSG:4326",
                formation="H1",
            )
        )
    return dataset


def test_factor_map_document_contains_grid_layer_by_default():
    service = GeologicalMappingService()
    dataset = _dataset()
    project = _project()
    map_doc, task = service.create_factor_map(
        project, dataset.factor_name, target_horizon="H1"
    )
    grid_layers = [l for l in map_doc.layers if isinstance(l, GridMapLayer)]
    assert grid_layers, "pipeline must produce the continuous raster layer"


def test_bridge_preserves_the_continuous_raster_link():
    project = _project()
    service = GeologicalMappingService()
    dataset = _dataset()
    map_doc, task = service.create_factor_map(
        project, dataset.factor_name, target_horizon="H1"
    )

    paleo_map = project.paleomap_documents[-1]
    assert isinstance(paleo_map, PaleoMapDocument)
    # the compatibility record keeps the raster reachable (#1034)
    assert paleo_map.linked_factor_task_id == task.id
    stored_task = next(
        t for t in project.factor_map_tasks if t.id == paleo_map.linked_factor_task_id
    )
    assert stored_task is task


def test_linked_grid_is_resolvable_from_the_compatibility_record():
    """The rendering overlay path must be able to rebuild the raster from the
    linked task — no data loss between bridge and render."""
    from paleo_workbench.project.factor_grid_artifacts import (
        factor_grid_result_for_task,
    )

    project = _project()
    service = GeologicalMappingService()
    dataset = _dataset()
    map_doc, task = service.create_factor_map(
        project, dataset.factor_name, target_horizon="H1"
    )
    paleo_map = project.paleomap_documents[-1]

    stored = next(t for t in project.factor_map_tasks if t.id == paleo_map.linked_factor_task_id)
    grid = factor_grid_result_for_task(stored)
    assert grid is not None
    assert grid.grid_z.shape[0] > 1
    assert np.isfinite(grid.grid_z).any()


def test_roundtrip_project_json_preserves_the_grid_link(tmp_path):
    from paleo_workbench.project.manager import ProjectManager

    project = _project()
    service = GeologicalMappingService()
    dataset = _dataset()
    map_doc, task = service.create_factor_map(
        project, dataset.factor_name, target_horizon="H1"
    )
    path = tmp_path / "grid.paleo.json"
    ProjectManager(path).save(project)

    reloaded = ProjectManager(path).load()
    paleo_map = reloaded.paleomap_documents[-1]
    assert paleo_map.linked_factor_task_id is not None
    assert any(t.id == paleo_map.linked_factor_task_id for t in reloaded.factor_map_tasks)


def test_map_document_layer_kinds_all_survive_the_bridge():
    project = _project()
    service = GeologicalMappingService()
    dataset = _dataset()
    map_doc, task = service.create_factor_map(
        project, dataset.factor_name, target_horizon="H1", include_polygons=True
    )
    paleo_map = project.paleomap_documents[-1]

    kinds = {l.layer_type for l in map_doc.layers}
    # the produced document carries the full single-factor chain
    assert "grid" in kinds
    # and every VECTOR kind has its compatibility representation
    if "contour" in kinds:
        assert paleo_map.line_features, "contour features lost in bridge"
    if "well_point" in kinds:
        assert paleo_map.well_overlays, "well points lost in bridge"
    if {"polygon", "facies"} & kinds:
        assert paleo_map.facies_polygons, "facies polygons lost in bridge"
