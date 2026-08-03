"""Optional WellLogEngine (welllog) bridge for the workstation host (#224/#225).

Host MultiTrackCanvas remains the default multi-track path. When the ``welllog``
Shiboken package is importable, the shell can embed ``WellLogView`` and submit:

- multi-track presentation via ``submit_multi_track`` (#225)
- multi-well shared-depth section via ``submit_multi_well_section`` (#225)
- single-curve fallback via ``submit_curve`` (#224)

Missing engine never crashes the host.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np

from well_log_workstation.las_import import ImportedWellDocument
from well_log_workstation.template_model import HostPresentation
from well_log_workstation.tops_model import FormationTop


class EngineUnavailable(Exception):
    """welllog package / WellLogView not available."""


class EngineSubmitError(Exception):
    """submit_curve or related engine call failed."""


@dataclass(frozen=True)
class EngineCapability:
    available: bool
    detail: str
    well_log_view_cls: type | None = None


_cached: EngineCapability | None = None


def reset_engine_capability_cache() -> None:
    global _cached
    _cached = None


def probe_engine() -> EngineCapability:
    """Detect welllog without raising. Result is cached until reset."""
    global _cached
    if _cached is not None:
        return _cached

    # Allow forced disable for tests / CI
    if os.environ.get("WLWS_DISABLE_ENGINE", "").strip() in ("1", "true", "yes"):
        _cached = EngineCapability(False, "WLWS_DISABLE_ENGINE set")
        return _cached

    try:
        from welllog import WellLogView  # type: ignore

        _cached = EngineCapability(True, "welllog.WellLogView", WellLogView)
        return _cached
    except Exception as exc_pkg:  # noqa: BLE001
        pkg_err = str(exc_pkg)

    # Fallback: load extension without package __init__ (e.g. missing TableModel)
    try:
        import importlib
        import importlib.util

        # Prefer already-loaded module, else import welllog._QtWidgets carefully
        try:
            ext = importlib.import_module("welllog._QtWidgets")
        except Exception:
            # Last resort: find shared library on sys.path
            import sys
            from pathlib import Path

            ext = None
            for entry in sys.path:
                for name in ("_QtWidgets.abi3.so", "_QtWidgets.so"):
                    candidate = Path(entry) / "welllog" / name
                    if candidate.is_file():
                        spec = importlib.util.spec_from_file_location(
                            "welllog._QtWidgets", candidate
                        )
                        if spec and spec.loader:
                            ext = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(ext)
                            break
                if ext is not None:
                    break
            if ext is None:
                raise ImportError(pkg_err)

        view_cls = getattr(getattr(ext, "welllog", None), "WellLogView", None)
        if view_cls is None:
            _cached = EngineCapability(
                False, f"welllog._QtWidgets has no WellLogView ({pkg_err})"
            )
            return _cached
        _cached = EngineCapability(
            True, f"welllog._QtWidgets.WellLogView ({pkg_err})", view_cls
        )
        return _cached
    except Exception as exc_ext:  # noqa: BLE001
        _cached = EngineCapability(
            False, f"welllog unavailable: {pkg_err}; {exc_ext}"
        )
        return _cached


def engine_available() -> bool:
    return probe_engine().available


def create_well_log_view(parent=None) -> Any:
    """Instantiate native WellLogView or raise EngineUnavailable."""
    cap = probe_engine()
    if not cap.available or cap.well_log_view_cls is None:
        raise EngineUnavailable(cap.detail)
    return cap.well_log_view_cls(parent)


def _readonly_f64(arr: np.ndarray) -> np.ndarray:
    out = np.ascontiguousarray(arr, dtype=np.float64)
    if not out.flags.writeable:
        return out
    # Copy then freeze — submit_curve rejects writable buffers
    frozen = np.array(out, dtype=np.float64, copy=True)
    frozen.setflags(write=False)
    return frozen


def primary_curve_from_presentation(
    presentation: HostPresentation,
) -> tuple[np.ndarray, np.ndarray, str, str] | None:
    """Return (depth, values, mnemonic, value_unit) for first bound curve layer."""
    depth = _readonly_f64(np.asarray(presentation.depth, dtype=np.float64))
    for track in presentation.tracks:
        if track.role != "curve" or not track.layers:
            continue
        layer = track.layers[0]
        vals = np.asarray(layer.values, dtype=np.float64).copy()
        nulls = np.asarray(layer.null_mask, dtype=bool)
        if nulls.size == vals.size:
            vals[nulls] = np.nan
        # Engine may not accept NaN — replace with 0 for display path only
        vals = np.nan_to_num(vals, nan=0.0)
        values = _readonly_f64(vals)
        n = min(depth.size, values.size)
        if n < 2:
            return None
        return depth[:n], values[:n], layer.mnemonic, layer.unit or "unit"
    return None


def primary_curve_from_document(
    document: ImportedWellDocument,
) -> tuple[np.ndarray, np.ndarray, str, str] | None:
    depth = _readonly_f64(np.asarray(document.depth, dtype=np.float64))
    if not document.curves:
        return None
    curve = document.curves[0]
    vals = np.asarray(curve.values, dtype=np.float64).copy()
    nulls = np.asarray(curve.null_mask, dtype=bool)
    if nulls.size == vals.size:
        vals[nulls] = np.nan
    vals = np.nan_to_num(vals, nan=0.0)
    values = _readonly_f64(vals)
    n = min(depth.size, values.size)
    if n < 2:
        return None
    return depth[:n], values[:n], curve.mnemonic, curve.unit or "unit"


def submit_primary_curve(
    view: Any,
    *,
    depth: np.ndarray,
    values: np.ndarray,
    mnemonic: str,
    depth_unit: str,
    value_unit: str,
    document_id: str | None = None,
) -> dict[str, object]:
    """Call WellLogView.submit_curve with UUID entity ids."""
    doc_id = document_id or str(uuid.uuid4())
    # EntityId parse requires non-nil UUID strings
    try:
        uuid.UUID(doc_id)
    except ValueError:
        doc_id = str(uuid.uuid4())
    axis_id = str(uuid.uuid4())
    curve_id = str(uuid.uuid4())
    depth_r = _readonly_f64(depth)
    values_r = _readonly_f64(values)
    if depth_r.size != values_r.size:
        raise EngineSubmitError("depth and values length mismatch")
    try:
        report = view.submit_curve(
            depth_r,
            values_r,
            doc_id,
            axis_id,
            curve_id,
            mnemonic,
            depth_unit or "m",
            value_unit or "unit",
        )
    except Exception as exc:  # noqa: BLE001
        raise EngineSubmitError(str(exc)) from exc
    if not isinstance(report, dict):
        return {"raw": report, "curve_id": curve_id}
    out = dict(report)
    out.setdefault("curve_id", curve_id)
    out.setdefault("document_id", doc_id)
    return out  # type: ignore[return-value]


def load_presentation_into_view(
    view: Any,
    presentation: HostPresentation,
    *,
    tops: list[FormationTop] | None = None,
) -> dict[str, object]:
    """Submit multi-track presentation; fall back to single-curve if needed."""
    if hasattr(view, "submit_multi_track"):
        try:
            return submit_multi_track_presentation(view, presentation, tops=tops)
        except EngineSubmitError:
            # Older builds or empty track map — try single curve
            pass
    primary = primary_curve_from_presentation(presentation)
    if primary is None:
        raise EngineSubmitError("图版未绑定可提交的曲线")
    depth, values, mnemonic, value_unit = primary
    doc_id = presentation.well_document_id
    return submit_primary_curve(
        view,
        depth=depth,
        values=values,
        mnemonic=mnemonic,
        depth_unit=presentation.depth_unit or "m",
        value_unit=value_unit,
        document_id=doc_id if _is_uuid(doc_id) else None,
    )


def presentation_to_multi_track_payload(
    presentation: HostPresentation,
    *,
    tops: list[FormationTop] | None = None,
) -> dict[str, Any]:
    """Build ``submit_multi_track`` payload from a host multi-track presentation."""
    depth = _readonly_f64(np.asarray(presentation.depth, dtype=np.float64))
    if depth.size < 2:
        raise EngineSubmitError("深度样本不足")

    doc_id = presentation.well_document_id
    if not _is_uuid(doc_id):
        doc_id = str(uuid.uuid4())

    # Collect unique curve layers → curves list + map mnemonic→curve_id
    curves: list[dict[str, Any]] = []
    curve_ids: dict[str, str] = {}  # mnemonic upper -> curve_id
    n = depth.size

    for track in presentation.tracks:
        if track.role != "curve":
            continue
        for layer in track.layers:
            key = layer.mnemonic.upper()
            if key in curve_ids:
                continue
            vals = np.asarray(layer.values, dtype=np.float64).copy()
            nulls = np.asarray(layer.null_mask, dtype=bool)
            if nulls.size == vals.size:
                vals[nulls] = np.nan
            vals = np.nan_to_num(vals, nan=0.0)
            values = _readonly_f64(vals)
            m = min(n, values.size)
            if m < 2:
                continue
            cid = str(uuid.uuid4())
            curve_ids[key] = cid
            curves.append(
                {
                    "curve_id": cid,
                    "mnemonic": layer.mnemonic,
                    "values": values[:m],
                    "value_unit": layer.unit or "unit",
                }
            )

    if not curves:
        raise EngineSubmitError("图版未绑定可提交的曲线")

    # Align depth to first curve length
    first_len = int(curves[0]["values"].size)  # type: ignore[union-attr]
    depth = depth[:first_len]

    tracks_payload: list[dict[str, Any]] = []
    for track in presentation.tracks:
        if track.role != "curve" or not track.layers:
            continue
        layers_out: list[dict[str, Any]] = []
        for layer in track.layers:
            cid = curve_ids.get(layer.mnemonic.upper())
            if not cid:
                continue
            layers_out.append({"curve_id": cid, "color": layer.color or "#1972b8"})
        if not layers_out:
            continue
        width_mm = max(20.0, float(track.width_fraction) * 120.0)
        entry: dict[str, Any] = {
            "width_mm": width_mm,
            "layers": layers_out,
        }
        if track.scale is not None:
            entry["scale_min"] = float(track.scale.min)
            entry["scale_max"] = float(track.scale.max)
            entry["scale_mode"] = (
                "log" if track.scale.mode == "log" else "linear"
            )
        tracks_payload.append(entry)

    if not tracks_payload:
        raise EngineSubmitError("无曲线道可提交")

    payload: dict[str, Any] = {
        "document_id": doc_id,
        "depth": depth,
        "depth_unit": presentation.depth_unit or "m",
        "curves": curves,
        "tracks": tracks_payload,
    }
    if tops:
        markers = []
        for t in tops:
            mid = t.id if t.id and _is_uuid(t.id) else str(uuid.uuid4())
            markers.append(
                {"id": mid, "depth": float(t.depth), "label": t.name}
            )
        if markers:
            payload["markers"] = markers
    return payload


def submit_multi_track_presentation(
    view: Any,
    presentation: HostPresentation,
    *,
    tops: list[FormationTop] | None = None,
) -> dict[str, object]:
    """Call WellLogView.submit_multi_track with a host presentation."""
    if not hasattr(view, "submit_multi_track"):
        raise EngineSubmitError("WellLogView 不支持 submit_multi_track（请重建 welllog 绑定）")
    payload = presentation_to_multi_track_payload(presentation, tops=tops)
    try:
        report = view.submit_multi_track(payload)
    except Exception as exc:  # noqa: BLE001
        raise EngineSubmitError(str(exc)) from exc
    if not isinstance(report, dict):
        return {"raw": report}
    return dict(report)


def presentations_to_multi_well_payload(
    presentations: list[HostPresentation],
    *,
    tops_per_well: list[list[FormationTop]] | None = None,
    gap_mm: float = 5.0,
    shared_depth: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Build ``submit_multi_well_section`` payload (primary curve per well)."""
    if len(presentations) < 1:
        raise EngineSubmitError("至少需要一口井")
    wells: list[dict[str, Any]] = []
    d0_global: float | None = None
    d1_global: float | None = None

    for i, pres in enumerate(presentations):
        primary = primary_curve_from_presentation(pres)
        if primary is None:
            raise EngineSubmitError(f"井 {pres.well_name} 无绑定曲线")
        depth, values, mnemonic, value_unit = primary
        dmin, dmax = float(np.nanmin(depth)), float(np.nanmax(depth))
        d0_global = dmin if d0_global is None else min(d0_global, dmin)
        d1_global = dmax if d1_global is None else max(d1_global, dmax)
        doc_id = (
            pres.well_document_id
            if _is_uuid(pres.well_document_id)
            else str(uuid.uuid4())
        )
        well: dict[str, Any] = {
            "document_id": doc_id,
            "axis_id": str(uuid.uuid4()),
            "curve_id": str(uuid.uuid4()),
            "mnemonic": mnemonic,
            "depth_unit": pres.depth_unit or "m",
            "value_unit": value_unit or "unit",
            "depth": depth,
            "values": values,
            "width_mm": 35.0,
        }
        if tops_per_well is not None and i < len(tops_per_well):
            markers = []
            for t in tops_per_well[i]:
                mid = t.id if t.id and _is_uuid(t.id) else str(uuid.uuid4())
                markers.append(
                    {"id": mid, "depth": float(t.depth), "label": t.name}
                )
            if markers:
                well["markers"] = markers
        wells.append(well)

    if shared_depth is not None:
        shared_top, shared_bottom = shared_depth
    else:
        shared_top = d0_global if d0_global is not None else 0.0
        shared_bottom = d1_global if d1_global is not None else 1.0
    if not (shared_bottom > shared_top):
        shared_bottom = shared_top + 1.0

    return {
        "gap_mm": float(gap_mm),
        "shared_top": float(shared_top),
        "shared_bottom": float(shared_bottom),
        "wells": wells,
    }


def submit_multi_well_presentations(
    view: Any,
    presentations: list[HostPresentation],
    *,
    tops_per_well: list[list[FormationTop]] | None = None,
    gap_mm: float = 5.0,
    shared_depth: tuple[float, float] | None = None,
) -> dict[str, object]:
    """Call WellLogView.submit_multi_well_section for correlation-lite."""
    if not hasattr(view, "submit_multi_well_section"):
        raise EngineSubmitError(
            "WellLogView 不支持 submit_multi_well_section（请重建 welllog 绑定）"
        )
    payload = presentations_to_multi_well_payload(
        presentations,
        tops_per_well=tops_per_well,
        gap_mm=gap_mm,
        shared_depth=shared_depth,
    )
    try:
        report = view.submit_multi_well_section(payload)
    except Exception as exc:  # noqa: BLE001
        raise EngineSubmitError(str(exc)) from exc
    if not isinstance(report, dict):
        return {"raw": report}
    return dict(report)


def clear_multi_well(view: Any) -> None:
    if hasattr(view, "clear_multi_well_section"):
        try:
            view.clear_multi_well_section()
        except Exception:  # noqa: BLE001
            pass


def _is_uuid(text: str) -> bool:
    try:
        uuid.UUID(text)
        return True
    except (ValueError, TypeError, AttributeError):
        return False
