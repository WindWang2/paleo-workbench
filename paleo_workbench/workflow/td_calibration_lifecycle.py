"""Time-depth calibration lifecycle: reviewed well-tie → versioned authority (L7/L9).

Closes the well–seismic tie loop with a single, auditable authority chain:

    sonic/density logs → integrated TWT (± reviewed bulk shift,
    optionally a BOUNDED stretch/squeeze) → reviewed pairs →
    TD-table artifact → catalog DERIVED version + DataRun (quality
    metadata) → project ``entity_asset_link(role=time_depth)`` →
    hub :class:`TimeDepthCalibration` (version_id + fingerprint)

The artifact is the SMI TD-table format ``parse_td_table`` already reads,
so a reopened project registers the calibration through the existing
``bind_project`` path — there is no second calibration authority.

Verification honesty: ``verified`` is True ONLY when the recorded
correlation passes the QC threshold AND a reviewer explicitly confirmed.
Nothing in this module auto-verifies a tie.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from paleo_workbench.catalog.service import DataCatalogService

GENERATOR_ID = "well-tie-calibration-v1"

#: Minimum normalized cross-correlation a tie must reach before a human
#: review may mark it verified (QC gate; below this the save still happens
#: but ``verified`` stays False).
QC_CORRELATION_THRESHOLD = 0.70

#: Bounded stretch/squeeze factors — local time-warping beyond ±10 % per
#: interval is not a tie correction anymore, it is fabricating a curve.
STRETCH_FACTOR_LIMITS = (0.90, 1.10)


class CalibrationBuildError(ValueError):
    """A calibration could not be built from the reviewed tie (fail-closed)."""


@dataclass(frozen=True)
class StretchSqueezeRecord:
    """A reviewed, BOUNDED piecewise time-warp.

    ``anchors_m`` are strictly increasing MD anchors; ``factors`` are the
    local TWT stretch factors at those anchors (1.0 = unchanged), each
    inside :data:`STRETCH_FACTOR_LIMITS`. Factors between anchors are
    linearly interpolated and applied to the TWT increments.
    """

    anchors_m: tuple[float, ...]
    factors: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.anchors_m) != len(self.factors):
            raise CalibrationBuildError(
                "stretch/squeeze anchors and factors must have the same length"
            )
        if len(self.anchors_m) < 2:
            raise CalibrationBuildError(
                "stretch/squeeze needs at least two anchors"
            )
        for a, b in zip(self.anchors_m, self.anchors_m[1:]):
            if not b > a:
                raise CalibrationBuildError(
                    f"stretch/squeeze anchors must strictly increase ({a} → {b})"
                )
        lo, hi = STRETCH_FACTOR_LIMITS
        for factor in self.factors:
            if not math.isfinite(factor) or not lo <= factor <= hi:
                raise CalibrationBuildError(
                    f"stretch/squeeze factor {factor} outside bounded range "
                    f"[{lo}, {hi}]"
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "anchors_m": list(self.anchors_m),
            "factors": list(self.factors),
            "limits": list(STRETCH_FACTOR_LIMITS),
        }


@dataclass
class TieReviewData:
    """What the tie workflow hands to the save (all user-attributable)."""

    well_name: str
    well_entity_id: str
    depths_m: np.ndarray
    twt_ms: np.ndarray
    bulk_shift_ms: float = 0.0
    correlation: float | None = None
    wavelet: str = "ricker"
    method: str = "sonic-integration"
    stretch: StretchSqueezeRecord | None = None
    reviewer: str = ""
    reviewer_confirmed: bool = False

    def __post_init__(self) -> None:
        self.depths_m = np.asarray(self.depths_m, dtype=np.float64)
        self.twt_ms = np.asarray(self.twt_ms, dtype=np.float64)
        if self.depths_m.size != self.twt_ms.size:
            raise CalibrationBuildError("depths and twt arrays must match in size")
        if self.depths_m.size < 2:
            raise CalibrationBuildError("a calibration needs at least two samples")
        if self.bulk_shift_ms != 0.0 and not math.isfinite(self.bulk_shift_ms):
            raise CalibrationBuildError("bulk shift must be finite")


@dataclass
class TdCalibrationSaveResult:
    well_name: str
    version_id: str
    run_id: str
    asset_id: str
    fingerprint: str
    verified: bool
    pair_count: int
    artifact_path: str


# ---------------------------------------------------------------------------
# Pair building (bulk shift + bounded stretch/squeeze + validation)
# ---------------------------------------------------------------------------


def build_calibration_pairs(
    depths_m: np.ndarray,
    twt_ms: np.ndarray,
    *,
    bulk_shift_ms: float = 0.0,
    stretch: StretchSqueezeRecord | None = None,
) -> list[tuple[float, float]]:
    """Reviewed tie arrays → cleaned (MD m, TWT ms) pairs. Fail-closed.

    Applies the reviewed bulk shift, then the bounded piecewise warp, then
    validates strict monotonicity on BOTH axes. Anything ambiguous (duplicate
    depths, non-increasing time after warping) raises instead of producing a
    silently reordered or clamped calibration.
    """
    depths = np.asarray(depths_m, dtype=np.float64)
    twt = np.asarray(twt_ms, dtype=np.float64) + float(bulk_shift_ms)
    if depths.size != twt.size:
        raise CalibrationBuildError("depths and twt arrays must match in size")
    if depths.size < 2:
        raise CalibrationBuildError("a calibration needs at least two samples")

    order = np.argsort(depths, kind="stable")
    depths = depths[order]
    twt = twt[order]
    if np.any(np.diff(depths) <= 0.0):
        raise CalibrationBuildError("duplicate MD values in the tie (cannot calibrate)")

    if stretch is not None:
        twt = _apply_bounded_warp(depths, twt, stretch)

    if np.any(np.diff(twt) <= 0.0):
        raise CalibrationBuildError(
            "TWT not strictly increasing after reviewed corrections"
        )
    if not (np.isfinite(depths).all() and np.isfinite(twt).all()):
        raise CalibrationBuildError("non-finite samples in the tie")
    return [(float(d), float(t)) for d, t in zip(depths, twt)]


def _apply_bounded_warp(
    depths: np.ndarray, twt: np.ndarray, stretch: StretchSqueezeRecord
) -> np.ndarray:
    """Piecewise-linear factor warp over TWT increments (record is pre-validated)."""
    factor = np.interp(
        depths, np.asarray(stretch.anchors_m), np.asarray(stretch.factors)
    )
    out = np.empty_like(twt)
    out[0] = twt[0]
    for i in range(1, depths.size):
        out[i] = out[i - 1] + (twt[i] - twt[i - 1]) * float(factor[i])
    return out


def calibration_fingerprint(pairs: Sequence[tuple[float, float]]) -> str:
    """Scientific fingerprint: canonical pairs only (display state excluded)."""
    payload = json.dumps(
        {"schema": "td-calibration-v1", "pairs": [[f"{md:.6f}", f"{t:.6f}"] for md, t in pairs]},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Artifact (SMI TD-table, parse_td_table-compatible)
# ---------------------------------------------------------------------------


def write_td_table(
    path: Path,
    well_name: str,
    pairs: Sequence[tuple[float, float]],
    tvdss_m: Sequence[float],
    *,
    tvd_m: Sequence[float] | None = None,
    header_lines: Sequence[str] = (),
) -> Path:
    """Write the calibration as an SMI TD table.

    Column order matches ``parse_td_table`` (TIME TVDSS TVD MD, ≥4 columns,
    ``# Well : NAME`` comment); TIME is milliseconds — the same unit the
    parser reads back. ``tvdss_m`` must be computed honestly by the caller
    (hub trajectory/KB); ``tvd_m`` is optional and, when omitted, the TVD
    column carries the MD values with an explicit header note (no deviation
    survey ⇒ TVD==MD), never an invented trajectory.
    """
    tvdss = np.asarray(tvdss_m, dtype=np.float64)
    if tvdss.size != len(pairs):
        raise CalibrationBuildError("tvdss array must match the pairs length")
    if tvd_m is None:
        tvd = np.asarray([md for md, _ in pairs], dtype=np.float64)
        tvd_note = "# TVD column carries MD (no deviation survey applied)"
    else:
        tvd = np.asarray(tvd_m, dtype=np.float64)
        tvd_note = ""
        if tvd.size != len(pairs):
            raise CalibrationBuildError("tvd array must match the pairs length")
    lines = [f"# Well : {well_name}"]
    if tvd_note:
        lines.append(tvd_note)
    lines.extend(f"# {line}" for line in header_lines)
    lines.append("# TIME(ms) TVDSS(m) TVD(m) MD(m)")
    # 6 decimals match the scientific fingerprint's pair precision, so a
    # fingerprint recomputed from the artifact equals the stored one.
    for (md, twt), z, d in zip(pairs, tvdss, tvd):
        lines.append(f"{twt:16.6f} {z:14.6f} {d:14.6f} {md:14.6f}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def tvdss_from_hub(hub, well_id: str, mds: Sequence[float]) -> list[float]:
    """Honest TVDSS per MD through the hub (trajectory + KB), fail-closed."""
    out: list[float] = []
    for md in mds:
        out.append(float(hub.well_depth_to_tvdss(well_id, float(md))))
    return out


def hub_calibration_from_td_table(
    path: Path,
    well_name: str,
    *,
    version_id: str | None = None,
    fingerprint: str | None = None,
    metadata: dict[str, Any] | None = None,
):
    """TD-table artifact → hub :class:`TimeDepthCalibration` (identity attached).

    Parses through the SAME production parser (``parse_td_table``) the
    project-open path uses, so what was saved is exactly what reopens.
    """
    from paleo_workbench.viz.coordinate_hub import TimeDepthCalibration
    from paleo_workbench.viz.joint_well_parsers import parse_td_table

    table = parse_td_table(Path(path), well_name=well_name)
    if table is None:
        raise CalibrationBuildError(f"TD table {path} is not parseable")
    pairs = list(zip(table.md_m, table.time_ms))
    return TimeDepthCalibration.from_pairs(
        str(well_name),
        pairs,
        provenance=f"td-table:{Path(path).name}",
        version_id=version_id,
        fingerprint=fingerprint,
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# Save: catalog version + run + project link
# ---------------------------------------------------------------------------


def save_reviewed_calibration(
    service: DataCatalogService,
    project,
    review: TieReviewData,
    *,
    tvdss_m: Sequence[float],
    parent_version_ids: Sequence[str] = (),
) -> TdCalibrationSaveResult:
    """Persist a reviewed tie as the well's versioned calibration authority.

    * builds/validates the pairs (fail-closed),
    * writes the TD-table artifact and registers ONE catalog DERIVED version
      with a DataRun carrying the full quality provenance (correlation, bulk
      shift, wavelet, reviewer, verified flag, stretch record),
    * upserts the project's ``entity_asset_link(role=time_depth)`` (new link
      becomes primary; previous primary links of the same role are demoted,
      not deleted — history stays queryable).

    ``verified`` in the run parameters is computed, never trusted: it is
    True only when the recorded correlation passes
    :data:`QC_CORRELATION_THRESHOLD` AND the reviewer explicitly confirmed.
    """
    pairs = build_calibration_pairs(
        review.depths_m,
        review.twt_ms,
        bulk_shift_ms=review.bulk_shift_ms,
        stretch=review.stretch,
    )
    fingerprint = calibration_fingerprint(pairs)
    correlation = (
        float(review.correlation)
        if review.correlation is not None and math.isfinite(review.correlation)
        else None
    )
    verified = bool(
        correlation is not None
        and correlation >= QC_CORRELATION_THRESHOLD
        and review.reviewer_confirmed
        and str(review.reviewer).strip()
    )

    with tempfile.NamedTemporaryFile(
        "w", suffix=".dat", delete=False, encoding="utf-8"
    ) as handle:
        staged = Path(handle.name)
    try:
        write_td_table(
            staged,
            review.well_name,
            pairs,
            tvdss_m,
            header_lines=(
                f"provenance: {review.method} / {review.wavelet}",
                f"bulk_shift_ms: {review.bulk_shift_ms:g}",
                f"correlation: {correlation if correlation is not None else 'n/a'}",
                f"reviewer: {review.reviewer or 'unreviewed'}",
                f"verified: {verified}",
                f"fingerprint: {fingerprint}",
            ),
        )
        derived = service.create_derived(
            staged,
            parent_version_ids=list(parent_version_ids),
            name=f"{review.well_name} TD calibration",
            operation="time_depth_calibration",
            parameters={
                "well_name": review.well_name,
                "well_entity_id": review.well_entity_id,
                "method": review.method,
                "wavelet": review.wavelet,
                "bulk_shift_ms": float(review.bulk_shift_ms),
                "correlation": correlation,
                "qc_threshold": QC_CORRELATION_THRESHOLD,
                "reviewer": str(review.reviewer or ""),
                "reviewer_confirmed": bool(review.reviewer_confirmed),
                "verified": verified,
                "stretch_squeeze": (
                    review.stretch.as_dict() if review.stretch is not None else None
                ),
                "pair_count": len(pairs),
                "fingerprint": fingerprint,
            },
            generator=GENERATOR_ID,
            type="time_depth",
            format="dat",
            input_ports=[
                {
                    "role": "checkshot",
                    "version_id": parent_version_ids[0],
                    "entity_type": "well",
                    "entity_id": review.well_entity_id,
                }
            ]
            if parent_version_ids
            else None,
            output_port_role="calibrated_td",
            metadata={
                "fingerprint": fingerprint,
                "verified": verified,
                "well_name": review.well_name,
                "pair_count": len(pairs),
            },
        )
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass

    _upsert_time_depth_link(project, review.well_entity_id, derived.asset_id)

    run_id = str(getattr(derived, "run_id", "") or "")
    if not run_id:
        for run in service.document.runs:
            if derived.id in (run.output_version_ids or ()):
                run_id = run.id
                break
    try:
        artifact_path = str(service.resolve_path(derived))
    except Exception:
        artifact_path = str(derived.path)
    return TdCalibrationSaveResult(
        well_name=review.well_name,
        version_id=derived.id,
        run_id=run_id,
        asset_id=str(derived.asset_id),
        fingerprint=fingerprint,
        verified=verified,
        pair_count=len(pairs),
        artifact_path=artifact_path,
    )


def _upsert_time_depth_link(project, well_entity_id: str, asset_id: str) -> None:
    # Single write path for entity↔asset links (review R2-M1): the domain
    # upsert is idempotent and demotes sibling primaries of the same role.
    from paleo_workbench.project.domain import upsert_entity_asset_link

    upsert_entity_asset_link(
        project,
        entity_type="well",
        entity_id=str(well_entity_id),
        asset_id=str(asset_id),
        role="time_depth",
        is_primary=True,
        note="well-seismic tie calibration",
    )
