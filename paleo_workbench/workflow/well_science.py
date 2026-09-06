"""Well scientific contract V6: depth units, null policy, gap semantics.

The typed vocabulary every unit-dependent well operation shares (§2–4 of the
Scientific Interpretation & Algorithm V6 program):

* :class:`DepthUnitInfo` — a depth axis unit is ``m``/``ft`` **or unknown**;
  "unknown" is a first-class state, never coerced to meters. ``declared``
  distinguishes a header-declared unit the code could not honor (e.g.
  ``DEPT.FURLONGS``) from a unit the file never declared at all.
* :func:`require_depth_unit` — the gate every unit-dependent operation calls
  before doing arithmetic; unknown raises :class:`UnknownDepthUnitError`
  instead of guessing.
* :func:`classify_depth_unit` / :func:`depth_unit_of` — one authority for
  token classification and for reading the unit off a loaded document
  (bare ``WellLogData`` or its ``WellLogDataWithDepthUnit`` envelope).

Existing domain models are extended, not duplicated: canonical conversion
factors come from :mod:`paleo_workbench.workflow.curve_operations`
(:func:`conversion_factor` — the explicit whitelist), and depth *domains*
(MD/TVD/TVDSS) remain :class:`paleo_workbench.workflow.stratigraphy_models.DepthDomain`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

FT_TOKENS = frozenset({"FT", "F", "FEET", "FOOT"})
M_TOKENS = frozenset({"M", "METER", "METERS", "MTR", "MTRS", "METRE", "METRES"})


class UnknownDepthUnitError(ValueError):
    """A unit-dependent operation met an unknown/undeclared depth unit.

    ``operation`` names the refusing operation so diagnostics are locatable.
    This is the typed refusal replacing the legacy silent ``or "m"``
    fallbacks (V6 P0-3).
    """

    def __init__(self, info: "DepthUnitInfo | None", operation: str) -> None:
        raw = info.raw if info is not None else ""
        detail = (
            f"declared as {raw!r} but unrecognized"
            if info is not None and info.declared
            else "not declared by the file"
        )
        super().__init__(
            f"operation {operation!r} depends on the depth unit, which is "
            f"{detail}; refusing instead of assuming meters"
        )
        self.info = info
        self.operation = operation


@dataclass(frozen=True)
class DepthUnitInfo:
    """Classified depth-axis unit: ``m``/``ft`` when known, else ``None``.

    ``declared`` is True when the source carried *some* unit token (matched
    or not); ``raw`` preserves that token verbatim for diagnostics.
    """

    unit: str | None
    declared: bool
    raw: str = ""

    @property
    def known(self) -> bool:
        return self.unit in ("m", "ft")


def classify_depth_unit(token: Any) -> DepthUnitInfo:
    """Classify one depth-unit header token (None/"" = undeclared)."""
    raw = str(token).strip() if token is not None else ""
    if not raw:
        return DepthUnitInfo(unit=None, declared=False, raw="")
    upper = raw.upper()
    if upper in FT_TOKENS:
        return DepthUnitInfo(unit="ft", declared=True, raw=raw)
    if upper in M_TOKENS:
        return DepthUnitInfo(unit="m", declared=True, raw=raw)
    return DepthUnitInfo(unit=None, declared=True, raw=raw)


def require_depth_unit(unit: Any, *, operation: str) -> str:
    """Return the canonical unit ("m"/"ft") or raise :class:`UnknownDepthUnitError`.

    *unit* may be a raw token, a ``DepthUnitInfo``, or ``None``.
    """
    info = unit if isinstance(unit, DepthUnitInfo) else classify_depth_unit(unit)
    if not info.known:
        raise UnknownDepthUnitError(info, operation)
    return info.unit  # type: ignore[return-value]


class _HasDepthUnitAttr(Protocol):
    @property
    def depth_unit(self) -> Any: ...


def depth_unit_of(data: Any) -> DepthUnitInfo:
    """Read the depth-unit envelope off a loaded well-log document.

    Bare engine documents (no ``depth_unit`` attribute) are *unknown* —
    absence of metadata is never evidence of meters.
    """
    value = getattr(data, "depth_unit", None)
    if value is None:
        return DepthUnitInfo(unit=None, declared=False)
    return classify_depth_unit(value)


# ---------------------------------------------------------------------------
# Null policy (declared vs inferred vs derived-injected)
# ---------------------------------------------------------------------------

#: Whitelist of legacy missing-value sentinels that may be *inferred* when a
#: source declares none (ResForm-compatible v1). Inference must always be
#: reported as a diagnostic — it is a hypothesis, not a declaration.
INFERRED_NULL_SENTINELS: tuple[float, ...] = (-999.25, -999.0, -9999.0, -99999.0)

#: Default sentinel a DERIVED LAS writer introduces when the source declared
#: none (LAS text cannot carry NaN). Using it is legitimate only when the
#: derivation records the policy in provenance (see curve_interpretation).
DERIVED_NULL_SENTINEL = -999.25

#: Tolerance for matching a declared sentinel in float data.
NULL_MATCH_ABS_TOL = 1e-6


@dataclass(frozen=True)
class NullPolicy:
    """How missing samples are represented for one dataset.

    ``source``:

    * ``"declared"`` — the file itself declared the sentinel (LAS ``NULL``);
    * ``"inferred"`` — a whitelisted legacy sentinel assumed by a loader,
      which must attach a traceable diagnostic;
    * ``"derived_injected"`` — the derivation introduced a sentinel the
      source never declared (recorded in the run's provenance);
    * ``"none"`` — no sentinel is in play (NaN in memory is the only null).
    """

    source: str
    sentinel: float | None = None
    inferred_sentinels: tuple[float, ...] = ()

    @property
    def declared(self) -> bool:
        return self.source == "declared"

    def matches(self, values) -> "Any":
        """Boolean mask of samples equal to the active sentinel(s)."""
        import numpy as np

        arr = np.asarray(values, dtype=float)
        mask = np.zeros(arr.shape, dtype=bool)
        for sentinel in (self.sentinel,) if self.sentinel is not None else ():
            mask |= np.isclose(arr, sentinel, rtol=0.0, atol=NULL_MATCH_ABS_TOL)
        for sentinel in self.inferred_sentinels:
            mask |= np.isclose(arr, sentinel, rtol=0.0, atol=NULL_MATCH_ABS_TOL)
        return mask

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"source": self.source}
        if self.sentinel is not None:
            out["sentinel"] = self.sentinel
        if self.inferred_sentinels:
            out["inferred_sentinels"] = list(self.inferred_sentinels)
        return out


def null_policy_from_declared(declared_sentinel: Any) -> NullPolicy:
    """Policy for a source that (may have) declared a LAS ``NULL`` value."""
    if declared_sentinel is None or declared_sentinel == "":
        return NullPolicy(source="none")
    try:
        return NullPolicy(source="declared", sentinel=float(declared_sentinel))
    except (TypeError, ValueError):
        return NullPolicy(source="none")
