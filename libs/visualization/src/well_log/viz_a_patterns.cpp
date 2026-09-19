// VIZ-A — Chinese lithology/facies vocabulary over the WLE pattern stack.
// Tables are mechanically transcribed from the frozen geoviz source
// (pattern_map.py @ geo-viz-engine 08851951; see tools/oracle/generate_viz_a_*).
// Pattern primitives are a deterministic procedural approximation of the
// geoviz SVG tile assets using only the ADR 0020 vector vocabulary; the
// geometry spec (4mm tile, anchored, versioned) is frozen in
// tests/cpp/viz_a/patterns_test.cpp and the visual tolerance is declared in
// docs/development/cpp-viz-a/ledger.md.

#include "pwb/viz/well_log_patterns.hpp"
#include "pwb/viz/well_log_document_plan.hpp"

#include <algorithm>
#include <unordered_map>

namespace pwb::viz {

namespace {

// Python _SORTED_PATTERN_KEYS/_SORTED_COLOR_KEYS parity: keys sorted by
// descending length, stable for equal lengths (insertion order preserved —
// std::stable_sort over the frozen table order).
std::vector<std::pair<std::string, std::string>> sorted_by_length_desc(
    const std::vector<std::pair<std::string, std::string>>& entries) {
    std::vector<std::pair<std::string, std::string>> sorted = entries;
    std::stable_sort(sorted.begin(), sorted.end(),
                     [](const auto& a, const auto& b) {
                         return a.first.size() > b.first.size();
                     });
    return sorted;
}

std::string fuzzy_lookup(const std::vector<std::pair<std::string, std::string>>& entries,
                         const std::vector<std::pair<std::string, std::string>>& sorted,
                         const std::string& name) {
    for (const auto& [key, value] : entries) {
        if (key == name) return value;
    }
    for (const auto& [key, value] : sorted) {
        if (name.find(key) != std::string::npos) return value;
    }
    return {};
}

// Tile-local helpers (millimetres) for the procedural primitives.
welllog::PatternLine line(double x1, double y1, double x2, double y2) {
    return welllog::PatternLine{
        .from = {welllog::Millimetres{x1}, welllog::Millimetres{y1}},
        .to = {welllog::Millimetres{x2}, welllog::Millimetres{y2}}};
}

welllog::PatternCircle circle(double x, double y, double r, bool filled) {
    return welllog::PatternCircle{
        .center = {welllog::Millimetres{x}, welllog::Millimetres{y}},
        .radius = welllog::Millimetres{r},
        .filled = filled};
}

constexpr double kTile = 4.0;  // mm, see ledger geometry spec

}  // namespace

const std::vector<std::pair<std::string, std::string>>& pattern_map_entries() {
    static const std::vector<std::pair<std::string, std::string>> kMap = {
        {"\xE7\xA0\x82\xE5\xB2\xA9", "sandstone"},
        {"\xE6\xB3\xA5\xE5\xB2\xA9", "mudstone"},
        {"\xE7\x81\xB0\xE5\xB2\xA9", "limestone"},
        {"\xE7\x99\xBD\xE4\xBA\x91\xE5\xB2\xA9", "dolomite"},
        {"\xE9\xA1\xB5\xE5\xB2\xA9", "shale"},
        {"\xE7\xB2\x89\xE7\xA0\x82\xE5\xB2\xA9", "siltstone"},
        {"\xE7\xA0\x82\xE5\x9D\xAA", "sand-flat"},
        {"\xE6\xB3\xA5\xE5\x9D\xAA", "mud-flat"},
        {"\xE4\xBA\x91\xE8\xB4\xA8\xE5\x9D\xAA", "dolomitic-flat"},
        {"\xE6\xB7\xB7\xE7\xA7\xAF\xE6\xBD\xAE\xE5\x9D\xAA", "dolomitic-flat"},
        {"\xE7\xA2\x8E\xE5\xB1\x91\xE5\xB2\xA9\xE6\xBD\xAE\xE5\x9D\xAA", "tidal-flat"},
        {"\xE6\xBD\xAE\xE5\x9D\xAA", "tidal-flat"},
        {"\xE6\xB3\xA5\xE8\xB4\xA8\xE9\x99\x86\xE6\xA3\x9A", "muddy-shelf"},
        {"\xE7\xA0\x82\xE8\xB4\xA8\xE9\x99\x86\xE6\xA3\x9A", "sandy-shelf"},
        {"\xE7\xA0\x82\xE6\xB3\xA5\xE8\xB4\xA8\xE9\x99\x86\xE6\xA3\x9A", "sand-mud-shelf"},
        {"\xE7\xA2\x8E\xE5\xB1\x91\xE5\xB2\xA9\xE6\xB5\x85\xE6\xB0\xB4\xE9\x99\x86\xE6\xA3\x9A", "clastic-shelf"},
        {"\xE6\xB7\xB7\xE7\xA7\xAF\xE6\xB5\x85\xE6\xB0\xB4\xE9\x99\x86\xE6\xA3\x9A", "mixed"},
        {"\xE9\x99\x86\xE6\xA3\x9A", "shelf"},
        {"\xE6\xB7\xB7\xE7\xA7\xAF", "mixed"},
        {"\xE4\xB8\x89\xE8\xA7\x92\xE6\xB4\xB2", "delta"},
        {"\xE6\xBB\xA8\xE5\xB2\xB8", "shoreface"},
        {"\xE5\x89\x8D\xE6\xBB\xA8", "shoreface"},
        {"\xE4\xB8\xB4\xE6\xBB\xA8", "shoreface"},
        {"\xE7\x94\x9F\xE7\x89\xA9\xE7\xA4\x81", "reef"},
        {"\xE7\xA4\x81", "reef"},
        {"\xE8\x92\xB8\xE5\x8F\x91\xE5\xB2\xA9", "evaporite"},
        {"\xE8\x86\x8F\xE7\x9B\x90", "evaporite"},
        {"\xE5\x86\xB0\xE5\xB7\x9D", "glacial"},
        {"\xE5\x86\xB0\xE7\xA2\x9B", "glacial"},
        {"\xE7\x81\xAB\xE5\xB1\xB1\xE5\xB2\xA9", "volcanic"},
        {"\xE7\x86\x94\xE5\xB2\xA9", "volcanic"},
        {"\xE5\x8F\x98\xE8\xB4\xA8\xE5\xB2\xA9", "metamorphic"},
        {"\xE5\x86\xB2\xE7\xA7\xAF\xE6\x89\x87", "alluvial"},
        {"\xE6\xB4\xAA\xE7\xA7\xAF\xE6\x89\x87", "alluvial"},
        {"\xE6\xBD\x9F\xE6\xB9\x96", "lagoon"},
        {"\xE5\xB1\x80\xE9\x99\x90\xE5\x8F\xB0\xE5\x9C\xB0", "lagoon"},
    };
    return kMap;
}

const std::vector<std::pair<std::string, std::string>>& facies_color_entries() {
    // The frozen FACIES_COLORS table already lives in the document plan
    // (PR #1359 vendored it); reuse it instead of a second copy (R3-P1).
    return facies_colors();
}

std::string pattern_id_for(const std::string& lithology_name) {
    static const auto sorted = sorted_by_length_desc(pattern_map_entries());
    return fuzzy_lookup(pattern_map_entries(), sorted, lithology_name);
}

std::string facies_color_for(const std::string& name) {
    static const auto sorted = sorted_by_length_desc(facies_color_entries());
    return fuzzy_lookup(facies_color_entries(), sorted, name);
}

std::optional<PatternDefinition> make_pattern_definition(
    const std::string& pattern_id, welllog::EntityId id) {
    using Primitives = std::vector<welllog::PatternPrimitive>;
    // Family-shaped procedural approximations of the geoviz SVG tiles:
    // each family gets a deterministic, tile-repeatable primitive set.
    static const std::unordered_map<std::string, Primitives> kPrimitives = {
        // Sand-rich: coarse stipple.
        {"sandstone", Primitives{circle(1.0, 1.0, 0.28, true),
                                 circle(3.0, 2.6, 0.28, true),
                                 circle(1.8, 3.4, 0.24, true),
                                 circle(3.2, 0.8, 0.24, true)}},
        // Mud-rich: sparse fine dashes (horizontal).
        {"mudstone", Primitives{line(0.4, 1.0, 1.6, 1.0),
                                line(2.4, 2.2, 3.6, 2.2),
                                line(0.8, 3.2, 2.0, 3.2)}},
        // Carbonates: brick joints.
        {"limestone", Primitives{line(0.0, 2.0, kTile, 2.0),
                                 line(2.0, 0.0, 2.0, 2.0),
                                 line(1.0, 2.0, 1.0, kTile),
                                 line(3.0, 2.0, 3.0, kTile)}},
        {"dolomite", Primitives{line(0.0, 1.3, kTile, 1.3),
                                line(0.0, 2.7, kTile, 2.7),
                                line(1.3, 0.0, 1.3, 1.3),
                                line(2.7, 1.3, 2.7, 2.7),
                                line(2.0, 2.7, 2.0, kTile)}},
        {"shale", Primitives{line(0.0, 0.8, kTile, 0.8),
                             line(0.0, 1.6, kTile, 1.6),
                             line(0.0, 2.4, kTile, 2.4),
                             line(0.0, 3.2, kTile, 3.2)}},
        {"siltstone", Primitives{circle(1.0, 1.0, 0.14, true),
                                 circle(3.0, 1.4, 0.14, true),
                                 circle(2.0, 2.8, 0.14, true),
                                 circle(0.8, 3.2, 0.14, true)}},
        // Flats: alternating dash/dot bands.
        {"sand-flat", Primitives{line(0.3, 1.0, 2.0, 1.0),
                                 circle(3.0, 1.0, 0.2, true),
                                 line(0.3, 3.0, 2.0, 3.0),
                                 circle(3.0, 3.0, 0.2, true)}},
        {"mud-flat", Primitives{line(0.3, 1.2, 3.7, 1.2),
                                line(0.7, 2.8, 3.3, 2.8)}},
        {"dolomitic-flat", Primitives{line(0.3, 1.0, 2.0, 1.0),
                                      line(0.0, 1.6, kTile, 1.6),
                                      line(0.3, 2.8, 2.0, 2.8),
                                      line(0.0, 3.4, kTile, 3.4)}},
        {"tidal-flat", Primitives{welllog::PatternPolyline{
                            .points = {{welllog::Millimetres{0.4}, welllog::Millimetres{2.0}},
                                       {welllog::Millimetres{1.3}, welllog::Millimetres{1.2}},
                                       {welllog::Millimetres{2.2}, welllog::Millimetres{2.8}},
                                       {welllog::Millimetres{3.6}, welllog::Millimetres{2.0}}},
                            .closed = false}}},
        // Shelves: horizontal single/double lines.
        {"muddy-shelf", Primitives{line(0.0, 1.3, kTile, 1.3),
                                   line(0.0, 2.7, kTile, 2.7)}},
        {"sandy-shelf", Primitives{line(0.0, 2.0, kTile, 2.0),
                                   circle(1.0, 2.9, 0.2, true),
                                   circle(3.0, 1.1, 0.2, true)}},
        {"sand-mud-shelf", Primitives{line(0.0, 1.3, kTile, 1.3),
                                      circle(1.0, 2.1, 0.2, true),
                                      line(0.0, 2.7, kTile, 2.7),
                                      circle(3.0, 3.4, 0.2, true)}},
        {"clastic-shelf", Primitives{line(0.0, 2.0, kTile, 2.0),
                                     line(1.0, 1.2, 3.0, 1.2)}},
        {"mixed", Primitives{line(0.0, 1.3, kTile, 1.3),
                             circle(1.2, 2.2, 0.24, true),
                             line(0.0, 2.9, kTile, 2.9),
                             circle(3.0, 0.6, 0.24, true)}},
        {"shelf", Primitives{line(0.0, 2.0, kTile, 2.0)}},
        // Deltaic: foreset chevrons.
        {"delta", Primitives{welllog::PatternPolyline{
                       .points = {{welllog::Millimetres{0.4}, welllog::Millimetres{2.6}},
                                  {welllog::Millimetres{1.6}, welllog::Millimetres{1.4}},
                                  {welllog::Millimetres{2.8}, welllog::Millimetres{2.6}}},
                       .closed = false},
                   welllog::PatternPolyline{
                       .points = {{welllog::Millimetres{0.4}, welllog::Millimetres{3.6}},
                                  {welllog::Millimetres{1.6}, welllog::Millimetres{2.4}},
                                  {welllog::Millimetres{2.8}, welllog::Millimetres{3.6}}},
                       .closed = false}}},
        {"shoreface", Primitives{line(0.0, 1.2, kTile, 1.2),
                                 line(0.0, 2.4, kTile, 2.4),
                                 line(0.0, 3.6, kTile, 3.6),
                                 circle(2.0, 0.6, 0.18, true)}},
        // Reef: clustered circles.
        {"reef", Primitives{circle(1.2, 1.2, 0.4, false),
                            circle(2.8, 1.6, 0.32, false),
                            circle(1.8, 3.0, 0.44, false)}},
        // Evaporite: cross-bed crystals.
        {"evaporite", Primitives{line(0.6, 0.8, 3.4, 3.2),
                                 line(3.4, 0.8, 0.6, 3.2),
                                 line(0.6, 0.8, 3.4, 0.8),
                                 line(0.6, 3.2, 3.4, 3.2)}},
        {"glacial", Primitives{welllog::PatternPolyline{
                        .points = {{welllog::Millimetres{0.4}, welllog::Millimetres{1.0}},
                                   {welllog::Millimetres{1.4}, welllog::Millimetres{2.0}},
                                   {welllog::Millimetres{0.9}, welllog::Millimetres{3.0}}},
                        .closed = false}}},
        {"volcanic", Primitives{line(0.0, 1.0, kTile, 1.0),
                                line(0.8, 1.0, 1.6, 2.6),
                                line(2.4, 1.0, 3.2, 2.6)}},
        {"metamorphic", Primitives{line(0.4, 0.6, 2.0, 2.0),
                                   line(2.0, 2.0, 3.6, 0.6),
                                   line(2.0, 2.0, 2.0, 3.6)}},
        {"alluvial", Primitives{welllog::PatternPolyline{
                         .points = {{welllog::Millimetres{0.4}, welllog::Millimetres{3.2}},
                                    {welllog::Millimetres{1.2}, welllog::Millimetres{1.6}},
                                    {welllog::Millimetres{2.0}, welllog::Millimetres{2.6}},
                                    {welllog::Millimetres{2.8}, welllog::Millimetres{0.8}}},
                         .closed = false}}},
        {"lagoon", Primitives{line(0.2, 1.4, 1.4, 1.4),
                              line(2.6, 1.4, 3.8, 1.4),
                              line(0.2, 2.8, 1.4, 2.8),
                              line(2.6, 2.8, 3.8, 2.8)}},
    };

    const auto found = kPrimitives.find(pattern_id);
    if (found == kPrimitives.end()) return std::nullopt;

    PatternDefinition definition;
    definition.id = id;
    definition.tile_width = welllog::Millimetres{kTile};
    definition.tile_height = welllog::Millimetres{kTile};
    definition.foreground = welllog::RgbaColor{40, 40, 40, 255};
    definition.background = welllog::RgbaColor{255, 255, 255, 0};
    definition.stroke_width = welllog::Millimetres{0.18};
    definition.scene_anchor = {};
    definition.primitives = found->second;
    definition.version = 1;
    return definition;
}

}  // namespace pwb::viz
