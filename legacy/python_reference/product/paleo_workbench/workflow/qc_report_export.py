"""Export QualityReport documents to JSON for the review page."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from paleo_workbench.project.artifacts import record_export
from paleo_workbench.project.models import QualityReport
from paleo_workbench.resources.exporters import atomic_output


def _json_safe(value: Any) -> Any:
    """Normalize non-finite floats to null so strict JSON parsers accept the file."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


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
    text = json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False)
    with atomic_output(path) as tmp_path:
        tmp_path.write_text(text, encoding="utf-8")
        # Verify the delivered file parses before publishing/registering it.
        json.loads(tmp_path.read_text(encoding="utf-8"))
    if register and project is not None:
        record_export(
            project,
            linked_id=report.linked_map_document_id or report.id,
            output_path=str(path),
            fmt="qc_json",
            source_task_ids=[report.id],
            source_resource_ids=(
                [report.linked_map_document_id] if report.linked_map_document_id else None
            ),
        )
    return path
