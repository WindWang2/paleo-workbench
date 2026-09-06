"""Factor unit / color-ramp defaults — the leaf authority for the factor chain.

``FACTOR_DEFAULTS`` was promoted here from
``mapping/geological_pipeline/pipeline.py`` (which re-exports it) so the
*workflow* task pipeline can resolve a factor's unit without importing the
mapping package. The dependency arrow between the two packages must stay
one-directional (mapping → workflow, because ``geological_pipeline.pipeline``
consumes ``workflow.factor_grid_result``).

Contract:

* A factor whose mnemonic is known gets its canonical unit and recommended
  color ramp. The unit travels explicitly through the whole chain:
  extract → interpolate → ``FactorGridResult.unit`` → contour labels → legend.
* An *unknown* factor resolves to ``None`` — "no declared unit". Units are
  never guessed from the value range or the method (the grid contract treats
  ``None`` the same way it treats an undeclared CRS).
* Dimensionless quantities use the UCUM convention ``"1"`` (probability),
  not an empty string, so a declared-dimensionless factor stays
  distinguishable from an undeclared one.

This module imports only the standard library.
"""

from __future__ import annotations

FACTOR_DEFAULTS: dict[str, dict[str, str]] = {
    # --- porosity --------------------------------------------------------------
    "孔隙度": {"unit": "%", "color_ramp": "porosity"},
    "porosity": {"unit": "%", "color_ramp": "porosity"},
    "POR": {"unit": "%", "color_ramp": "porosity"},
    "PORO": {"unit": "%", "color_ramp": "porosity"},
    "PHIE": {"unit": "%", "color_ramp": "porosity"},
    "PHIT": {"unit": "%", "color_ramp": "porosity"},
    # --- permeability ----------------------------------------------------------
    "渗透率": {"unit": "mD", "color_ramp": "permeability"},
    "permeability": {"unit": "mD", "color_ramp": "permeability"},
    "PERM": {"unit": "mD", "color_ramp": "permeability"},
    "PERMEABILITY": {"unit": "mD", "color_ramp": "permeability"},
    "K": {"unit": "mD", "color_ramp": "permeability"},
    # --- net pay / sand thickness ---------------------------------------------
    "有效厚度": {"unit": "m", "color_ramp": "sand_thickness"},
    "net_pay": {"unit": "m", "color_ramp": "sand_thickness"},
    "NET_PAY": {"unit": "m", "color_ramp": "sand_thickness"},
    "净产层厚度": {"unit": "m", "color_ramp": "sand_thickness"},
    "H_pay": {"unit": "m", "color_ramp": "sand_thickness"},
    "H_net": {"unit": "m", "color_ramp": "sand_thickness"},
    "PAY_THICKNESS": {"unit": "m", "color_ramp": "sand_thickness"},
    # --- formation thickness ---------------------------------------------------
    "地层厚度": {"unit": "m", "color_ramp": "thickness"},
    "formation_thickness": {"unit": "m", "color_ramp": "thickness"},
    "thickness": {"unit": "m", "color_ramp": "thickness"},
    "H_t": {"unit": "m", "color_ramp": "thickness"},
    "TOTAL_THICKNESS": {"unit": "m", "color_ramp": "thickness"},
    "砂岩厚度": {"unit": "m", "color_ramp": "sand_thickness"},
    "sand_thickness": {"unit": "m", "color_ramp": "sand_thickness"},
    "H_s": {"unit": "m", "color_ramp": "sand_thickness"},
    "SAND_THICKNESS": {"unit": "m", "color_ramp": "sand_thickness"},
    # --- sand ratio ------------------------------------------------------------
    "砂地比": {"unit": "%", "color_ramp": "sand_thickness"},
    "sand_ratio": {"unit": "%", "color_ramp": "sand_thickness"},
    "R_s": {"unit": "%", "color_ramp": "sand_thickness"},
    "SAND_RATIO": {"unit": "%", "color_ramp": "sand_thickness"},
    # --- depth markers ---------------------------------------------------------
    "地层顶界": {"unit": "m", "color_ramp": "elevation"},
    "顶界深度": {"unit": "m", "color_ramp": "elevation"},
    "top_depth": {"unit": "m", "color_ramp": "elevation"},
    "top_md": {"unit": "m", "color_ramp": "elevation"},
    "top_tvd": {"unit": "m", "color_ramp": "elevation"},
    "TOP": {"unit": "m", "color_ramp": "elevation"},
    "TOP_DEPTH": {"unit": "m", "color_ramp": "elevation"},
    "地层底界": {"unit": "m", "color_ramp": "elevation"},
    "底界深度": {"unit": "m", "color_ramp": "elevation"},
    "base_depth": {"unit": "m", "color_ramp": "elevation"},
    "base_md": {"unit": "m", "color_ramp": "elevation"},
    "base_tvd": {"unit": "m", "color_ramp": "elevation"},
    "BASE": {"unit": "m", "color_ramp": "elevation"},
    "BASE_DEPTH": {"unit": "m", "color_ramp": "elevation"},
    # --- geochemistry / source rock -------------------------------------------
    "TOC": {"unit": "%", "color_ramp": "toc"},
    "toc": {"unit": "%", "color_ramp": "toc"},
    # --- palaeo-environment ----------------------------------------------------
    "古水深": {"unit": "m", "color_ramp": "water_depth"},
    "water_depth": {"unit": "m", "color_ramp": "water_depth"},
    "paleo_water_depth": {"unit": "m", "color_ramp": "water_depth"},
    "PALEO_WATER_DEPTH": {"unit": "m", "color_ramp": "water_depth"},
    # --- probability (UCUM dimensionless "1": values live in [0, 1]) -----------
    "probability": {"unit": "1", "color_ramp": "probability"},
    "PROBABILITY": {"unit": "1", "color_ramp": "probability"},
    "概率": {"unit": "1", "color_ramp": "probability"},
    "沉积概率": {"unit": "1", "color_ramp": "probability"},
}

# Factor families (M1 coverage contract): every family a single-factor map may
# carry, with its canonical representative mnemonic. Seismic-derived attributes
# are intentionally absent — they enter as *existing* factor results and keep
# whatever unit their producing run declared.
FACTOR_FAMILIES: dict[str, tuple[str, ...]] = {
    "sand_thickness": ("砂岩厚度", "sand_thickness", "H_s"),
    "formation_thickness": ("地层厚度", "formation_thickness", "H_t"),
    "sand_ratio": ("砂地比", "sand_ratio", "R_s"),
    "porosity": ("孔隙度", "porosity"),
    "probability": ("probability", "概率"),
    "paleo_water_depth": ("古水深", "water_depth"),
}


def normalize_factor_key(factor_name: str) -> str:
    """Canonical lookup key: stripped, case-folded."""
    return factor_name.strip().lower() if factor_name else ""


def _folded_entry(factor_name: str) -> dict[str, str] | None:
    """Case-folded lookup over every known mnemonic (case is never semantic)."""
    key = normalize_factor_key(factor_name)
    direct = FACTOR_DEFAULTS.get(factor_name) or FACTOR_DEFAULTS.get(key)
    if direct:
        return direct
    for aliases in FACTOR_FAMILIES.values():
        if key in {alias.lower() for alias in aliases}:
            for representative in aliases:
                entry = FACTOR_DEFAULTS.get(representative) or FACTOR_DEFAULTS.get(
                    representative.lower()
                )
                if entry:
                    return entry
    return None


def unit_for_factor(factor_name: str) -> str | None:
    """Canonical unit for *factor_name*, or ``None`` when unknown (never guessed)."""
    entry = _folded_entry(factor_name)
    return (entry.get("unit") or None) if entry else None


def color_ramp_for_factor(factor_name: str) -> str | None:
    """Recommended color ramp for *factor_name*, or ``None`` when unknown."""
    entry = _folded_entry(factor_name)
    return (entry.get("color_ramp") or None) if entry else None


# Derived-factor provenance rules (decision D11): explicit derivation is legal
# geology; it must carry a traceable marker instead of passing as measured data.
DERIVED_SAND_RATIO_RULE = "sand_ratio = H_s / H_t"
DERIVED_FORMATION_THICKNESS_RULE = "formation_thickness = base_depth - top_depth"


def validate_factor_unit_against_values(
    factor_name: str,
    unit: str | None,
    values,
) -> list[str]:
    """Cross-check a DECLARED unit against the values' magnitude (V6 §14).

    A name-derived "%" unit on a fraction (0..1) column — or "1" on percent-
    scale data — silently misclassifies every downstream threshold. The
    check is a diagnostic, not a correction: it never rewrites the unit.
    """
    import numpy as np

    if unit is None:
        return []
    arr = np.asarray(values, dtype=float)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return []
    lo, hi = float(finite.min()), float(finite.max())
    diagnostics: list[str] = []
    u = str(unit).strip()
    if u in {"%", "percent"}:
        if 0.0 <= lo and hi <= 1.5 and not np.allclose(finite, np.round(finite)):
            diagnostics.append(
                f"factor {factor_name!r} declares % but values span "
                f"[{lo:.3g}, {hi:.3g}] — fractions misread as percent "
                f"(÷100 or relabel as v/v)"
            )
    elif u in {"1", "v/v", "fraction"}:
        if lo >= 1.5 or hi > 1.5:
            diagnostics.append(
                f"factor {factor_name!r} declares dimensionless {u!r} but values "
                f"span [{lo:.3g}, {hi:.3g}] — percent-scale data in a 0..1 unit"
            )
    return diagnostics
