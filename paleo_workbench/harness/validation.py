"""Result verification hooks (P2-C).

Two independent gates run at the end of guarded actions:

- :class:`ScientificValidator` — grid/array outputs must not be silently
  degenerate (all-NaN, empty extent, unitless mismatch, flipped ranges);
- :class:`MapValidationHook` — a map an agent claims is "done" must actually
  be exportable (visible non-empty layers, sane extent/CRS, legend/colorbar/
  scale/north-arrow/title bindings per the composition).

Both return a :class:`ValidationReport` with PASS / WARNING / FAIL and
concrete reasons; a FAIL blocks success claims (the executor marks the
action failed), a WARNING is surfaced but does not block.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PASS = "pass"
WARNING = "warning"
FAIL = "fail"


@dataclass(slots=True)
class ValidationReport:
    verdict: str = PASS
    reasons: list[str] = field(default_factory=list)

    def add(self, verdict: str, reason: str) -> None:
        self.reasons.append(reason)
        if verdict == FAIL or (verdict == WARNING and self.verdict == PASS):
            self.verdict = verdict

    @property
    def passed(self) -> bool:
        return self.verdict != FAIL

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "reasons": list(self.reasons)}


class ScientificValidator:
    """Sanity checks for numeric (grid/array) action outputs."""

    max_nan_ratio = 0.9  # above this the output is effectively empty
    min_finite_values = 4

    def validate_grid(self, grid: Any, *, label: str = "grid", expected_shape: tuple[int, ...] | None = None,
                      unit: str | None = None, crs: str | None = None,
                      extent: tuple[float, ...] | None = None) -> ValidationReport:
        report = ValidationReport()
        array = getattr(grid, "grid_z", None)
        if array is None:
            array = grid
        try:
            import numpy as np

            if not isinstance(array, np.ndarray):
                report.add(FAIL, f"{label}: output is not an array ({type(array).__name__})")
                return report
            if array.size == 0:
                report.add(FAIL, f"{label}: empty array")
                return report
            if expected_shape is not None and tuple(array.shape) != tuple(expected_shape):
                report.add(FAIL, f"{label}: shape {array.shape} != expected {expected_shape}")
            finite = np.isfinite(array)
            finite_ratio = float(finite.sum()) / float(array.size)
            if finite_ratio == 0.0:
                report.add(FAIL, f"{label}: all values are NaN/nodata — computation produced nothing")
            elif finite_ratio < (1.0 - self.max_nan_ratio):
                report.add(WARNING, f"{label}: {1 - finite_ratio:.1%} NaN/nodata (coverage thin)")
            elif int(finite.sum()) < self.min_finite_values:
                report.add(WARNING, f"{label}: only {int(finite.sum())} finite values")
            if finite.any():
                vmin, vmax = float(array[finite].min()), float(array[finite].max())
                if vmax < vmin:
                    report.add(FAIL, f"{label}: inverted value range")
                if vmin == vmax:
                    report.add(WARNING, f"{label}: constant value {vmin} (degenerate field)")
        except Exception as exc:  # validation must never crash the action
            report.add(WARNING, f"{label}: validation error {type(exc).__name__}: {exc}")
        # Axis/CRS/unit metadata checks when the object carries them.
        try:
            import numpy as np
        except Exception:  # pragma: no cover
            np = None  # type: ignore
        for axis in ("grid_x", "grid_y"):
            axis_values = getattr(grid, axis, None)
            if axis_values is not None and len(axis_values) > 1 and np is not None:
                values = np.asarray(axis_values, dtype=float)
                lo, hi = float(values[0]), float(values[-1])
                if not bool(np.all(np.diff(values) > 0)):
                    report.add(FAIL, f"{label}.{axis}: non-ascending axis [{lo}, {hi}]")
                if extent is not None and len(extent) >= 4:
                    x0, y0, x1, y1 = (float(v) for v in extent[:4])
                    if axis == "grid_x" and not (x0 <= lo and hi <= x1):
                        report.add(FAIL, f"{label}: grid x-axis [{lo}, {hi}] outside extent [{x0}, {x1}]")
                    if axis == "grid_y" and not (y0 <= lo and hi <= y1):
                        report.add(FAIL, f"{label}: grid y-axis [{lo}, {hi}] outside extent [{y0}, {y1}]")
        declared_crs = getattr(grid, "crs", None)
        if crs is not None and declared_crs is not None and str(crs) != str(declared_crs):
            report.add(FAIL, f"{label}: CRS mismatch ({declared_crs} != {crs})")
        declared_unit = getattr(grid, "unit", None)
        if unit is not None and declared_unit is not None and str(unit) != str(declared_unit):
            report.add(WARNING, f"{label}: unit mismatch ({declared_unit} != {unit})")
        if getattr(grid, "algorithm_id", None) is None and hasattr(grid, "grid_z"):
            report.add(WARNING, f"{label}: missing algorithm provenance")
        return report

    def validate_array(self, array: Any, *, label: str = "array") -> ValidationReport:
        return self.validate_grid(array, label=label)


class MapValidationHook:
    """Export-readiness gate for map documents and their compositions."""

    def validate(self, document: Any, composition: Any | None = None, *,
                 require_components: bool = False) -> ValidationReport:
        report = ValidationReport()
        layers = list(getattr(document, "layers", []) or [])
        if not layers:
            report.add(FAIL, "map: no layers")
            return report
        visible = [layer for layer in layers if getattr(layer, "visible", True)]
        if not visible:
            report.add(FAIL, "map: all layers hidden")
        empty = [getattr(layer, "name", layer.id) for layer in visible if self._layer_is_empty(layer)]
        if empty:
            report.add(FAIL, f"map: empty visible layers {empty}")
        extent = getattr(document, "extent", None)
        if not extent or not all(self._finite(v) for v in extent):
            report.add(FAIL, f"map: invalid extent {extent!r}")
        else:
            x0, y0, x1, y1 = (float(v) for v in extent[:4])
            if x1 <= x0 or y1 <= y0:
                report.add(FAIL, f"map: inverted extent [{x0}, {y0}, {x1}, {y1}]")
        crs = getattr(document, "crs", None)
        if not crs:
            report.add(WARNING, "map: no declared CRS")
        grid_layers = [layer for layer in visible if getattr(layer, "layer_type", "") == "grid"]
        if grid_layers and not any(self._grid_ramp(layer) for layer in grid_layers):
            report.add(WARNING, "map: grid layers without color ramp (colorbar unreadable)")
        if composition is not None:
            self._validate_composition(composition, report, require=require_components)
        elif require_components:
            report.add(FAIL, "map: no composition attached (legend/scale/north arrow missing)")
        return report

    # ------------------------------------------------------------- helpers --
    @staticmethod
    def _finite(value: Any) -> bool:
        try:
            import math

            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _layer_is_empty(layer: Any) -> bool:
        layer_type = getattr(layer, "layer_type", "")
        features = getattr(layer, "features", None)
        if features is not None:
            return len(features) == 0
        if layer_type == "grid":
            grid = getattr(layer, "grid_result", None)
            array = getattr(grid, "grid_z", None) if grid is not None else None
            if array is None:
                return True
            import numpy as np

            return not bool(np.isfinite(array).any())
        return False

    @staticmethod
    def _grid_ramp(layer: Any) -> Any:
        """Grid layers carry their ramp in ``color_ramp_name`` / style."""
        return (
            getattr(layer, "color_ramp_name", None)
            or (getattr(layer, "style", None) or {}).get("color_ramp")
            or getattr(layer, "raster_ramp", None)
        )

    def _validate_composition(self, composition: Any, report: ValidationReport, *, require: bool) -> None:
        elements = list(getattr(composition, "elements", []) or [])
        present = {str(getattr(e, "element_type", getattr(e, "element_type", ""))).split(".")[-1].lower(): e for e in elements}
        needed = {
            "legend": "legend binding",
            "scale_bar": "scale bar",
            "north_arrow": "north arrow",
            "title": "title",
        }
        missing = [label for key, label in needed.items() if key not in present]
        if missing:
            verdict = FAIL if require else WARNING
            report.add(verdict, f"composition: missing {missing}")
        if "main_map" not in present:
            report.add(FAIL, "composition: no main map frame element")
        hidden = [
            getattr(e, "id", "?")
            for e in elements
            if getattr(e, "visible", True) is False
        ]
        if hidden:
            report.add(WARNING, f"composition: hidden elements {hidden}")
        title = getattr(composition, "title", "")
        if not (title or "").strip():
            report.add(WARNING, "composition: untitled map")
