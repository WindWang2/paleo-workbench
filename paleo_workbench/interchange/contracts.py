"""Interchange contracts: the shared vocabulary of the import/export lifecycle.

Every format flow goes through five phases:

    Inspect -> Plan -> Execute -> Verify -> Register

- ``inspect`` reads the minimum metadata needed to describe the file; it never
  writes anything.
- ``plan`` produces a serializable :class:`ImportPlan` / :class:`ExportPlan`
  describing exactly what will happen (managed copy vs external reference,
  transforms, warnings, estimated bytes).
- ``execute`` performs the copy/transform through controlled services, is
  cancellable, and leaves no half-written artifacts (temp + atomic rename).
- ``verify`` re-opens the output structurally (never just "file exists") and
  returns an :class:`ExportVerification` in one of four states; ``UNVERIFIED``
  must never be presented as verified.
- ``register`` records the result in the data catalog (the single lifecycle
  authority) so provenance stays intact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


class InterchangeError(Exception):
    """Base class for interchange failures."""


class FormatNotSupportedError(InterchangeError):
    """Raised when a format has no usable adapter or capability."""


class PreflightFailedError(InterchangeError):
    """Raised when preflight rejects an input; nothing has been registered."""


class CancelledError(InterchangeError):
    """Raised when a cancelled operation reaches a cancellation checkpoint."""


class CancelToken:
    """Cooperative cancellation handle shared across batch/adapter operations.

    ``check()`` raises :class:`CancelledError` at well-defined checkpoints so
    callers never observe a partially committed result (all writers use
    temp-file + atomic rename, so cancellation mid-write leaves the previous
    state untouched).
    """

    __slots__ = ("_cancelled", "_reason")

    def __init__(self) -> None:
        self._cancelled = False
        self._reason = ""

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str = "cancelled") -> None:
        if not self._cancelled:
            self._cancelled = True
            self._reason = reason

    def check(self) -> None:
        if self._cancelled:
            raise CancelledError(self._reason or "cancelled")

    def checkpoint(self) -> None:
        self.check()


NULL_CANCEL = CancelToken()


def _null_progress(fraction: float, message: str = "") -> None:
    return None


ProgressCallback = Callable[[float, str], None]


@dataclass(frozen=True)
class SniffResult:
    """Outcome of a bounded magic/header probe."""

    format_id: str  # best-effort candidate, "" when undetermined
    confidence: str  # "high" | "medium" | "low"
    evidence: str  # why, e.g. "tiff-magic", "las-version-section"
    extension: str = ""

    @property
    def determined(self) -> bool:
        return bool(self.format_id)


@dataclass(frozen=True)
class FormatCapability:
    """What an adapter honestly supports (declared, never guessed)."""

    read: bool = False
    inspect: bool = False
    import_data: bool = False
    export: bool = False
    roundtrip_verify: bool = False
    notes: str = ""


class VerificationState(str, Enum):
    VERIFIED = "VERIFIED"
    VERIFIED_WITH_WARNINGS = "VERIFIED_WITH_WARNINGS"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class VerificationCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ExportVerification:
    """Structural re-open result of an exported artifact."""

    state: VerificationState
    checks: list[VerificationCheck] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.state in (VerificationState.VERIFIED, VerificationState.VERIFIED_WITH_WARNINGS)

    @classmethod
    def unverified(cls, detail: str) -> "ExportVerification":
        return cls(state=VerificationState.UNVERIFIED, detail=detail)

    @classmethod
    def failed(cls, checks: Iterable[VerificationCheck], detail: str = "") -> "ExportVerification":
        return cls(state=VerificationState.FAILED, checks=list(checks), detail=detail)

    def summary(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "detail": self.detail,
            "warnings": list(self.warnings),
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
        }


@dataclass
class InspectionResult:
    """Minimum metadata read by ``inspect``; serializable, read-only."""

    format_id: str
    ok: bool = True
    size_bytes: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    crs: str | None = None
    units: dict[str, str] = field(default_factory=dict)
    dataset_bounds: tuple[float, float, float, float] | None = None
    object_type: str = ""  # e.g. "well_log", "vector_layer", "raster", "volume"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "format_id": self.format_id,
            "ok": self.ok,
            "size_bytes": self.size_bytes,
            "crs": self.crs,
            "units": dict(self.units),
            "object_type": self.object_type,
            "bounds": list(self.dataset_bounds) if self.dataset_bounds else None,
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class ImportPlan:
    """Serializable statement of what an import will do before it runs."""

    format_id: str
    source_path: str
    action: str  # "managed_copy" | "link_external" | "transform_import" | "unsupported"
    asset_name: str
    warnings: list[str] = field(default_factory=list)
    estimated_bytes: int = 0
    transform: str | None = None  # adapter-local transform id, e.g. "csv_normalize"
    metadata: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_id": self.format_id,
            "source_path": self.source_path,
            "action": self.action,
            "asset_name": self.asset_name,
            "warnings": list(self.warnings),
            "estimated_bytes": self.estimated_bytes,
            "transform": self.transform,
            "metadata": dict(self.metadata),
            "options": dict(self.options),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ImportPlan":
        return cls(
            format_id=str(data["format_id"]),
            source_path=str(data["source_path"]),
            action=str(data["action"]),
            asset_name=str(data["asset_name"]),
            warnings=[str(w) for w in data.get("warnings", ())],
            estimated_bytes=int(data.get("estimated_bytes", 0)),
            transform=data.get("transform"),
            metadata=dict(data.get("metadata", {})),
            options=dict(data.get("options", {})),
        )


@dataclass
class ImportExecutionResult:
    """Outcome of executing an import plan through the catalog."""

    version_id: str | None = None
    asset_id: str | None = None
    managed: bool = True
    verification: ExportVerification | None = None
    staged_path: str | None = None  # for transform_import: registered file

    def summary(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "asset_id": self.asset_id,
            "managed": self.managed,
            "verification": self.verification.summary() if self.verification else None,
        }


@dataclass
class ExportPlan:
    """Serializable statement of what an export will produce."""

    format_id: str
    source_path: str
    target_path: str
    estimated_bytes: int = 0
    options: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_id": self.format_id,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "estimated_bytes": self.estimated_bytes,
            "options": dict(self.options),
            "warnings": list(self.warnings),
        }
