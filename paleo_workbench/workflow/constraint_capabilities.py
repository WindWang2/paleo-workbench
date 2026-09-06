"""Method × constraint capability matrix (scientific V6 §10).

THE contract that makes constraint handling honest: for every interpolation
method and every geological constraint kind, this module states whether the
method SUPPORTS, PARTIALLY supports, APPROXIMATES, or does NOT support the
constraint — and :func:`evaluate_request` turns a requested set into the
structured ``requested/applied/partial/ignored/unsupported`` record that
must travel with every interpolation result.

The rule this enforces (audit P0-6/P0-7): a workflow may never silently
pass a constraint the backend ignores — the geologist who draws faults and
picks kriging gets a fault-oblivious surface *labelled as such*, with the
ignored constraints on the provenance record.

Support semantics per the V6 baseline audit (00-baseline.md §3):

===============  ==============  ===========  ===================  =====================
method            boundary mask   barrier      direction/aniso     trend (q/b_i weights)
===============  ==============  ===========  ===================  =====================
IDW (workflow)    unsupported     supported    unsupported         unsupported
constrained IDW   supported       supported    supported(corridor) supported(decluster)
kriging           unsupported     unsupported  unsupported         unsupported
spline (cubic)    partial(hull)   unsupported  unsupported         unsupported
linear            partial(hull)   unsupported  unsupported         unsupported
nearest           partial(hull)   unsupported  unsupported         unsupported
rbf               partial(hull)   unsupported  unsupported         unsupported
directional       unsupported     unsupported  supported(global)   supported
===============  ==============  ===========  ===================  =====================

``partial(hull)`` = the method clips to the samples' convex hull, not to a
user-drawn boundary ring. ``directional`` averages multi-line anisotropy
into one global azimuth (baseline P2-8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConstraintKind(str, Enum):
    BOUNDARY_MASK = "boundary_mask"        # user boundary rings / interpolation domain
    BARRIER = "barrier"                    # faults / break lines (hard discontinuity)
    DIRECTION = "direction"                # direction lines / azimuth corridor
    ANISOTROPY = "anisotropy"              # semi-axis ratio
    TREND = "trend"                        # per-sample quality/bias weights (q/b_i)


class Support(str, Enum):
    SUPPORTED = "supported"
    PARTIAL = "partial"          # honored with material caveats (see notes)
    APPROXIMATION = "approximation"
    UNSUPPORTED = "unsupported"


_PARTIAL_HULL = "clips to the samples' convex hull; a user-drawn boundary ring is not honored"


@dataclass(frozen=True)
class MethodCapabilities:
    method: str
    label: str
    support: dict[ConstraintKind, tuple[Support, str]]
    prerequisites: tuple[str, ...] = ()

    def for_kind(self, kind: ConstraintKind) -> tuple[Support, str]:
        return self.support.get(kind, (Support.UNSUPPORTED, "not consumed by this method"))


_METHODS: dict[str, MethodCapabilities] = {
    "idw": MethodCapabilities(
        method="idw",
        label="IDW 反距离加权",
        support={
            ConstraintKind.BARRIER: (
                Support.SUPPORTED,
                "break lines zero node→sample weights across the barrier segment",
            ),
        },
    ),
    "constrained_idw": MethodCapabilities(
        method="constrained_idw",
        label="约束IDW",
        support={
            ConstraintKind.BOUNDARY_MASK: (
                Support.SUPPORTED,
                "rasterized domain = boundary rings − holes ∩ coverage ∩ hull",
            ),
            ConstraintKind.BARRIER: (
                Support.SUPPORTED,
                "hard line-of-sight barrier + region partitioning + blank corridor",
            ),
            ConstraintKind.DIRECTION: (
                Support.SUPPORTED,
                "curve-coordinate corridor anisotropy along direction lines",
            ),
            ConstraintKind.ANISOTROPY: (
                Support.PARTIAL,
                "anisotropy ratio floored at 16 by the host adapter (documented)",
            ),
            ConstraintKind.TREND: (
                Support.SUPPORTED,
                "declustering weights (q honored via corridor; b_i not consumed)",
            ),
        },
        prerequisites=("scipy",),
    ),
    "kriging": MethodCapabilities(
        method="kriging",
        label="普通克里金",
        support={},  # isotropic ordinary kriging honors no geological constraint
        prerequisites=("≥3 non-collocated samples",),
    ),
    "spline": MethodCapabilities(
        method="spline",
        label="样条 (CloughTocher)",
        support={ConstraintKind.BOUNDARY_MASK: (Support.PARTIAL, _PARTIAL_HULL)},
        prerequisites=("scipy",),
    ),
    "linear": MethodCapabilities(
        method="linear",
        label="线性插值",
        support={ConstraintKind.BOUNDARY_MASK: (Support.PARTIAL, _PARTIAL_HULL)},
    ),
    "nearest": MethodCapabilities(
        method="nearest",
        label="最近邻",
        support={ConstraintKind.BOUNDARY_MASK: (Support.PARTIAL, _PARTIAL_HULL)},
    ),
    "rbf": MethodCapabilities(
        method="rbf",
        label="RBF 多二次",
        support={ConstraintKind.BOUNDARY_MASK: (Support.PARTIAL, _PARTIAL_HULL)},
        prerequisites=("global solve; not reachable from the UI method list"),
    ),
    "directional": MethodCapabilities(
        method="directional",
        label="方向趋势",
        support={
            ConstraintKind.DIRECTION: (
                Support.PARTIAL,
                "multi-line anisotropy averaged into one global azimuth",
            ),
            ConstraintKind.ANISOTROPY: (
                Support.PARTIAL,
                "azimuth + semi-axes honored; global single corridor",
            ),
            ConstraintKind.TREND: (
                Support.SUPPORTED,
                "per-sample q/b_i weights multiply the Gaussian kernel",
            ),
        },
    ),
}


class ConstraintViolationError(ValueError):
    """A strict-mode request asked a method for constraints it cannot honor."""

    def __init__(self, method: str, unsupported: list[str], ignored: list[str]) -> None:
        parts = [f"method {method!r} cannot honor the requested constraints:"]
        if unsupported:
            parts.append(" unsupported: " + ", ".join(unsupported))
        if ignored:
            parts.append(" ignored: " + ", ".join(ignored))
        super().__init__(";".join(parts))
        self.method = method
        self.unsupported = unsupported
        self.ignored = ignored


@dataclass
class ConstraintApplication:
    """The structured requested/applied/ignored record for one interpolation."""

    method: str
    requested: list[str] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)      # requested, backend drops silently
    unsupported: list[str] = field(default_factory=list)  # requested, method cannot honor
    diagnostics: list[str] = field(default_factory=list)

    @property
    def honest(self) -> bool:
        """True when nothing requested was dropped without a diagnostic."""
        return not (set(self.ignored) - set(self.diagnostics_labels()))

    def diagnostics_labels(self) -> set[str]:
        return {d.split(":")[0] for d in self.diagnostics}

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "requested_constraints": list(self.requested),
            "applied_constraints": list(self.applied),
            "partial_constraints": list(self.partial),
            "ignored_constraints": list(self.ignored),
            "unsupported_constraints": list(self.unsupported),
            "constraint_diagnostics": list(self.diagnostics),
        }


def capability_matrix() -> dict[str, dict[str, dict[str, str]]]:
    """The full method × constraint matrix (serialized for UI/docs)."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    for method_id, caps in _METHODS.items():
        row: dict[str, dict[str, str]] = {}
        for kind in ConstraintKind:
            support, notes = caps.for_kind(kind)
            row[kind.value] = {"support": support.value, "notes": notes}
        out[method_id] = {
            "label": caps.label,
            "prerequisites": list(caps.prerequisites),
            "constraints": row,
        }
    return out


def capabilities_for_method(method: str) -> MethodCapabilities:
    key = str(method or "").strip().lower()
    if key not in _METHODS:
        key = _normalize_method_label(key)
    if key not in _METHODS:
        raise KeyError(f"unknown interpolation method {method!r}; known: {sorted(_METHODS)}")
    return _METHODS[key]


_LABEL_ALIASES = {
    "克里金": "kriging",
    "克里金(mvp·线性)": "kriging",
    "反距离加权": "idw",
    "idw": "idw",
    "约束idw": "constrained_idw",
    "样条": "spline",
    "线性": "linear",
    "最近邻": "nearest",
    "方向趋势": "directional",
    "rbf": "rbf",
}


def _normalize_method_label(label: str) -> str:
    return _LABEL_ALIASES.get(label, label)


def evaluate_request(
    method: str,
    requested: "list[ConstraintKind] | set[ConstraintKind] | None",
    *,
    strict: bool = False,
) -> ConstraintApplication:
    """Evaluate requested constraints against a method's capabilities.

    Never silent: every requested-but-dropped kind appears in ``ignored``
    (backend drops it) or ``unsupported`` (method cannot honor it) with a
    human-readable diagnostic. ``strict=True`` raises
    :class:`ConstraintViolationError` instead — used by strict callers
    (Harness scientific actions) where a constraint-oblivious surface must
    not be produced at all.
    """
    caps = capabilities_for_method(method)
    app = ConstraintApplication(method=caps.method)
    for kind in requested or ():
        kind = ConstraintKind(kind)
        app.requested.append(kind.value)
        support, notes = caps.for_kind(kind)
        if support is Support.SUPPORTED:
            app.applied.append(kind.value)
        elif support is Support.PARTIAL:
            app.partial.append(kind.value)
            app.diagnostics.append(f"{kind.value}:partial:{notes}")
        elif support is Support.APPROXIMATION:
            app.partial.append(kind.value)
            app.diagnostics.append(f"{kind.value}:approximation:{notes}")
        else:
            app.unsupported.append(kind.value)
            app.diagnostics.append(
                f"{kind.value}:unsupported:{caps.label} ignores {kind.value} — "
                "the surface will NOT reflect this constraint"
            )
    if strict and (app.unsupported or app.ignored):
        raise ConstraintViolationError(caps.method, app.unsupported, app.ignored)
    return app
