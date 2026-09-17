// Qt-free MapDocument JSON kernel (CONV-02).
//
// Port of the serialization contract of paleo_workbench/mapping/layers.py:
// MapDocument + the polymorphic layer hierarchy, as pure data. The Python
// side only ever *writes* these documents (to_dict); there is no Python
// loader, so the read side here is the contract defined in
// docs/development/cpp-conversion-swarm-20/ledgers/02-decisions.md (D-03):
// known keys fill dataclass defaults when absent, unknown keys are preserved
// in `extras` and re-emitted after the declared fields (never dropped).
//
// `style` / `metadata` / `features` / `annotations` are opaque ordered_json
// payloads: parsed documents round-trip them verbatim (key order and
// int/float shape included) — see decision D-07.
#pragma once

#include <pwb/domain/json.hpp>

#include <array>
#include <optional>
#include <string>
#include <vector>

namespace pwb::mapping_document {

using Json = pwb::domain::Json;

struct MapLayer {
    std::string id;
    std::string name = "Untitled Layer";
    std::string layer_type = "vector";
    std::array<double, 4> extent{0.0, 0.0, 1.0, 1.0};
    std::string crs;
    long long data_revision = 1;
    long long style_revision = 1;
    bool visible = true;
    double opacity = 1.0;
    bool has_scale_range = false;
    double scale_range_min = 0.0;
    double scale_range_max = 0.0;
    Json style;      // object payload, verbatim
    Json metadata;   // object payload, verbatim
    std::string source_version_id;
    Json features = Json::array();     // array payload for the vector family
    Json annotations = Json::array();  // array payload for annotation layers
    Json extras;       // unknown keys from the input, order preserved

};

// The sentinel extent (0, 0, 1, 1): layers still carrying it are excluded
// from MapDocument::recompute_extent (layers.py contract).
inline constexpr std::array<double, 4> kSentinelExtent{0.0, 0.0, 1.0, 1.0};

struct MapDocument {
    std::string id;
    std::string title = "Paleogeographic Map";
    std::string crs = "EPSG:4326";
    std::array<double, 4> extent{0.0, 0.0, 1.0, 1.0};
    std::vector<MapLayer> layers;
    Json metadata;  // object payload, verbatim
    bool has_active_layer = false;
    std::string active_layer_id;
    Json extras;  // unknown top-level keys, order preserved
};

// Throws std::invalid_argument when a known scalar cannot be coerced
// (mirrors the uncaught ValueError of the Python numeric paths).
MapLayer parse_layer(const Json& payload);
Json dump_layer(const MapLayer& layer);

MapDocument parse_map_document(const Json& payload);
Json dump_map_document(const MapDocument& doc);

// Document operations ported from MapDocument (layers.py). add/remove
// re-run recompute_extent exactly like the Python methods.
MapLayer* find_layer(MapDocument& doc, const std::string& layer_id);
void add_layer(MapDocument& doc, MapLayer layer,
               std::optional<std::size_t> position = std::nullopt);
// Returns the removed layer (Python returns it; nullopt when the id is
// unknown — no exception).
std::optional<MapLayer> remove_layer(MapDocument& doc,
                                     const std::string& layer_id);
// Python semantics: given ids first (duplicates skip), leftovers keep their
// previous relative order.
void reorder_layers(MapDocument& doc,
                    const std::vector<std::string>& layer_ids);
// Union of the visible, non-sentinel layer extents; leaves the document
// extent untouched when no layer qualifies.
std::array<double, 4> recompute_extent(MapDocument& doc);
// metadata["input_version_ids"] verbatim (the Python property seeds its
// result with that list untouched, internal duplicates included; only layer
// source_version_ids are appended first-wins). Returned as JSON so the
// verbatim entries survive.
Json input_version_ids(const MapDocument& doc);

}  // namespace pwb::mapping_document
