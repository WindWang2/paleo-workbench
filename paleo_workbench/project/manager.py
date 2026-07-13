from __future__ import annotations

import json
from pathlib import Path

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.project.paths import (
    ensure_artifact_layout,
    relativize_path,
    resolve_project_path,
)


class ProjectManager:
    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)

    def save(self, project: ProjectDocument) -> None:
        data = project.model_dump()
        for resource in data["resources"]:
            path, external = relativize_path(resource["path"], self.project_path)
            resource["path"] = path
            resource["external"] = external
        for artifact in data["export_artifacts"]:
            output_path, _ = relativize_path(artifact["output_path"], self.project_path)
            artifact["output_path"] = output_path
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        ensure_artifact_layout(self.project_path)
        self.project_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
        return ProjectDocument.model_validate(data)
