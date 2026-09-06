"""Geoscience interchange layer: unified format adapters, import preflight,
export verification, portable project packaging, dependency audit, batch
conversion, and delivery reports.

Design contract (docs/development/interchange-delivery-v5/decisions.md):

    Inspect -> Plan -> Execute -> Verify -> Register

- The data catalog (:mod:`paleo_workbench.catalog`) stays the single lifecycle
  authority; this layer only orchestrates through it.
- Adapters wrap existing parsers (geoviz / lasio / segyio / GDAL / rasterio /
  geomodel exporters); nothing is re-parsed.
- Formats the repository cannot genuinely serve are declared
  capability-unavailable, never faked.
"""

from __future__ import annotations

from paleo_workbench.interchange.contracts import (
    CancelToken,
    CancelledError,
    ExportPlan,
    ExportVerification,
    FormatCapability,
    FormatNotSupportedError,
    ImportExecutionResult,
    ImportPlan,
    InspectionResult,
    InterchangeError,
    PreflightFailedError,
    SniffResult,
    VerificationCheck,
    VerificationState,
)
from paleo_workbench.interchange.executor import ExportExecutor, ImportExecutor
from paleo_workbench.interchange.preflight import (
    ImportPreflightService,
    PreflightIssue,
    PreflightReport,
)
from paleo_workbench.interchange.registry import (
    FormatAdapter,
    InterchangeRegistry,
    default_registry,
    sniff_format,
)

__all__ = [
    "CancelToken",
    "CancelledError",
    "ExportPlan",
    "ExportVerification",
    "FormatAdapter",
    "FormatCapability",
    "FormatNotSupportedError",
    "ImportExecutionResult",
    "ImportExecutor",
    "ImportPlan",
    "ImportPreflightService",
    "InspectionResult",
    "InterchangeError",
    "InterchangeRegistry",
    "PreflightFailedError",
    "PreflightIssue",
    "PreflightReport",
    "SniffResult",
    "VerificationCheck",
    "VerificationState",
    "default_registry",
    "sniff_format",
]
