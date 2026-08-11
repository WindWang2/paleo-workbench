from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, _now_iso
from paleo_workbench.project.factor_grid_artifacts import persist_factor_grid_artifacts
from paleo_workbench.project.paths import (
    ensure_artifact_layout,
    relativize_path,
    resolve_project_path,
)


def _relativize_reference_layers(data: dict, project_path: Path) -> None:
    for doc in data.get("paleomap_documents") or []:
        for layer in doc.get("reference_layers") or []:
            source = layer.get("source_path")
            if not source:
                continue
            path, external = relativize_path(source, project_path)
            layer["source_path"] = path
            layer["external"] = external


def _resolve_reference_layers(data: dict, project_path: Path) -> None:
    for doc in data.get("paleomap_documents") or []:
        for layer in doc.get("reference_layers") or []:
            source = layer.get("source_path")
            if not source:
                continue
            layer["source_path"] = resolve_project_path(source, project_path)
            # File presence check on the resolved absolute path (status offline).
            path = Path(layer["source_path"])
            if not path.is_file():
                layer["status"] = "offline"
                layer["error_message"] = layer.get("error_message") or "参考图源文件不可用"
            elif layer.get("status") == "offline":
                layer["status"] = "ready"
                if layer.get("error_message") == "参考图源文件不可用":
                    layer["error_message"] = ""


def _relativize_factor_grid_artifacts(data: dict, project_path: Path) -> None:
    for task in data.get("factor_map_tasks") or []:
        artifact_path = task.get("grid_artifact_path")
        if not artifact_path:
            continue
        stored, _ = relativize_path(artifact_path, project_path)
        task["grid_artifact_path"] = stored


def _resolve_factor_grid_artifacts(data: dict, project_path: Path) -> None:
    for task in data.get("factor_map_tasks") or []:
        artifact_path = task.get("grid_artifact_path")
        if not artifact_path:
            continue
        task["grid_artifact_path"] = resolve_project_path(artifact_path, project_path)


class ProjectManager:
    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)

    def save(self, project: ProjectDocument) -> None:
        updated_at = _now_iso()
        # Persist numerical grids before constructing the JSON payload, so no inline
        # grid arrays leak back into a saved project.
        persist_factor_grid_artifacts(project, self.project_path)
        data = project.model_dump()
        data["meta"]["updated_at"] = updated_at
        for resource in data["resources"]:
            path, external = relativize_path(resource["path"], self.project_path)
            resource["path"] = path
            resource["external"] = external
        for artifact in data["export_artifacts"]:
            output_path, _ = relativize_path(artifact["output_path"], self.project_path)
            artifact["output_path"] = output_path
        _relativize_reference_layers(data, self.project_path)
        _relativize_factor_grid_artifacts(data, self.project_path)
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        ensure_artifact_layout(self.project_path)
        # Atomic replace so a crash mid-write cannot leave a truncated project file.
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.project_path.name}.",
            suffix=".tmp",
            dir=str(self.project_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.project_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        project.meta.updated_at = updated_at

    def load(self) -> ProjectDocument:
        data = json.loads(self.project_path.read_text(encoding="utf-8"))
        # Project files keep in-project paths relative for portability. Runtime
        # consumers such as previews must receive paths anchored to this project,
        # rather than to the application's current working directory.
        for resource in data.get("resources", []):
            resource["path"] = resolve_project_path(resource["path"], self.project_path)
        for artifact in data.get("export_artifacts", []):
            artifact["output_path"] = resolve_project_path(
                artifact["output_path"], self.project_path
            )
        _resolve_reference_layers(data, self.project_path)
        _resolve_factor_grid_artifacts(data, self.project_path)
        return ProjectDocument.model_validate(data)
