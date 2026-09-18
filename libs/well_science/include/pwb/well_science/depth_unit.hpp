// Depth-unit vocabulary (V6 §2–3): a depth axis is m / ft / unknown.
// "Unknown" is a first-class state, never coerced to meters. Ported from
// paleo_workbench/workflow/well_science.py (frozen against its oracle).
#pragma once

#include <optional>
#include <string>

namespace pwb::well_science {

// Classified depth-axis unit. `unit` is nullopt when unknown; `declared`
// distinguishes a header-declared token the code could not honor (e.g.
// DEPT.FURLONGS) from a unit the file never declared at all. `raw` preserves
// the stripped token verbatim for diagnostics.
struct DepthUnitInfo {
    std::optional<std::string> unit;
    bool declared = false;
    std::string raw;

    bool known() const { return unit && (*unit == "m" || *unit == "ft"); }
};

// Classify one depth-unit header token (nullopt / empty = undeclared).
// Matching is on the ASCII-uppercased stripped token: FT/F/FEET/FOOT and
// M/METER/METERS/MTR/MTRS/METRE/METRES.
DepthUnitInfo classify_depth_unit(std::optional<std::string> token);

// Return the canonical unit ("m"/"ft") or throw UnknownDepthUnitError.
std::string require_depth_unit(const DepthUnitInfo& info,
                               const std::string& operation);
std::string require_depth_unit(std::optional<std::string> token,
                               const std::string& operation);

// Read the depth-unit envelope off a loaded well-log document. Python ducks
// on the document's `depth_unit` attribute; the C++ core receives the
// envelope value directly — nullopt (bare document) is UNKNOWN, never meters.
DepthUnitInfo depth_unit_of(std::optional<std::string> envelope_unit);

}  // namespace pwb::well_science
