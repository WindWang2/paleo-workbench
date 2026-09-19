// Qt-free geological symbol registry V2 (CONV-27).
//
// Port of paleo_workbench/mapping/geological_symbols.py: the 15-entry §6
// symbol library (fault/facies/provenance/boundary), the alias resolution,
// the role/geometry binding validation, the fallback-style projection and
// the versioned whole-library document. Python semantics preserved:
//   * registry insertion order and sorted applicable_roles on dump;
//   * canonical_symbol_id alias resolution (4 legacy ids);
//   * validate_binding reason strings (role membership, then geometry
//     compatibility through the "vector" carrier rules);
//   * binding_record key order and source tag
//     "geological-symbols-v{version}/{symbol_id}";
//   * library_from_dict rejects other schema versions with the exact
//     Python message.
// LayerRole values travel as their plain strings (the Python enum values),
// so the Qt-free kernel needs no dependency on the workspace module.
#pragma once

#include <pwb/cartography/color_ramps.hpp>
#include <pwb/cartography/style_library.hpp>
#include <pwb/cartography/vector_style.hpp>
#include <pwb/domain/json.hpp>

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace pwb::cartography {

using Json = pwb::domain::Json;

inline constexpr long long kSymbolLibrarySchemaVersion = 2;

struct GeologicalSymbolDef {
    std::string symbol_id;
    long long version = 2;
    std::string title;
    std::string category;                   // fault | facies | provenance | boundary
    std::vector<std::string> applicable_roles;  // LayerRole value strings
    std::string geometry_kind;              // point | line | polygon
    VectorStyle legacy_fallback;
    Json renderer_hint;                     // renderer_kind/field/rules (+extras)
    Json metadata;                          // declaration-only extras

    // Python __post_init__ validation; throws std::invalid_argument with
    // the exact Python ValueError messages.
    void validate() const;

    Json to_dict() const;
    static GeologicalSymbolDef from_dict(const Json& data);

    // The V1 StyleEntry projection used for registration/apply.
    StyleEntry style_entry() const;
};

// Facies pattern table (facies_patterns.FACIES_PATTERN_MAP): exact lookup
// after whitespace-strip; nullopt when unmapped (volcanic/other).
std::optional<std::string> pattern_id_for_facies(const std::string& name);

// ---- registry -----------------------------------------------------------------

const std::vector<std::pair<std::string, GeologicalSymbolDef>>&
geological_symbols();

std::string canonical_symbol_id(const std::string& symbol_id);

// Lookup with alias resolution; throws std::out_of_range with the Python
// KeyError message (available ids sorted).
const GeologicalSymbolDef& symbol_by_id(const std::string& symbol_id);

// All symbols accepting the role, registry order.
std::vector<const GeologicalSymbolDef*> symbols_for_role(
    const std::string& role);

// (ok, reason); reason is "ok" on success.
std::pair<bool, std::string> validate_binding(const std::string& symbol_id,
                                              const std::string& role,
                                              const std::string& geometry_kind);

long long library_version();

// Flat VectorStyle dict of the fallback with keyword overrides (VectorStyle
// field names; line_pattern/marker accept their string values). Unknown
// fields throw std::invalid_argument like Python's dataclass replace().
Json legacy_style_for_symbol(const std::string& symbol_id,
                             const Json& overrides = Json());

// The style<->science traceability record stored as "style_binding".
Json binding_record(const std::string& symbol_id,
                    const Json& field_values = Json());

StyleEntry style_entry_for_symbol(const std::string& symbol_id);

// ---- V1 coexistence --------------------------------------------------------------

// Register every V2 symbol as a StyleEntry into a V1 library copy (the
// 12 built-in entries are never replaced); returns the keys written, in
// registry order. Library is keyed "{category}.{key}".
std::vector<std::string> register_symbols_into_style_library(
    std::vector<std::pair<std::string, StyleEntry>>& library);

// Reverse registration; returns the keys removed.
std::vector<std::string> unregister_symbols_from_style_library(
    std::vector<std::pair<std::string, StyleEntry>>& library);

// ---- library serialization ------------------------------------------------------

inline constexpr const char* kSymbolCategories[4] = {"fault", "facies",
                                                     "provenance", "boundary"};

Json symbol_library_document();  // {"schema_version": 2, "symbols": [...]}
// Parse a whole-library document; throws std::invalid_argument on schema
// mismatch. Returns defs in document order.
std::vector<std::pair<std::string, GeologicalSymbolDef>>
parse_symbol_library_document(const Json& document);

// LayerRole vocabulary membership (mapping_workspace/layer_roles.py values).
bool is_known_layer_role(const std::string& role);

}  // namespace pwb::cartography
