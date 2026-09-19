#pragma once

// Port of paleo_workbench/mapping_workspace/geological_layer_spec.py
// (UI-13): declarative, QGIS-drivable layer specifications for every
// geological layer role — the ONE formal binding between LayerRole
// (science vocabulary), the runtime layer type vocabulary, and the QGIS
// layer schema (fields_json wire payload, see qgis_layer_schema.hpp).
//
// Policies (edit / snapping / topology / stage / maturity / provenance)
// derive from the existing authorities (ROLE_EDITABLE, ROLE_RAW_PROTECTED,
// stages_for_role) instead of duplicating them. Pure data — no Qt, no
// QGIS import.

#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/tool_policy/stages.hpp>

namespace pwb::ui_composite {

using pwb::domain::Json;
using tool_policy::MappingStage;

// Field-level description (generalizes composite TemplateField).
// kind ∈ text/int/real/bool/datetime; choices = closed value domain
// (QGIS ValueMap); value_range = numeric range (QGIS Range bounds);
// required + expression → QGIS field constraints; default seeds new
// features during digitizing.
struct SpecField {
    std::string name;
    std::string label;
    std::string kind = "text";
    std::optional<int> length;
    std::optional<int> precision;
    std::vector<std::string> choices;
    std::optional<std::pair<double, double>> value_range;
    Json default_value;
    bool required = false;
    bool unique = false;
    std::string expression;
    std::optional<std::string> editor_widget;

    Json to_dict() const;
    static SpecField from_dict(const Json& data);

    bool operator==(const SpecField&) const = default;
};

struct EditPolicy {
    bool editable = false;
    bool raw_protected = false;
    bool allow_geometry_edit = true;
    bool allow_attribute_edit = true;

    Json to_dict() const;
    static EditPolicy from_dict(const Json& data);
    bool operator==(const EditPolicy&) const = default;
};

struct SnappingPolicy {
    bool enabled = false;
    std::vector<std::string> modes = {"vertex"};
    double tolerance = 10.0;
    std::string unit = "pixels";
    bool topological = false;

    Json to_dict() const;
    static SnappingPolicy from_dict(const Json& data);
    bool operator==(const SnappingPolicy&) const = default;
};

struct TopologyPolicy {
    bool validate_on_flush = true;
    std::vector<std::string> rules = {"ring_closure"};

    Json to_dict() const;
    static TopologyPolicy from_dict(const Json& data);
    bool operator==(const TopologyPolicy&) const = default;
};

struct StagePolicy {
    std::vector<MappingStage> visible_stages;
    std::vector<MappingStage> locked_stages;
    bool operator==(const StagePolicy&) const = default;
};

struct MaturityPolicy {
    bool track = true;
    std::string initial = "draft";
    bool operator==(const MaturityPolicy&) const = default;
};

// mode: catalog_version_pinned — pins a catalog DataVersion (factors);
//       content_fingerprint — content hashed for freshness (constraints);
//       session_only — ephemeral view layers.
struct ProvenancePolicy {
    std::string mode = "session_only";
    bool pins_inputs = false;
    bool operator==(const ProvenancePolicy&) const = default;
};

struct RendererBinding {
    std::string style_id;
    std::string fallback_style;
    // single|categorized|graduated|pseudocolor|rule_based
    std::string renderer_kind = "single";
    std::optional<std::string> field;

    Json to_dict() const;
    static RendererBinding from_dict(const Json& data);
    bool operator==(const RendererBinding&) const = default;
};

struct LabelBinding {
    bool enabled = false;
    std::optional<std::string> field;
    std::optional<std::string> size_field;
    std::optional<std::string> color_field;
    std::optional<std::string> rotation_field;

    Json to_dict() const;
    static LabelBinding from_dict(const Json& data);
    bool operator==(const LabelBinding&) const = default;
};

struct ScaleVisibility {
    std::optional<int> min_scale;  // visible when scale <= min
    std::optional<int> max_scale;  // visible when scale >= max

    Json to_dict() const;
    static ScaleVisibility from_dict(const Json& data);
    bool operator==(const ScaleVisibility&) const = default;
};

struct GeologicalLayerSpec {
    std::string spec_id;
    std::string role;                 // LayerRole value
    std::string geometry_kind;        // point|line|polygon|raster|vector
    std::string title;
    std::vector<SpecField> fields;
    std::optional<EditPolicy> edit_policy;
    std::optional<SnappingPolicy> snapping_policy;
    std::optional<TopologyPolicy> topology_policy;
    std::optional<StagePolicy> stage_policy;
    std::optional<MaturityPolicy> maturity_policy;
    std::optional<ProvenancePolicy> provenance_policy;
    std::optional<RendererBinding> renderer_binding;
    std::optional<LabelBinding> label_binding;
    std::optional<ScaleVisibility> scale_visibility;
    std::optional<std::string> constraint_kind;  // ConstraintKind value
    std::optional<std::string> factor_child;

    Json to_dict() const;
    static GeologicalLayerSpec from_dict(const Json& data);

    // Convert fields to the existing TemplateField schema consumed by
    // composite editing (name/kind/choices/default/required survive).
    Json to_template_schema() const;

    bool operator==(const GeologicalLayerSpec&) const = default;
};

// The registry (role → spec); function-local so construction order is
// defined.
const std::map<std::string, GeologicalLayerSpec>& geological_layer_specs();

// Spec for a role; unknown roles are an error, never a silent default
// (throws std::out_of_range — Python KeyError parity).
const GeologicalLayerSpec& spec_for_role(const std::string& role_value);

// Roles bound to a geological constraint kind (usually one).
std::vector<std::string> specs_for_constraint_kind(
    const std::string& kind_value);

// Primary runtime layer-type string for a role (LayerType vocabulary is
// plain str on the wire). Unknown → "".
std::string layer_type_for_role(const std::string& role_value);

// Default (typical) role for a runtime document type; the layer's true
// role always lives in its membership record — this is the type-level
// binding, not a per-layer classification. Unknown → nullopt.
std::optional<std::string> role_for_layer_type(
    const std::string& layer_type);

}  // namespace pwb::ui_composite
