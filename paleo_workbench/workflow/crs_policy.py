"""Distance/CRS policy for distance-based interpolation (decision D5).

The interpolation cores compute distances in the *raw coordinate space*
(Euclidean on the given XY). That is scientifically correct for projected
map metres and a silent lie for geographic degrees. The workbench cannot
reproject for the operator (source-CRS semantics belong to the data), but it
must never let the assumption stay implicit:

* :func:`resolve_distance_policy` inspects the declared CRS (pyproj when
  available, with a conservative built-in fallback for common geographic
  ids) and returns the *effective* strategy the run applies.
* A geographic CRS with the default ``planar`` policy resolves to
  ``planar_degrees`` — allowed (small-extent geological mapping is a legal
  use), but always **annotated**: the strategy travels on the grid result's
  ``algorithm_parameters`` and the task's quality metrics, so every consumer
  (QA, MapProduct compare, export metadata) can see it.
* An explicit operator override is honoured verbatim.
* An undeclared CRS stays undeclared — no policy is invented for it beyond
  marking the planar assumption as unverifiable.

This module is a leaf: standard library + optional pyproj.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = [
    "DISTANCE_POLICIES",
    "POLICY_PLANAR",
    "POLICY_PLANAR_DEGREES",
    "POLICY_UNDECLARED",
    "crs_is_geographic",
    "resolve_distance_policy",
]

POLICY_PLANAR = "planar"
POLICY_PLANAR_DEGREES = "planar_degrees"
POLICY_PROJECTED = "projected"
POLICY_UNDECLARED = "undeclared"

DISTANCE_POLICIES = (POLICY_PLANAR, POLICY_PLANAR_DEGREES, POLICY_PROJECTED)

logger = logging.getLogger(__name__)

# Well-known geographic CRS ids recognised without pyproj. Everything else
# needs pyproj; if pyproj is missing the CRS is treated as *unknown axis
# units* and the policy is annotated as unverifiable rather than guessed.
_KNOWN_GEOGRAPHIC = {
    "EPSG:4326",
    "EPSG:4269",  # NAD83
    "EPSG:4267",  # NAD27
    "EPSG:4214",  # Beijing 1954
    "EPSG:4610",  # Xian 1980
    "EPSG:4490",  # CGCS2000
    "EPSG:3857",  # Web Mercator — degrees in, projected metres out; the
    #               axis units below decide, this id alone is projected.
}
# ids in the set above that are actually projected (never treated as degrees)
_PROJECTED_EXCEPTIONS = {"EPSG:3857"}


def crs_is_geographic(crs: str | None) -> bool | None:
    """True/False when the CRS axis units are known, ``None`` when unknown."""
    if not crs:
        return None
    token = crs.split("/")[0].strip().upper()
    if token in _PROJECTED_EXCEPTIONS:
        return False
    if token in _KNOWN_GEOGRAPHIC:
        return True
    try:
        from pyproj import CRS

        parsed = CRS.from_user_input(crs)
        return parsed.is_geographic
    except Exception:
        return None


def resolve_distance_policy(
    crs: str | None,
    distance_policy: str | None = None,
) -> dict[str, Any]:
    """Resolve the effective distance strategy for a run.

    Returns ``{"policy": <effective>, "crs": <crs or None>,
    "axes_known": bool|None, "annotation": str, "warning": str|None}``.
    """
    axes_known = crs_is_geographic(crs)
    declared = (distance_policy or "").strip() or None
    if declared is not None and declared not in DISTANCE_POLICIES:
        raise ValueError(
            f"distance_policy must be one of {DISTANCE_POLICIES}, got {declared!r}"
        )

    if crs is None:
        policy = declared or POLICY_PLANAR
        return {
            "policy": policy,
            "crs": None,
            "axes_known": None,
            "annotation": (
                f"distance_policy={policy}; CRS undeclared — planar "
                "assumption unverified"
            ),
            "warning": None,
        }

    geographic = axes_known
    if declared == POLICY_PLANAR_DEGREES:
        return {
            "policy": POLICY_PLANAR_DEGREES,
            "crs": crs,
            "axes_known": geographic,
            "annotation": (
                "distance_policy=planar_degrees; operator explicitly accepted "
                "degree-as-planar distances"
            ),
            "warning": None if geographic else "planar_degrees declared for a non-geographic CRS",
        }
    if declared == POLICY_PROJECTED:
        return {
            "policy": POLICY_PROJECTED,
            "crs": crs,
            "axes_known": geographic,
            "annotation": f"distance_policy=projected; CRS {crs} declared projected by operator",
            "warning": (
                "projected policy declared but CRS is geographic"
                if geographic
                else None
            ),
        }

    # Default policy: planar. Honest only when axes are known-projected.
    if geographic is True:
        warning = (
            f"CRS {crs} is geographic (degree axes); interpolation distances "
            "treat degrees as planar metres. For large extents reproject to a "
            "projected CRS or declare distance_policy='planar_degrees'."
        )
        logger.warning(warning)
        return {
            "policy": POLICY_PLANAR_DEGREES,
            "crs": crs,
            "axes_known": True,
            "annotation": (
                f"distance_policy=planar_degrees; geographic CRS {crs} — "
                "degree-as-planar assumption APPLIED and recorded"
            ),
            "warning": warning,
        }
    if geographic is None:
        # Unknown axis units (unresolvable id / no pyproj): the planar
        # assumption is UNVERIFIED and the annotation must not claim
        # otherwise (review R1/R3 P2).
        return {
            "policy": POLICY_PLANAR,
            "crs": crs,
            "axes_known": None,
            "annotation": (
                f"distance_policy=planar; CRS {crs} axis units unverifiable "
                "(unknown id or pyproj unavailable) — planar assumption "
                "unconfirmed"
            ),
            "warning": (
                f"CRS {crs} axis units could not be verified; distance "
                "policy applied without confirmation"
            ),
        }
    return {
        "policy": POLICY_PLANAR,
        "crs": crs,
        "axes_known": geographic,
        "annotation": (
            f"distance_policy=planar; CRS {crs} projected/verified planar metres"
        ),
        "warning": None,
    }
