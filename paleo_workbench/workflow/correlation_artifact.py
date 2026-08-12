"""Portable correlation / fault interpretation artifacts (JSON, no curve dumps)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from paleo_workbench.workflow.stratigraphy_models import (
    CorrelationScientificPayload,
    FaultInterpretationPayload,
)

CORR_ARTIFACT_SUFFIX = ".correlation.json"
FAULT_ARTIFACT_SUFFIX = ".fault_interp.json"


def stable_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scientific_fingerprint_correlation(payload: CorrelationScientificPayload) -> str:
    return stable_sha256(payload.scientific_dict())


def scientific_fingerprint_fault(payload: FaultInterpretationPayload) -> str:
    return stable_sha256(payload.scientific_dict())


def write_correlation_artifact(
    payload: CorrelationScientificPayload,
    directory: Path | str,
    basename: str,
    *,
    extra_descriptor: dict[str, Any] | None = None,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{basename}{CORR_ARTIFACT_SUFFIX}"
    body = {
        "kind": "stratigraphic_correlation",
        "scientific": payload.scientific_dict(),
        "fingerprint": scientific_fingerprint_correlation(payload),
        "descriptor": dict(extra_descriptor or {}),
    }
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_correlation_artifact(
    path: Path | str,
) -> tuple[CorrelationScientificPayload, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sci = data.get("scientific") or data
    payload = CorrelationScientificPayload.model_validate(sci)
    return payload, dict(data.get("descriptor") or {})


def write_fault_artifact(
    payload: FaultInterpretationPayload,
    directory: Path | str,
    basename: str,
    *,
    extra_descriptor: dict[str, Any] | None = None,
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{basename}{FAULT_ARTIFACT_SUFFIX}"
    body = {
        "kind": "fault_interpretation",
        "scientific": payload.scientific_dict(),
        "fingerprint": scientific_fingerprint_fault(payload),
        "descriptor": dict(extra_descriptor or {}),
    }
    path.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_fault_artifact(
    path: Path | str,
) -> tuple[FaultInterpretationPayload, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    sci = data.get("scientific") or data
    payload = FaultInterpretationPayload.model_validate(sci)
    return payload, dict(data.get("descriptor") or {})
