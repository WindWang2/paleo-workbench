"""Export QualityReport documents to JSON for the review page."""

from __future__ import annotations

import json
from pathlib import Path

from paleo_workbench.project.artifacts import record_export
from paleo_workbench.project.models import QualityReport


def export_quality_report_json(
    report: QualityReport,
    output_path: Path | str,
    *,
    project=None,
    register: bool = True,
) -> Path:
    """Write a single QC report as UTF-8 JSON; optionally register ExportArtifact."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump() if hasattr(report, "model_dump") else dict(report)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if register and project is not None:
        record_export(
            project,
            linked_id=report.linked_map_document_id or report.id,
            output_path=str(path),
            fmt="qc_json",
            source_task_ids=[],
        )
    return path
