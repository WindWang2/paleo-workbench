// Declarative pydantic-parity schema machinery (schema-map.md §1/§6/§7).
//
// Each Python BaseModel is described by a ModelSpec table. `normalize()`
// reproduces pydantic's observable load semantics on the JSON tree:
//   - missing declared fields get their defaults inserted IN FIELD ORDER;
//   - lax coercions match pydantic v2 (int->double, integral double->int);
//   - strict Literal enums reject unknown values (Diagnostic, load fails);
//   - lenient enums replace unknown values with the fallback (dataclass
//     from_dict behavior — LayerRole/stage/binding kinds);
//   - unknown keys are PRESERVED after the declared block (superset of
//     Python, which drops them at non-extra levels — recorded in §7).
//
// The typed C++ views (ProjectMeta etc.) read the SAME normalized tree, so
// there is exactly one schema definition per model, as data.
#pragma once

#include "pwb/domain/diagnostics.hpp"
#include "pwb/domain/json.hpp"

#include <map>
#include <string>
#include <string_view>
#include <vector>

namespace pwb::project {

using pwb::domain::Json;

enum class FieldType {
    String,          // "x" — null/other → error
    Int,             // pydantic int (lax integral double ok)
    Double,          // pydantic float (lax int ok)
    Bool,
    StringOrNull,    // str | null
    IntOrNull,
    DoubleOrNull,
    StringList,      // [str]
    DoubleList,      // [double] ([[x,y],..] containers use DoubleGrid)
    DoubleGrid,      // [[double]]
    IntList,
    StringMap,       // {str: str}
    JsonMap,         // {str: any} — dict carrier, verbatim
    JsonMapOrNull,   // dict | null
    JsonList,        // [any] — list carrier, verbatim
    JsonValue,       // any — verbatim
    JsonValueOrNull, // any | null
    StrictEnum,      // string in vocab, else load error
    LenientEnum,     // string in vocab else fallback replacement
    Nested,          // nested ModelSpec object
    NestedOrNull,    // nested object | null
    NestedList,      // [nested object]
};

struct FieldSpec;

struct ModelSpec {
    std::string_view name;
    const std::vector<FieldSpec>* fields = nullptr;
};

struct FieldSpec {
    std::string_view name;
    FieldType type = FieldType::JsonValue;
    pwb::domain::Json default_value = nullptr;  // primitive defaults
    std::vector<std::string_view> vocab;        // enum vocabularies
    ModelSpec nested{};                          // Nested* targets
};

// Normalizes `object` in place against `spec`. Returns false when a strict
// constraint failed (the object may still be partially normalized — callers
// treat a failure as a load error, matching pydantic ValidationError).
bool normalize(Json& object, const ModelSpec& spec,
               pwb::domain::DiagnosticList& diagnostics);

// True when every declared field of `object` is present and well-typed
// (used to validate .bak candidates before any file is moved).
bool validates_against(const Json& object, const ModelSpec& spec);

// -- spec registry -----------------------------------------------------------

const ModelSpec& project_document_spec();
const ModelSpec& project_meta_spec();
const ModelSpec& coordinate_reference_spec();
const ModelSpec& resource_item_spec();
const ModelSpec& user_vector_layer_spec();
const ModelSpec& workarea_spec();
const ModelSpec& well_entity_spec();
const ModelSpec& seismic_survey_spec();
const ModelSpec& domain_entity_spec();
const ModelSpec& entity_asset_link_spec();

}  // namespace pwb::project
