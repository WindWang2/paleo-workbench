"""Sonic slowness units must be resolved from metadata, micro signs included (#879).

``well_tie_host`` kept a private ASCII alias table matched after
``unit.strip().upper()``. Python maps U+00B5 MICRO SIGN and U+03BC GREEK SMALL
MU to U+039C GREEK CAPITAL MU, never to ``U``, so ``µs/ft`` missed the table,
fell through to the unknown-unit branch and was returned unscaled — making
two-way time 3.28084x too small. ``USEC/FT`` was absent from the table
altogether even though ``USEC/M`` was present.

CONTEXT.md spells the canonical sonic unit ``μs/m`` with U+03BC, i.e. exactly
the spelling the old table could not recognise. The host now delegates to
``geoviz_well_tie.sonic_units``, the single unit table.
"""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.viz.hosts.well_tie_host import _sonic_to_us_per_m, _twt_from_sonic

US_FT_TO_US_M = 3.28084

MICRO = "\u00b5"  # MICRO SIGN
GREEK_MU = "\u03bc"  # GREEK SMALL LETTER MU


@pytest.mark.parametrize(
    "unit",
    [
        "US/FT",
        "us/ft",
        "US/F",
        "USFT",
        "USEC/FT",
        "MICROSEC/FT",
        f"{MICRO}s/ft",
        f"{GREEK_MU}s/ft",
        f"{MICRO}S/FT",
        f" {MICRO}s/ft ",
    ],
)
def test_foot_units_are_scaled_to_us_per_m(unit: str) -> None:
    """Every recognised µs/ft spelling must scale the VALUES, not just the label."""
    sonic = np.full(5, 150.0)
    out = _sonic_to_us_per_m(sonic.copy(), unit)
    assert out[0] == pytest.approx(150.0 * US_FT_TO_US_M, rel=1e-9), (
        f"unit {unit!r} was not converted to µs/m"
    )


@pytest.mark.parametrize(
    "unit",
    ["US/M", "us/m", "USM", "USEC/M", "MICROSEC/M", f"{MICRO}s/m", f"{GREEK_MU}s/m"],
)
def test_metre_units_pass_through_unchanged(unit: str) -> None:
    """µs/m is already canonical, so values must be returned untouched."""
    sonic = np.full(5, 150.0)
    out = _sonic_to_us_per_m(sonic.copy(), unit)
    assert out[0] == pytest.approx(150.0, rel=1e-12), f"unit {unit!r} was wrongly scaled"


def test_micro_sign_and_ascii_spellings_agree() -> None:
    """The µ spelling must be indistinguishable from the ASCII one."""
    sonic = np.full(4, 145.0)
    ascii_out = _sonic_to_us_per_m(sonic.copy(), "US/FT")
    micro_out = _sonic_to_us_per_m(sonic.copy(), f"{MICRO}s/ft")
    greek_out = _sonic_to_us_per_m(sonic.copy(), f"{GREEK_MU}s/ft")
    np.testing.assert_allclose(micro_out, ascii_out)
    np.testing.assert_allclose(greek_out, ascii_out)


def test_twt_is_identical_for_ascii_and_micro_spelling() -> None:
    """The downstream effect: TWT must not depend on how the unit was spelled.

    Before the fix a 100 m interval logged at 150 µs/ft integrated to 30.0 ms
    with the µ spelling versus the correct 98.4 ms with ``US/FT``.
    """
    depths = np.array([0.0, 100.0])
    sonic = np.full(2, 150.0)

    ascii_twt = _twt_from_sonic(
        depths, _sonic_to_us_per_m(sonic.copy(), "US/FT"), "m"
    )
    micro_twt = _twt_from_sonic(
        depths, _sonic_to_us_per_m(sonic.copy(), f"{MICRO}s/ft"), "m"
    )

    np.testing.assert_allclose(micro_twt, ascii_twt)
    # 2 * 100 m * (150 * 3.28084) µs/m / 1000 -> ms
    assert float(ascii_twt[-1]) == pytest.approx(
        2 * 100.0 * 150.0 * US_FT_TO_US_M / 1000.0, rel=1e-6
    )


def test_unknown_unit_is_reported_not_silently_passed(caplog) -> None:
    """An unrecognised unit must produce a diagnostic rather than pass silently."""
    sonic = np.full(5, 300.0)  # >= 150 so the heuristic assumes µs/m
    with caplog.at_level("WARNING"):
        out = _sonic_to_us_per_m(sonic.copy(), "furlongs/fortnight")
    assert out[0] == pytest.approx(300.0)
    assert any(
        "sonic unit" in record.getMessage() for record in caplog.records
    ), "an unknown sonic unit must be surfaced as a warning"


def test_host_delegates_to_the_single_unit_table() -> None:
    """The host must not carry a second sonic unit table.

    The behavioural tests above are the real regression guard; this one only
    pins the structural decision that there is exactly one unit table, so a
    future edit cannot silently fork it again.
    """
    import inspect

    from paleo_workbench.viz.hosts import well_tie_host

    assert "normalize_sonic_units" in inspect.getsource(well_tie_host), (
        "well_tie_host must delegate sonic unit resolution to "
        "geoviz.normalize_sonic_units instead of re-implementing it (#879)"
    )
