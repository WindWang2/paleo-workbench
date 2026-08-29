"""Project save/reopen and catalog lifecycle for managed factor-grid artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from paleo_workbench.catalog import CoreCatalogAdapter, DataCatalogService, DataStage
from paleo_workbench.catalog.lifecycle import register_persisted_factor_grids
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.project.factor_grid_artifacts import factor_grid_result_for_task
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.viz.native_factor_map import scene_from_factor_task


def _completed_task() -> FactorMapTask:
    return FactorMapTask(
        id="factor_pora",
        name="H1 孔隙度",
        target_horizon="H1",
        factor_type="孔隙度",
        method="IDW",
        status="complete",
        parameters={
            "sample_points": [
                {"x": 0.0, "y": 0.0, "z": 2.0},
                {"x": 2.0, "y": 1.0, "z": 5.0},
            ],
            "grid": "3×2",
            "grid_x": [0.0, 1.0, 2.0],
            "grid_y": [0.0, 1.0],
            "grid_z": [[2.0, None, 4.0], [3.0, 4.0, 5.0]],
            "grid_var": [[0.1, 0.2, 0.3], [0.2, 0.3, 0.4]],
            "interp_backend": "kriging",
            "power": 2.0,
        },
    )


def test_project_save_externalizes_grid_and_native_scene_reopens_it(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    project = ProjectDocument.new("Demo")
    project.factor_map_tasks.append(_completed_task())

    manager = ProjectManager(project_path)
    manager.save(project)

    stored = json.loads(project_path.read_text(encoding="utf-8"))
    task_data = stored["factor_map_tasks"][0]
    assert set(task_data["parameters"]).isdisjoint(
        {"grid_x", "grid_y", "grid_z", "grid_var"}
    )
    assert task_data["grid_artifact_path"] == (
        "demo.artifacts/factor_maps/factor_pora.factor_grid.npz"
    )
    artifact_path = tmp_path / task_data["grid_artifact_path"]
    assert artifact_path.is_file()

    loaded = manager.load()
    task = loaded.factor_map_tasks[0]
    assert task.grid_artifact_path == artifact_path.resolve().as_posix()
    result = factor_grid_result_for_task(task, crs="EPSG:32650")
    assert result.shape == (2, 3)
    assert result.variance_grid is not None
    assert np.isnan(result.grid_z[0, 1])

    # The reopen path feeds the native scene directly; it must not require an
    # inline legacy grid or invoke interpolation.
    scene = scene_from_factor_task(task, crs="EPSG:32650")
    assert scene.scalar_layer(task.id) is not None
    assert scene.registry.get(task.id).source_ref == task.grid_artifact_path


def test_legacy_inline_grid_is_readable_then_migrates_on_next_save(tmp_path: Path):
    project_path = tmp_path / "legacy.paleo.json"
    original = ProjectDocument.new("Legacy")
    original.factor_map_tasks.append(_completed_task())
    project_path.write_text(
        json.dumps(original.model_dump(), ensure_ascii=False), encoding="utf-8"
    )

    manager = ProjectManager(project_path)
    loaded = manager.load()
    legacy = loaded.factor_map_tasks[0]
    assert legacy.grid_artifact_path is None
    assert factor_grid_result_for_task(legacy).shape == (2, 3)

    manager.save(loaded)
    migrated = json.loads(project_path.read_text(encoding="utf-8"))["factor_map_tasks"][0]
    assert migrated["grid_artifact_path"]
    assert "grid_z" not in migrated["parameters"]
    assert (tmp_path / migrated["grid_artifact_path"]).is_file()


def test_persisted_grid_registers_once_as_catalog_intermediate(tmp_path: Path):
    project_path = tmp_path / "catalogued.paleo.json"
    project = ProjectDocument.new("Catalogued")
    project.factor_map_tasks.append(_completed_task())
    ProjectManager(project_path).save(project)

    service = DataCatalogService.open(project_path)
    adapter = CoreCatalogAdapter(service)
    set_catalog(adapter)
    try:
        versions = register_persisted_factor_grids(project)
        assert len(versions) == 1
        version = versions[0]
        assert version.stage is DataStage.INTERMEDIATE
        assert Path(version.path).is_file()
        assert project.factor_map_tasks[0].grid_artifact_version_id == version.version_id
        assert project.factor_map_tasks[0].grid_artifact_path == version.path
        assert register_persisted_factor_grids(project) == []
        assert len([run for run in adapter.list_runs() if run.operation == "factor_map"]) == 1
    finally:
        reset_catalog()
        service.close()


def test_controller_save_as_registers_and_rebases_managed_grid(tmp_path: Path):
    """The real save-as lifecycle persists both task references and catalog version."""
    from paleo_workbench.ui.project_controller import ProjectController

    class _Window:
        def __init__(self, project):
            self.project = project
            self.project_path = None

        @staticmethod
        def _flush_mapping_draft() -> bool:
            return True

        @staticmethod
        def _show_project_error(*_args) -> None:
            raise AssertionError("project save unexpectedly failed")

    project = ProjectDocument.new("Controller")
    project.factor_map_tasks.append(_completed_task())
    window = _Window(project)
    controller = ProjectController(window)

    first = controller.save_project_as(tmp_path / "first.paleo.json")
    assert first is not None
    task = window.project.factor_map_tasks[0]
    assert task.grid_artifact_version_id
    assert task.grid_artifact_path and Path(task.grid_artifact_path).is_file()

    second = controller.save_project_as(tmp_path / "second.paleo.json")
    assert second is not None
    task = window.project.factor_map_tasks[0]
    assert task.grid_artifact_path and task.grid_artifact_path.startswith(
        (tmp_path / "second.artifacts").as_posix()
    )
    reopened = ProjectManager(second).load()
    assert factor_grid_result_for_task(reopened.factor_map_tasks[0]).shape == (2, 3)
