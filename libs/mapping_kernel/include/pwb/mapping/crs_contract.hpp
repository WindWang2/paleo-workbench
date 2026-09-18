#pragma once

// pwb::mapping — the unified CRS contract leaf, a faithful C++ port of
// paleo_workbench/mapping/crs_contract.py (V9 W3 single CRS
// predicate/resolution authority; V10/M0 §6 declared-domain rules;
// full-conversion task 17). Frozen against the Python oracle
// (tools/oracle/generate_crs_units_fixtures.py, "kernel" section —
// generated with pyproj import blocked, the same dependency profile as
// this kernel):
//
//   * normalize_crs — the one CRS comparison key ("EPSG:4326 / WGS84" →
//     "EPSG:4326"). It canonicalizes spelling; it never verifies that the
//     id resolves ("EPSG:99999" passes through and stays declared);
//   * crs_is_geographic — the axis-units truth IS
//     pwb::mapping::crs_is_geographic (crs_policy.hpp): Python's
//     crs_contract wrapper only strips and maps "" → None, which the
//     kernel predicate already answers identically. No second predicate.
//     nullopt = unverifiable, never a guess;
//   * resolve_crs / panel_publish_crs — an undeclared CRS never becomes
//     EPSG:4326 silently: it stays "" and carries a degraded reason the
//     caller must surface;
//   * crs_axis_unit_metres / scale_denominator_from_pixels — a scale
//     denominator is only meaningful on *verifiably* metre axes; the
//     kernel has no pyproj, so axes are never verifiable and the
//     denominator is honestly 0.0;
//   * crs_coordinate_domain / coordinate_domain_mismatch /
//     infer_crs_from_extent — declared-domain vs data-extent facts.
//     Geographic CRS → the analytic degree domain; projected CRS needs a
//     pyproj area_of_use transform, which this kernel cannot do →
//     nullopt: cannot-verify ≠ pass (fail-open, provable mismatches only).
//
// geod_for_crs is NOT ported: it returns a pyproj.Geod (ellipsoid math
// library), outside the Qt-free kernel. See ledger 17-findings.
// Qt-free, Python-free, numpy-free, pyproj-free.

#include <array>
#include <optional>
#include <string>

#include <pwb/mapping/crs_policy.hpp>

namespace pwb::mapping {

// Canonical CRS auth id ("" when absent/unparseable shape). Port of
// `re.match(r"^(EPSG:\d+)\b", text, re.IGNORECASE)` → group(1).upper(),
// else the stripped text unchanged.
std::string normalize_crs(const std::optional<std::string>& crs);

struct CRSResolution {
    // Resolved auth id; "" = none resolved.
    std::string crs;
    // False exactly when the source carried no usable CRS.
    bool declared = false;
    // What was done instead when declared is false. Callers surface it —
    // never swallow it.
    std::string degraded_reason;

    bool ok() const { return declared && !crs.empty(); }
};

// Resolve a CRS requirement without silent defaults. A non-empty `value`
// wins (normalized, declared). Otherwise `fallback` applies only when it
// is a real, recorded legacy default — the result is marked degraded with
// the purpose named. Otherwise undeclared (""): the forbidden pattern is
// `project_crs or "EPSG:4326"` with no trace.
CRSResolution resolve_crs(const std::optional<std::string>& value,
                          const std::string& purpose,
                          const std::optional<std::string>& fallback =
                              std::nullopt);

// Panel/publish path: undeclared → "" (render in original coordinates).
// The Python side also logger.warning's the degraded reason; in the
// kernel the reason travels on CRSResolution and surfacing it is the
// caller's contract.
std::string panel_publish_crs(
    const std::optional<std::string>& value,
    const std::string& purpose = "图层面板发布");

// True when the horizontal axis unit is verifiably metres. No pyproj in
// the kernel → nullopt for any non-empty id (the Python ImportError
// path); empty → nullopt.
std::optional<bool> crs_axis_unit_metres(const std::optional<std::string>& crs);

// Honest scale denominator from pixel geometry (mupp × inches-per-metre ×
// dpi) — 0.0 (unknown) unless the CRS axis unit is verifiably metres.
double scale_denominator_from_pixels(double map_units_per_pixel,
                                     double pixels_per_inch,
                                     const std::optional<std::string>& crs);

// (minx, miny, maxx, maxy) in the CRS's own coordinate units.
using Domain = std::array<double, 4>;

// Geographic CRS axes domain — analytic, exact.
inline constexpr Domain kGeographicDegreeDomain = {-180.0, -90.0, 180.0, 90.0};

// Declared-domain tolerances: epsilon absorbs edge-hugging data on the
// analytic geographic domain; the 2% slack only exists for the (unported,
// pyproj-computed) projected approximate box.
inline constexpr double kDomainEpsilon = 1e-9;
inline constexpr double kProjectedDomainSlack = 0.02;

// Valid coordinate domain of a declared CRS. Geographic → the degree
// domain; projected → pyproj area_of_use transform in Python, ImportError
// here → nullopt; undeclared → nullopt.
std::optional<Domain> crs_coordinate_domain(const std::optional<std::string>& crs);

// One provable "declared CRS domain vs actual data extent" mismatch.
struct DomainMismatch {
    std::string crs;
    Domain extent{};
    Domain domain{};

    // Chinese user-facing verdict; ":g" numbers via C "%g" (same origin).
    std::string describe() const;
};

// extent not fully inside the declared domain → the mismatch fact;
// unusable extent or underivable domain → nullopt (fail-open: only
// provable mismatches are caught).
std::optional<DomainMismatch> coordinate_domain_mismatch(
    const std::optional<std::string>& crs,
    const std::optional<Domain>& extent);

struct CRSInference {
    // "" = keep local (no declaration suggested).
    std::string suggested_crs;
    // Basis text for diagnostics/dialogs.
    std::string basis;

    bool suggests_declaration() const { return !suggested_crs.empty(); }
};

// First-import extent inference (M0 §6): fully inside the degree domain →
// suggest EPSG:4326 (user confirms, then it is locked); outside → keep
// local; unusable extent → no inference. A suggestion, never a silent
// declaration.
CRSInference infer_crs_from_extent(const std::optional<Domain>& extent);

}  // namespace pwb::mapping
