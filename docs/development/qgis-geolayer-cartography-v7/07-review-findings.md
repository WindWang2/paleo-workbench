# 07 — Review findings (§19 three rounds)

Status: PENDING — the three review rounds run after the bridge suite
verification completes (all implementation phases are committed; reviews
cover the final state).

## Round 1 — Scientific / GIS correctness
Focus: geometry/CRS/unit honesty, RAW/DERIVED discipline, constraints
routing, factor values, styling never rewrites science, QGIS operation
parity (bridge vs shapely on canonical fixtures).
<!-- R1_FINDINGS -->

## Round 2 — Architecture
Focus: no second GIS kernel, layer authority (spec registry ↔
memberships), QGIS tree authority, MapDocument authority, persistence,
mirror ledgers, layout (no second project authority), catalog/run graph.
<!-- R2_FINDINGS -->

## Round 3 — Cartography / Performance / Adversarial
Focus: 1000-layer trees, complex polygons/holes/Multi*, invalid geometries,
missing CRS, stale factors, bad renderers, project reopen, layout export,
fallback honesty, benchmark budgets.
<!-- R3_FINDINGS -->

## Fix log
<!-- FIX_LOG -->
