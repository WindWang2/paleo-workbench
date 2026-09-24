#include "pwb/project/schema.hpp"

#include <algorithm>

namespace pwb::project {

namespace {

using pwb::domain::Diagnostic;
using pwb::domain::DiagnosticList;
using pwb::domain::Json;

bool normalize_value(Json& value, const FieldSpec& field,
                     DiagnosticList& diagnostics);


bool fail(DiagnosticList& diagnostics, const FieldSpec& field,
          const std::string& problem) {
    diagnostics.push_back(Diagnostic::error(
        "schema_violation",
        "field '" + std::string(field.name) + "': " + problem));
    return false;
}

bool coerce_double(Json& value) {
    if (value.is_number_float()) return true;
    if (value.is_number_integer()) {
        const double as_double =
            value.is_number_unsigned()
                ? static_cast<double>(value.get<std::uint64_t>())
                : static_cast<double>(value.get<std::int64_t>());
        value = as_double;
        return true;
    }
    return false;
}

bool coerce_int(Json& value) {
    if (value.is_number_integer()) return true;
    if (value.is_number_float()) {
        const double d = value.get<double>();
        if (std::floor(d) == d && std::abs(d) < 9.2e18) {
            value = static_cast<std::int64_t>(d);
            return true;
        }
    }
    return false;
}

}  // namespace

bool normalize(Json& object, const ModelSpec& spec,
               DiagnosticList& diagnostics) {
    if (!object.is_object()) {
        diagnostics.push_back(Diagnostic::error(
            "schema_violation",
            std::string(spec.name) + ": expected object"));
        return false;
    }
    bool ok = true;
    Json result = Json::object();
    // Pass 1: declared fields in spec order (insert defaults when absent).
    for (const FieldSpec& field : *spec.fields) {
        const std::string key(field.name);
        if (!object.contains(key)) {
            if (field.type == FieldType::Nested) {
                Json fresh = Json::object();
                ok &= normalize(fresh, field.nested, diagnostics);
                result[key] = std::move(fresh);
            } else if (!field.default_value.is_null() ||
                       field.type == FieldType::JsonValueOrNull ||
                       field.type == FieldType::JsonMapOrNull ||
                       field.type == FieldType::StringOrNull ||
                       field.type == FieldType::IntOrNull ||
                       field.type == FieldType::DoubleOrNull ||
                       field.type == FieldType::NestedOrNull) {
                result[key] = field.default_value.is_null()
                                  ? Json(nullptr)
                                  : field.default_value;
            } else {
                ok &= fail(diagnostics, field, "required field missing");
                result[key] = nullptr;
            }
            continue;
        }
        Json value = std::move(object.at(key));
        ok &= normalize_value(value, field, diagnostics);
        result[key] = std::move(value);
    }
    // Pass 2: unknown keys preserved after the declared block.
    for (auto it = object.begin(); it != object.end(); ++it) {
        bool declared = false;
        for (const FieldSpec& field : *spec.fields) {
            if (field.name == it.key()) {
                declared = true;
                break;
            }
        }
        if (!declared) result[it.key()] = std::move(it.value());
    }
    object = std::move(result);
    return ok;
}

namespace {

bool normalize_value(Json& value, const FieldSpec& field,
                     DiagnosticList& diagnostics) {
    const bool nullable =
        field.type == FieldType::StringOrNull ||
        field.type == FieldType::IntOrNull ||
        field.type == FieldType::DoubleOrNull ||
        field.type == FieldType::JsonMapOrNull ||
        field.type == FieldType::JsonValueOrNull ||
        field.type == FieldType::NestedOrNull;
    if (value.is_null()) {
        return nullable ? true
                        : fail(diagnostics, field, "null not allowed here");
    }
    switch (field.type) {
        case FieldType::String:
            if (!value.is_string())
                return fail(diagnostics, field, "expected string");
            return true;
        case FieldType::StringOrNull:
            return value.is_string()
                       ? true
                       : fail(diagnostics, field, "expected string|null");
        case FieldType::Int:
        case FieldType::IntOrNull:
            if (!coerce_int(value))
                return fail(diagnostics, field, "expected integer");
            return true;
        case FieldType::Double:
        case FieldType::DoubleOrNull:
            if (!coerce_double(value))
                return fail(diagnostics, field, "expected number");
            return true;
        case FieldType::Bool:
            if (!value.is_boolean())
                return fail(diagnostics, field, "expected boolean");
            return true;
        case FieldType::StringList:
        case FieldType::IntList: {
            if (!value.is_array())
                return fail(diagnostics, field, "expected array");
            bool ok = true;
            for (auto& item : value) {
                if (field.type == FieldType::StringList) {
                    if (!item.is_string()) {
                        diagnostics.push_back(Diagnostic::error(
                            "schema_violation",
                            "field '" + std::string(field.name) +
                                "': expected string element"));
                        ok = false;
                    }
                } else if (!coerce_int(item)) {
                    ok = false;
                }
            }
            return ok;
        }
        case FieldType::DoubleList:
        case FieldType::DoubleGrid: {
            if (!value.is_array())
                return fail(diagnostics, field, "expected array");
            bool ok = true;
            for (auto& item : value) {
                if (field.type == FieldType::DoubleList) {
                    if (!coerce_double(item)) {
                        fail(diagnostics, field, "expected number element");
                        ok = false;
                    }
                } else {
                    if (!item.is_array()) {
                        fail(diagnostics, field,
                             "expected [[number]] grid element");
                        ok = false;
                        continue;
                    }
                    for (auto& coord : item) {
                        if (!coerce_double(coord)) {
                            fail(diagnostics, field,
                                 "expected number in grid element");
                            ok = false;
                        }
                    }
                }
            }
            return ok;
        }
        case FieldType::StringMap:
            if (!value.is_object())
                return fail(diagnostics, field, "expected object");
            for (auto& item : value) {
                if (!item.is_string())
                    return fail(diagnostics, field, "expected string value");
            }
            return true;
        case FieldType::JsonMap:
        case FieldType::JsonMapOrNull:
            if (!value.is_object())
                return fail(diagnostics, field, "expected object");
            return true;
        case FieldType::JsonList:
            if (!value.is_array())
                return fail(diagnostics, field, "expected array");
            return true;
        case FieldType::JsonValue:
        case FieldType::JsonValueOrNull:
            return true;
        case FieldType::StrictEnum: {
            if (!value.is_string())
                return fail(diagnostics, field, "expected enum string");
            const std::string current = value.get<std::string>();
            for (auto allowed : field.vocab) {
                if (allowed == current) return true;
            }
            return fail(diagnostics, field,
                        "unknown enum value '" + current + "'");
        }
        case FieldType::LenientEnum: {
            if (!value.is_string()) {
                value = field.default_value;
                return true;
            }
            const std::string current = value.get<std::string>();
            for (auto allowed : field.vocab) {
                if (allowed == current) return true;
            }
            value = field.default_value;  // Python from_dict fallback
            return true;
        }
        case FieldType::Nested:
            return normalize(value, field.nested, diagnostics);
        case FieldType::NestedOrNull:
            if (!value.is_object())
                return fail(diagnostics, field, "expected object|null");
            return normalize(value, field.nested, diagnostics);
        case FieldType::NestedList: {
            if (!value.is_array())
                return fail(diagnostics, field, "expected array");
            bool ok = true;
            for (auto& item : value) {
                if (!item.is_object()) {
                    diagnostics.push_back(Diagnostic::error(
                        "schema_violation",
                        "field '" + std::string(field.name) +
                            "': expected object element"));
                    ok = false;
                    continue;
                }
                ok &= normalize(item, field.nested, diagnostics);
            }
            return ok;
        }
    }
    return fail(diagnostics, field, "unhandled field type");
}

}  // namespace

bool validates_against(const Json& object, const ModelSpec& spec) {
    if (!object.is_object()) return false;
    DiagnosticList sink;
    Json copy = object;
    return normalize(copy, spec, sink);
}

// ---------------------------------------------------------------------------
// Spec tables — transcribed field-by-field from paleo_workbench/project/
// models.py + domain.py (baseline d0347da2). Defaults are Python defaults.
// ---------------------------------------------------------------------------

namespace specs {

const std::vector<FieldSpec> kProjectMeta{
    {"name", FieldType::String},
    {"region", FieldType::String, ""},
    {"version", FieldType::String, "0.2.17a0"},
    {"created_at", FieldType::String, ""},
    {"updated_at", FieldType::String, ""},
    {"project_root", FieldType::String, "."},
    {"last_recovery", FieldType::JsonValueOrNull, nullptr},
};

const std::vector<FieldSpec> kCoordinate{
    {"project_crs", FieldType::String, ""},
    {"crs_locked", FieldType::Bool, false},
    {"target_crs", FieldType::StringOrNull, nullptr},
    {"display_crs", FieldType::String, "EPSG:4326 / WGS84"},
    {"transform_history", FieldType::JsonList, Json::array()},
};

const std::vector<FieldSpec> kStratigraphy{
    {"target_horizon", FieldType::String, ""},
    {"sequence_boundaries", FieldType::StringList, Json::array()},
    {"systems_tract_scheme", FieldType::String, "LST/TST/HST"},
    {"interpretation_version", FieldType::String, "v1"},
    {"applicable_wells", FieldType::StringList, Json::array()},
    {"applicable_seismic_ranges", FieldType::StringList, Json::array()},
};

const std::vector<FieldSpec> kWorkArea{
    {"id", FieldType::String, ""},
    {"name", FieldType::String, ""},
    {"description", FieldType::String, ""},
    {"boundary", FieldType::DoubleGrid, Json::array()},
    {"boundary_crs", FieldType::String, ""},
    {"project_crs", FieldType::String, ""},
    {"display_crs", FieldType::String, ""},
    {"vertical_datum", FieldType::String, ""},
    {"horizontal_units", FieldType::String, ""},
    {"vertical_units", FieldType::String, ""},
    {"metadata", FieldType::JsonMap, Json::object()},
    {"created_at", FieldType::String, ""},
    {"updated_at", FieldType::String, ""},
};

const std::vector<FieldSpec> kWellEntity{
    {"id", FieldType::String, ""},
    {"name", FieldType::String},
    {"uwi", FieldType::String, ""},
    {"aliases", FieldType::StringList, Json::array()},
    {"surface_x", FieldType::DoubleOrNull, nullptr},
    {"surface_y", FieldType::DoubleOrNull, nullptr},
    {"surface_z", FieldType::DoubleOrNull, nullptr},
    {"source_crs", FieldType::String, ""},
    {"project_x", FieldType::DoubleOrNull, nullptr},
    {"project_y", FieldType::DoubleOrNull, nullptr},
    {"coordinate_status", FieldType::String, "missing"},
    {"kb", FieldType::DoubleOrNull, nullptr},
    {"td", FieldType::DoubleOrNull, nullptr},
    {"status", FieldType::String, "active"},
    {"spatial_scope", FieldType::StrictEnum,
     "workarea", {"workarea", "reference"}},
    {"tags", FieldType::StringList, Json::array()},
    {"metadata", FieldType::JsonMap, Json::object()},
    {"created_at", FieldType::String, ""},
    {"updated_at", FieldType::String, ""},
};

const std::vector<FieldSpec> kSeismicSurvey{
    {"id", FieldType::String, ""},
    {"name", FieldType::String},
    {"survey_type", FieldType::StrictEnum, "3d", {"3d", "2d"}},
    {"crs", FieldType::String, ""},
    {"extent", FieldType::DoubleGrid, Json::array()},
    {"inline_range", FieldType::DoubleList, Json::array()},
    {"crossline_range", FieldType::DoubleList, Json::array()},
    {"n_samples", FieldType::IntOrNull, nullptr},
    {"dt_ms", FieldType::DoubleOrNull, nullptr},
    {"metadata", FieldType::JsonMap, Json::object()},
    {"created_at", FieldType::String, ""},
    {"updated_at", FieldType::String, ""},
};

const std::vector<FieldSpec> kDomainEntity{
    {"id", FieldType::String, ""},
    {"kind", FieldType::StrictEnum,
     "geological", {"geological", "auxiliary"}},
    {"name", FieldType::String},
    {"entity_kind", FieldType::String, ""},
    {"description", FieldType::String, ""},
    {"metadata", FieldType::JsonMap, Json::object()},
    {"created_at", FieldType::String, ""},
    {"updated_at", FieldType::String, ""},
};

const std::vector<FieldSpec> kEntityAssetLink{
    {"id", FieldType::String, ""},
    {"entity_type", FieldType::StrictEnum,
     "well",
     {"well", "seismic_survey", "geological_entity", "auxiliary_entity"}},
    {"entity_id", FieldType::String},
    {"asset_id", FieldType::String},
    {"role", FieldType::String, "other"},
    {"is_primary", FieldType::Bool, false},
    {"unresolved", FieldType::Bool, false},
    // V14-DATA-LINEAGE: role-internal ordering (e.g. multi-LAS load
    // order). Default 0 keeps pre-V14 documents byte-stable through
    // normalize; Python legacy reads unknown keys tolerantly.
    {"ordinal", FieldType::Int, 0},
    {"note", FieldType::String, ""},
    {"metadata", FieldType::JsonMap, Json::object()},
    {"created_at", FieldType::String, ""},
};

const std::vector<FieldSpec> kResourceItem{
    {"id", FieldType::String, ""},
    {"name", FieldType::String},
    {"path", FieldType::String},
    {"type", FieldType::String, ""},
    {"format", FieldType::String, ""},
    {"crs", FieldType::StringOrNull, nullptr},
    {"status", FieldType::String, "indexed"},
    {"tags", FieldType::StringList, Json::array()},
    {"source", FieldType::String, "local"},
    {"parsed_summary", FieldType::JsonMap, Json::object()},
    {"checksum", FieldType::StringOrNull, nullptr},
    {"external", FieldType::Bool, false},
    {"artifact_role", FieldType::StringOrNull, nullptr},
};

const std::vector<FieldSpec> kUserVectorFeature{
    {"id", FieldType::String},
    {"geometry", FieldType::JsonMap, Json::object()},
    {"properties", FieldType::JsonMap, Json::object()},
};

const std::vector<FieldSpec> kUserVectorLayer{
    {"id", FieldType::String, ""},
    {"name", FieldType::String, "编修图层"},
    {"geometry_kind", FieldType::StrictEnum,
     "line", {"point", "line", "polygon"}},
    {"template", FieldType::String, ""},
    {"crs", FieldType::String, ""},
    {"style", FieldType::JsonMap, Json::object()},
    {"field_schema", FieldType::JsonMap, Json::object()},
    {"features", FieldType::NestedList, Json::array(),
     {}, ModelSpec{"UserVectorFeature", &kUserVectorFeature}},
    {"visible", FieldType::Bool, true},
    {"opacity", FieldType::Double, 1.0},
};


const ModelSpec kMetaSpec{"ProjectMeta", &kProjectMeta};
const ModelSpec kCoordinateSpec{"CoordinateReference", &kCoordinate};
const ModelSpec kStratigraphySpec{"StratigraphicFramework", &kStratigraphy};
const ModelSpec kWorkAreaSpec{"WorkArea", &kWorkArea};
const ModelSpec kWellSpec{"WellEntity", &kWellEntity};
const ModelSpec kSurveySpec{"SeismicSurveyEntity", &kSeismicSurvey};
const ModelSpec kDomainEntitySpec{"DomainEntity", &kDomainEntity};
const ModelSpec kLinkSpec{"EntityAssetLink", &kEntityAssetLink};
const ModelSpec kResourceSpec{"ResourceItem", &kResourceItem};
const ModelSpec kUserVectorLayerSpec{"UserVectorLayer", &kUserVectorLayer};

// Python-parity defaults for the two sections Python materializes on
// ProjectDocument.new (see kProjectDocument below). Function-local statics
// avoid static-init-order hazards and a discarded parse degrades to an
// empty object instead of poisoning the spec.
Json joint_analysis_default() {
    static const Json value = [] {
        Json parsed = Json::parse(
            std::string(R"({"tree_checks":{},"well_visibility":{},)")
                + R"("well_identity_asset_id":null,"well_identity_map":{},)"
                + R"("seismic_color_scale":"blue-white-red",)"
                + R"("gr_color_scale":"viridis","well_width_px":5,)"
                + R"("orthogonal_inline_index":null,)"
                + R"("orthogonal_crossline_index":null,)"
                + R"("orthogonal_inline_number":null,)"
                + R"("orthogonal_crossline_number":null,"time_slices":[],)"
                + R"("active_time_slice_ms":null,"time_slice_opacity":80,)"
                + R"("vertical_domain":"Time","active_fence_wells":[],)"
                + R"("active_fence_name":null,"path_hints":{}})",
            nullptr, false);
        return parsed.is_discarded() ? Json::object() : parsed;
    }();
    return value;
}

Json geo3d_workspace_default() {
    static const Json value = [] {
        Json parsed = Json::parse(
            std::string(R"({"objects":[],"measurements":[],"display":{},)")
                + R"("clip":{},"camera":{},"views":[],"selected":""})",
            nullptr, false);
        return parsed.is_discarded() ? Json::object() : parsed;
    }();
    return value;
}

// Top-level ProjectDocument. meta is REQUIRED; everything else carries a
// default. Long-tail business sections (well_tables, contour_drafts, …)
// stay JsonList envelopes: they round-trip verbatim and are explicitly
// documented as lossless-pass-through (baseline.md §5).
const std::vector<FieldSpec> kProjectDocument{
    {"schema_version", FieldType::Int, 1},
    {"meta", FieldType::Nested, nullptr, {}, kMetaSpec},
    {"coordinate", FieldType::Nested, nullptr, {}, kCoordinateSpec},
    {"stratigraphy", FieldType::Nested, nullptr, {}, kStratigraphySpec},
    {"facies_taxonomy", FieldType::JsonMapOrNull, nullptr},
    {"workarea", FieldType::NestedOrNull, nullptr, {}, kWorkAreaSpec},
    {"wells", FieldType::NestedList, Json::array(), {}, kWellSpec},
    {"seismic_surveys", FieldType::NestedList, Json::array(), {},
     kSurveySpec},
    {"geological_entities", FieldType::NestedList, Json::array(), {},
     kDomainEntitySpec},
    {"auxiliary_entities", FieldType::NestedList, Json::array(), {},
     kDomainEntitySpec},
    {"entity_asset_links", FieldType::NestedList, Json::array(), {},
     kLinkSpec},
    {"resources", FieldType::NestedList, Json::array(), {}, kResourceSpec},
    {"well_tables", FieldType::JsonList, Json::array()},
    {"constraint_layers", FieldType::JsonList, Json::array()},
    {"map_products", FieldType::JsonList, Json::array()},
    {"contour_drafts", FieldType::JsonList, Json::array()},
    {"compilation_runs", FieldType::JsonList, Json::array()},
    {"factor_map_tasks", FieldType::JsonList, Json::array()},
    {"horizon_interpretations", FieldType::JsonList, Json::array()},
    {"correlation_interpretations", FieldType::JsonList, Json::array()},
    {"fault_interpretations", FieldType::JsonList, Json::array()},
    {"prediction_tasks", FieldType::JsonList, Json::array()},
    {"paleomap_documents", FieldType::JsonList, Json::array()},
    {"user_vector_layers", FieldType::NestedList, Json::array(), {},
     kUserVectorLayerSpec},
    // RETIRED (QGIS-native data-management convergence):
    //   * map_qgis_project_xml — the inline QGIS-project XML envelope was
    //     never written by the native shell; GIS state now lives in the
    //     sibling .qgs file referenced by
    //     mapping_workspace.qgis_project_file. Legacy documents carrying
    //     the section round-trip it verbatim (unknown-key pass-through).
    //   * workstation_reference_layers — dead self-built datasource
    //     description (no writer since the C++ migration; reference
    //     layers are QgsProject layers now). Same verbatim legacy
    //     round-trip; QA readers treat absence as an empty list.
    {"onboarding_report", FieldType::JsonMap, Json::object()},
    {"quality_reports", FieldType::JsonList, Json::array()},
    {"version_sets", FieldType::JsonList, Json::array()},
    {"export_artifacts", FieldType::JsonList, Json::array()},
    // joint_analysis / geo3d_workspace: Python materializes full defaults
    // on ProjectDocument.new (fixtures carry them as objects). Without a
    // default here, create_new() emits null, which parse() rejects — the
    // defaults below are the frozen Python parity content (minimal
    // fixture, oracle-regenerated 2026-09-16).
    {"joint_analysis", FieldType::JsonValue, joint_analysis_default()},
    {"geo3d_workspace", FieldType::JsonValue, geo3d_workspace_default()},
    {"mapping_workspace", FieldType::JsonMap, Json::object()},
    {"compilation_input_sets", FieldType::JsonList, Json::array()},
    {"integrated_interpretations", FieldType::JsonList, Json::array()},
    {"interpretation_revisions", FieldType::JsonList, Json::array()},
};

const ModelSpec kDocumentSpec{"ProjectDocument", &kProjectDocument};

}  // namespace specs

const ModelSpec& project_document_spec() { return specs::kDocumentSpec; }
const ModelSpec& project_meta_spec() { return specs::kMetaSpec; }
const ModelSpec& coordinate_reference_spec() { return specs::kCoordinateSpec; }
const ModelSpec& resource_item_spec() { return specs::kResourceSpec; }
const ModelSpec& user_vector_layer_spec() {
    return specs::kUserVectorLayerSpec;
}
const ModelSpec& workarea_spec() { return specs::kWorkAreaSpec; }
const ModelSpec& well_entity_spec() { return specs::kWellSpec; }
const ModelSpec& seismic_survey_spec() { return specs::kSurveySpec; }
const ModelSpec& domain_entity_spec() { return specs::kDomainEntitySpec; }
const ModelSpec& entity_asset_link_spec() { return specs::kLinkSpec; }

}  // namespace pwb::project
