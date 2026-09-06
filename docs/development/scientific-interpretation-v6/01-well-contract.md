# 01 — Well Scientific Contract V2

## Status: implemented (§2–7)

The typed vocabulary lives in `paleo_workbench/workflow/well_science.py`;
existing domain models were extended, not replaced.

| contract concept | implementation |
|---|---|
| WellIdentity | stable resource ids; `build_well_identity_map` refuses duplicate-name→id ambiguity; tops/datum/multi-well keyed by id (see 00-baseline P0-2 fixes) |
| CurveIdentity | `stable_entity_id("curve", well, mnemonic, index)` + engine resource ids (duplicate names disambiguated by slot) |
| DepthAxis | `WellLogData.curves[i].depth` + `WellLogDataWithDepthUnit` envelope |
| DepthDomain | `workflow/stratigraphy_models.DepthDomain` (MD/TVD/TVDSS; unchanged authority) |
| DepthUnit | `DepthUnitInfo{unit: m\|ft\|None, declared, raw}` — unknown is first-class |
| NullPolicy | `NullPolicy{source: declared\|inferred\|derived_injected\|none, sentinel, inferred_sentinels}` |
| GapMask | NaN values ride on the axis; `interp_gap_preserving` keeps interior gaps; engine run-splitting renders them |
| CurveVersion | catalog DERIVED versions per correction (unchanged ADR 0056 path) |
| InterpretationVersion | correlation artifacts + fingerprints (unchanged Stage-12 path) |

## Invariants (verified by tests/test_well_science.py, test_well_identity.py)
1. stable ids only — display names never identify wells/curves/tops.
2. MD/TVD/TVDSS distinct; m/ft conversion explicit via the curve_operations
   whitelist; unknown → `UnknownDepthUnitError` from any unit-dependent op.
3. declared vs inferred nulls distinguished; derived LAS injection is
   recorded (`null_policy: derived_injected` in run provenance).
4. gaps survive: resample never bridges; engine submission carries NaN.
5. RAW immutable; every correction = DERIVED + DataRun.
6. render decimation never reaches scientific computation (preview loader
   separated; unit envelope travels with the document).
