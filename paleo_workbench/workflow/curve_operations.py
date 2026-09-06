"""Well curve processing kernels for the interpretation toolbox (L3).

Pure, catalog-free numeric kernels + a controlled derived-curve expression
evaluator. Every function is NaN-aware: missing samples ride along as NaN and
never silently become zeros. Units are explicit — :data:`UNIT_CONVERSIONS`
whitelists the supported (from, to) pairs with exact factors; unknown pairs
raise instead of guessing. The expression evaluator parses a restricted AST
(arithmetic on curve names + whitelisted numpy-style calls) and never calls
:func:`eval`.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

FT_TO_M = 0.3048


# ---------------------------------------------------------------------------
# Smoothing / filtering
# ---------------------------------------------------------------------------


def moving_average(values: np.ndarray, window: int = 5) -> np.ndarray:
    """Centered moving average over *window* samples (NaN-aware).

    Window counts are samples, not metres — callers translate their depth
    spacing into a sample count before calling. A window position averages
    only the finite samples inside it, and a NaN position STAYS NaN: gaps
    must not be silently filled with a neighbourhood average (that would
    fabricate measurements across missing intervals).
    """
    arr = np.asarray(values, dtype=float)
    n = arr.size
    if n == 0:
        return arr.copy()
    # A window wider than the curve averages the whole curve (convolution
    # 'same' would otherwise return a LONGER array than the input).
    w = min(max(1, int(window)), n)
    if w == 1:
        return arr.copy()
    finite = np.isfinite(arr)
    if not finite.any():
        return arr.copy()
    filled = np.where(finite, arr, 0.0)
    kernel = np.ones(w, dtype=float)
    sums = np.convolve(filled, kernel, mode="same")
    counts = np.convolve(finite.astype(float), kernel, mode="same")
    out = np.full(n, np.nan)
    ok = counts > 0
    out[ok] = sums[ok] / counts[ok]
    out[~finite] = np.nan
    return out


def median_filter_curve(values: np.ndarray, window: int = 5) -> np.ndarray:
    """Rolling median over *window* samples (odd, NaN positions preserved)."""
    arr = np.asarray(values, dtype=float)
    finite = np.isfinite(arr)
    if arr.size == 0 or not finite.any():
        return arr.copy()
    from scipy.ndimage import median_filter

    w = max(1, int(window) | 1)
    filled = np.where(finite, arr, float(np.median(arr[finite])))
    out = median_filter(filled, size=w, mode="reflect")
    out[~finite] = np.nan
    return out


# ---------------------------------------------------------------------------
# Normalization / outlier handling
# ---------------------------------------------------------------------------


def normalize_curve(values: np.ndarray, method: str = "zscore") -> np.ndarray:
    """Normalize the finite samples to z-scores or the [0, 1] range.

    Statistics come from the curve's OWN finite samples (per-curve
    normalization); nothing is inferred about the population. Degenerate
    spread (constant curve) returns zeros for zscore and 0.5 for minmax so
    the operation stays total without inventing variation.
    """
    arr = np.asarray(values, dtype=float)
    finite = np.isfinite(arr)
    out = np.full(arr.shape, np.nan)
    if not finite.any():
        return out
    data = arr[finite]
    if method == "zscore":
        mean = float(np.mean(data))
        std = float(np.std(data))
        out[finite] = (data - mean) / (std if std > 1e-12 else 1.0)
    elif method == "minmax":
        lo, hi = float(np.min(data)), float(np.max(data))
        span = hi - lo
        out[finite] = 0.5 if span <= 1e-12 else (data - lo) / span
    else:
        raise ValueError(f"unknown normalization method {method!r} (zscore|minmax)")
    return out


def clip_outliers(
    values: np.ndarray,
    lower: float | None = None,
    upper: float | None = None,
    percentile: float | None = None,
) -> np.ndarray:
    """Clip finite samples to explicit bounds or a symmetric percentile band.

    ``percentile`` p (0 < p < 50) clips to [p, 100-p] computed from the
    curve's own finite samples. NaN survives untouched. When nothing to clip
    is requested the kernel raises — a no-op clip is a caller bug.
    """
    arr = np.asarray(values, dtype=float)
    finite = np.isfinite(arr)
    if not finite.any():
        return arr.copy()
    lo, hi = lower, upper
    if percentile is not None:
        p = float(percentile)
        if not 0.0 < p < 50.0:
            raise ValueError(f"percentile must be in (0, 50), got {p}")
        lo = float(np.percentile(arr[finite], p))
        hi = float(np.percentile(arr[finite], 100.0 - p))
    if lo is None and hi is None:
        raise ValueError("clip_outliers needs lower/upper bounds or a percentile")
    out = arr.copy()
    if lo is not None:
        out[finite] = np.maximum(out[finite], float(lo))
    if hi is not None:
        out[finite] = np.minimum(out[finite], float(hi))
    return out


# ---------------------------------------------------------------------------
# Unit conversion (explicit whitelist — never a guessed factor)
# ---------------------------------------------------------------------------

_UNIT_ALIASES = {
    "m": "m", "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "ft": "ft", "feet": "ft", "foot": "ft", "f": "ft",  # LAS depth unit "F"
    "g/cc": "g/cc", "g/cm3": "g/cc", "g/cm³": "g/cc", "gm/cc": "g/cc",
    "kg/m3": "kg/m3", "kg/m³": "kg/m3",
    "us/m": "us/m", "µs/m": "us/m", "us/ft": "us/ft", "µs/ft": "us/ft",
    "mm": "mm", "in": "in", "inch": "in", "inches": "in",
    "mv": "mv", "millivolt": "mv", "v": "v", "volt": "v",
    "ohmm": "ohmm", "ohm.m": "ohmm", "ohmm.m": "ohmm", "ohm-m": "ohmm",
    "%": "percent", "pct": "percent", "v/v": "v/v",
    "api": "api",
}

# (from, to) -> multiplicative factor applied to VALUES.
UNIT_CONVERSIONS: dict[tuple[str, str], float] = {
    ("m", "ft"): 1.0 / FT_TO_M,
    ("ft", "m"): FT_TO_M,
    ("g/cc", "kg/m3"): 1000.0,
    ("kg/m3", "g/cc"): 0.001,
    ("us/m", "us/ft"): FT_TO_M,
    ("us/ft", "us/m"): 1.0 / FT_TO_M,
    ("mm", "in"): 1.0 / 25.4,
    ("in", "mm"): 25.4,
    ("mv", "v"): 0.001,
    ("v", "mv"): 1000.0,
    ("percent", "v/v"): 0.01,
    ("v/v", "percent"): 100.0,
}


def normalize_unit_name(unit: str | None) -> str | None:
    """Canonical unit key for a LAS header unit string (None if unmatched)."""
    if unit is None:
        return None
    return _UNIT_ALIASES.get(str(unit).strip().lower())


def conversion_factor(from_unit: str, to_unit: str) -> float:
    """Exact factor for a whitelisted (from, to) pair; raises otherwise.

    An identity pair (same canonical unit) returns 1.0 — useful for depth
    normalization requests that are already satisfied.
    """
    src = normalize_unit_name(from_unit)
    dst = normalize_unit_name(to_unit)
    if src is None or dst is None:
        raise ValueError(
            f"unrecognized unit ({from_unit!r} -> {to_unit!r}); "
            f"supported: {sorted(set(_UNIT_ALIASES))}"
        )
    if src == dst:
        return 1.0
    factor = UNIT_CONVERSIONS.get((src, dst))
    if factor is None:
        raise ValueError(
            f"no whitelisted conversion {from_unit!r} -> {to_unit!r}; "
            f"supported pairs: {sorted(UNIT_CONVERSIONS)}"
        )
    return factor


def convert_values(values: np.ndarray, from_unit: str, to_unit: str) -> np.ndarray:
    """Convert curve values between whitelisted units (NaN preserved)."""
    factor = conversion_factor(from_unit, to_unit)
    arr = np.asarray(values, dtype=float).copy()
    finite = np.isfinite(arr)
    arr[finite] = arr[finite] * factor
    return arr


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------


def resample_axis(depth: np.ndarray, step: float) -> np.ndarray:
    """New regular depth axis spanning the input range at *step*.

    ``step`` must be positive; the axis starts at the input's first depth and
    never extrapolates past the last (a partial trailing interval is dropped,
    not rounded up).
    """
    arr = np.asarray(depth, dtype=float)
    if arr.size < 2:
        return arr.copy()
    step_val = float(step)
    if not math.isfinite(step_val) or step_val <= 0.0:
        raise ValueError(f"resample step must be positive, got {step_val}")
    if float(arr[-1]) < float(arr[0]):
        raise ValueError(
            "resample needs a non-descending depth axis "
            f"(got {arr[0]} → {arr[-1]}); reverse the axis explicitly first"
        )
    start, stop = float(arr[0]), float(arr[-1])
    count = int(math.floor((stop - start) / step_val + 1e-9)) + 1
    return start + np.arange(count, dtype=float) * step_val


def interp_nan_aware(new_x: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Linear interpolation that keeps NaN holes and range limits honest.

    .. deprecated-semantics:: V6 §4
        This kernel drops NaN samples from the interpolant, so an *interior*
        gap between two finite samples is silently bridged by a linear ramp —
        fabricated measurements across a missing interval. Resampling and
        other scientific paths must use :func:`interp_gap_preserving`;
        ``interp_nan_aware`` remains for display-only continuity.
    """
    new_x = np.asarray(new_x, dtype=float)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    out = np.full(new_x.shape, np.nan)
    if not finite.any():
        return out
    xs, ys = x[finite], y[finite]
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    xs_unique, idx = np.unique(xs, return_index=True)
    out = np.interp(new_x, xs_unique, ys[idx])
    out[(new_x < xs_unique[0]) | (new_x > xs_unique[-1])] = np.nan
    return out


def interp_gap_preserving(new_x: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Linear interpolation that never bridges an interior gap (V6 §4).

    Output samples are NaN everywhere the source provides no evidence:
    inside an interior NaN span (a missing interval stays missing — no
    linear ramp across a washed-out zone), and outside the finite samples'
    hull. Interpolation happens only within each contiguous finite run.
    """
    new_x = np.asarray(new_x, dtype=float)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    out = np.full(new_x.shape, np.nan)
    finite = np.isfinite(x) & np.isfinite(y)
    if not finite.any():
        return out
    idx = np.flatnonzero(finite)
    breaks = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate(([idx[0]], idx[breaks + 1]))
    ends = np.concatenate((idx[breaks], [idx[-1]]))
    for s, e in zip(starts, ends):
        segment = (new_x >= x[s]) & (new_x <= x[e])
        if not segment.any():
            continue
        xs, ys = x[s : e + 1], y[s : e + 1]
        # Duplicate depths within a run: np.interp needs strictly increasing
        # x; keep the first sample at each depth (deterministic).
        xs_unique, first = np.unique(xs, return_index=True)
        out[segment] = np.interp(new_x[segment], xs_unique, ys[first])
    return out


# ---------------------------------------------------------------------------
# Missing-interval diagnostics (read-only — never creates a version)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MissingIntervalReport:
    """Where a curve has no data, in the depth domain of its axis."""

    intervals: tuple[tuple[float, float], ...]
    total_samples: int
    missing_samples: int

    @property
    def missing_fraction(self) -> float:
        return (
            self.missing_samples / self.total_samples
            if self.total_samples
            else 0.0
        )

    @property
    def largest_gap(self) -> float:
        return max((b - a for a, b in self.intervals), default=0.0)


def missing_interval_report(depth: np.ndarray, values: np.ndarray) -> MissingIntervalReport:
    """Finite-sample gaps strictly INSIDE the surveyed range (edges are not gaps)."""
    d = np.asarray(depth, dtype=float)
    v = np.asarray(values, dtype=float)
    finite = np.isfinite(v) & np.isfinite(d)
    total = int(v.size)
    missing = int((~np.isfinite(v)).sum())
    intervals: list[tuple[float, float]] = []
    if finite.any() and total > 2:
        first, last = int(np.argmax(finite)), int(len(finite) - 1 - np.argmax(finite[::-1]))
        run_start: int | None = None
        for i in range(first, last + 1):
            bad = not finite[i]
            if bad and run_start is None:
                run_start = i
            elif not bad and run_start is not None:
                intervals.append((float(d[run_start]), float(d[i - 1])))
                run_start = None
        if run_start is not None:  # pragma: no cover - loop ends on last finite
            intervals.append((float(d[run_start]), float(d[last])))
    return MissingIntervalReport(
        intervals=tuple(intervals), total_samples=total, missing_samples=missing
    )


# ---------------------------------------------------------------------------
# Derived-curve expression evaluator (controlled — AST whitelist, no eval)
# ---------------------------------------------------------------------------

_ALLOWED_FUNCS: dict[str, Any] = {
    "abs": np.abs,
    "min": np.minimum,
    "max": np.maximum,
    "log": np.log,
    "log10": np.log10,
    "log2": np.log2,
    "exp": np.exp,
    "sqrt": np.sqrt,
    "sin": np.sin,
    "cos": np.cos,
    "tan": np.tan,
    "where": np.where,
    "clip": np.clip,
}

_ALLOWED_BINOPS = (
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv,
)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)
_ALLOWED_CMPOPS = (ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.Eq, ast.NotEq)
_ALLOWED_BOOLOPS = (ast.And, ast.Or)


def evaluate_curve_expression(expr: str, variables: dict[str, np.ndarray]) -> np.ndarray:
    """Evaluate a restricted arithmetic expression over named curve arrays.

    Grammar: numbers, curve names (keys of *variables*), unary +/-, binary
    arithmetic (+ - * / ** % //), element-wise comparisons and boolean
    operators (for ``where(...)`` flags), and calls to the whitelisted
    numpy-style functions in :data:`_ALLOWED_FUNCS` with positional args
    only. Anything else — attribute access, subscripts, lambdas, keywords,
    non-listed names — raises :class:`ValueError` rather than being
    evaluated.
    """
    if not expr or not expr.strip():
        raise ValueError("empty expression")
    if not variables:
        raise ValueError("expression needs at least one curve variable")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {exc}") from exc

    def visit(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Pow):
                return left ** right
            if isinstance(node.op, ast.Mod):
                return left % right
            return left // right
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARYOPS):
            value = visit(node.operand)
            return +value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.Compare) and all(
            isinstance(op, _ALLOWED_CMPOPS) for op in node.ops
        ):
            left = visit(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = visit(comparator)
                if isinstance(op, ast.Gt):
                    left = left > right
                elif isinstance(op, ast.Lt):
                    left = left < right
                elif isinstance(op, ast.GtE):
                    left = left >= right
                elif isinstance(op, ast.LtE):
                    left = left <= right
                elif isinstance(op, ast.Eq):
                    left = left == right
                else:
                    left = left != right
            return left
        if isinstance(node, ast.BoolOp) and isinstance(node.op, _ALLOWED_BOOLOPS):
            operands = [np.asarray(visit(v), dtype=bool) for v in node.values]
            result = operands[0]
            for operand in operands[1:]:
                result = (result & operand) if isinstance(node.op, ast.And) else (result | operand)
            return result
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return np.asarray(node.value, dtype=float)
            raise ValueError(f"constant {node.value!r} not allowed (numbers only)")
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(
                    f"unknown curve name {node.id!r}; available: {sorted(variables)}"
                )
            return np.asarray(variables[node.id], dtype=float)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
                name = getattr(getattr(node, "func", None), "id", "?")
                raise ValueError(
                    f"function {name!r} not allowed; supported: {sorted(_ALLOWED_FUNCS)}"
                )
            if node.keywords:
                raise ValueError("keyword arguments are not allowed")
            return _ALLOWED_FUNCS[node.func.id](*[visit(a) for a in node.args])
        raise ValueError(f"expression element {type(node).__name__} is not allowed")

    result = visit(tree)
    result = np.asarray(result, dtype=float)
    if result.ndim != 0 and result.shape != next(iter(variables.values())).shape:
        # Scalar intermediate folding can produce 0-d; anything else must
        # stay sample-aligned.
        raise ValueError("expression did not produce a sample-aligned result")
    return np.broadcast_to(result, next(iter(variables.values())).shape).astype(float).copy()
