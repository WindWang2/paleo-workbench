// VIZ-A — Chinese lithology/facies vocabulary for the WLE pattern stack.
// Ports the frozen geoviz_well_log data tables (pattern_map.py: PATTERN_MAP
// 36 entries, FACIES_COLORS 85 entries @ geo-viz-engine 08851951) plus the
// PatternEngine lookup order (exact match, then longest-key substring —
// pattern_engine.py _fuzzy_lookup/_SORTED_*_KEYS). The WLE SDK supplies the
// rendering vocabulary (PatternDefinition + IntervalLayerSpec, scene.hpp);
// this header maps the workbench's Chinese names onto it.

#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include <welllog/scene/scene.hpp>

namespace pwb::viz {

// PATTERN_MAP — frozen order (stability matters: substring lookup breaks
// ties by insertion order among equal-length keys, exactly like Python's
// stable sort over the dict keys).
const std::vector<std::pair<std::string, std::string>>& pattern_map_entries();

// FACIES_COLORS — frozen order, same tie-break rule.
const std::vector<std::pair<std::string, std::string>>& facies_color_entries();

// Exact-then-longest-substring lookup; empty when nothing matches
// (PatternEngine._fuzzy_lookup returns None -> caller falls back to a solid
// color; that policy stays with the track builder).
std::string pattern_id_for(const std::string& lithology_name);

// FACIES_COLORS lookup with the same fuzzy rule ("#rrggbb", empty when
// unmatched).
std::string facies_color_for(const std::string& name);

// WellLog scene vocabulary (scene.hpp / types.hpp).
using PatternDefinition = welllog::PatternDefinition;

// Deterministic WLE pattern definition for a pattern id (tile geometry +
// restricted vector primitives, ADR 0020 vocabulary only). The primitives
// are a procedural approximation of the geoviz SVG tile assets — visual
// parity tolerance is declared in docs/development/cpp-viz-a/ledger.md
// (geometry spec: tile 4mm x 4mm, anchored, version-tagged; not a
// pixel-for-pixel port of the SVGs). nullopt for an unknown id.
std::optional<PatternDefinition> make_pattern_definition(
    const std::string& pattern_id, welllog::EntityId id = {});

}  // namespace pwb::viz
