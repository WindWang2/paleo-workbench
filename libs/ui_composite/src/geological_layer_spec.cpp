#include <pwb/ui_composite/geological_layer_spec.hpp>

#include <pwb/ui_composite/layer_groups.hpp>
#include <pwb/ui_composite/roles.hpp>

#include <stdexcept>

namespace pwb::ui_composite {
namespace {

const Json* find(const Json& object, const char* key) {
    if (!object.is_object()) {
        return nullptr;
    }
    auto it = object.find(key);
    return it == object.end() ? nullptr : &*it;
}

std::string str_or(const Json& object, const char* key,
                   std::string fallback = {}) {
    const Json* value = find(object, key);
    if (value != nullptr && value->is_string()) {
        return value->get<std::string>();
    }
    if (value != nullptr && !value->is_null() && !value->is_object() &&
        !value->is_array()) {
        return value->dump();
    }
    return fallback;
}

bool bool_or(const Json& object, const char* key, bool fallback) {
    const Json* value = find(object, key);
    if (value != nullptr && value->is_boolean()) {
        return value->get<bool>();
    }
    return fallback;
}

double num_or(const Json& object, const char* key, double fallback) {
    const Json* value = find(object, key);
    if (value != nullptr && value->is_number()) {
        return value->get<double>();
    }
    return fallback;
}

std::optional<std::string> opt_str(const Json& object, const char* key) {
    const Json* value = find(object, key);
    if (value != nullptr && value->is_string()) {
        return value->get<std::string>();
    }
    return std::nullopt;
}

std::vector<std::string> str_list(const Json& object, const char* key) {
    std::vector<std::string> out;
    const Json* value = find(object, key);
    if (value != nullptr && value->is_array()) {
        for (const Json& item : *value) {
            if (item.is_string()) {
                out.push_back(item.get<std::string>());
            }
        }
    }
    return out;
}

Json stage_list_json(const std::vector<MappingStage>& stages) {
    Json out = Json::array();
    for (MappingStage stage : stages) {
        out.push_back(std::string(tool_policy::stage_value(stage)));
    }
    return out;
}

std::vector<MappingStage> stage_list_parse(const Json& object,
                                           const char* key) {
    std::vector<MappingStage> out;
    for (const std::string& id : str_list(object, key)) {
        if (auto stage = tool_policy::stage_from_value(id)) {
            out.push_back(*stage);
        }
    }
    return out;
}

SpecField F(std::string name, std::string label = {},
            std::string kind = "text",
            std::vector<std::string> choices = {},
            Json default_value = Json(""), bool required = false,
            std::optional<std::pair<double, double>> range = std::nullopt) {
    return SpecField{
        .name = std::move(name),
        .label = std::move(label),
        .kind = std::move(kind),
        .length = std::nullopt,
        .precision = std::nullopt,
        .choices = std::move(choices),
        .value_range = range,
        .default_value = std::move(default_value),
        .required = required,
        .unique = false,
        .expression = {},
        .editor_widget = std::nullopt,
    };
}

// Field sets shared across specs (mirrors Python module constants).
const std::vector<SpecField>& fault_fields() {
    static const std::vector<SpecField> fields = {
        F("fault_type", "断层性质", "text",
          {"normal", "reverse", "thrust", "strike_slip", "unclassified"},
          Json("unclassified"), true),
        F("confidence", "置信度", "text",
          {"inferred", "interpreted", "verified"}, Json("interpreted"),
          true),
        F("activity", "活动性", "text",
          {"active", "dormant", "unknown"}, Json("unknown")),
    };
    return fields;
}

const SpecField& facies_class_field() {
    static const SpecField field =
        F("facies_name", "相名", "text",
          {"alluvial_fan", "fluvial", "lacustrine", "delta", "shoreline",
           "shallow_marine", "deep_marine", "volcanic", "other"},
          Json("other"), true);
    return field;
}

const std::vector<SpecField>& facies_fields() {
    static const std::vector<SpecField> fields = {
        facies_class_field(),
        F("facies_id", "相编号", "text", {}, Json("")),
        F("source", "来源", "text", {}, Json("interpretation")),
    };
    return fields;
}

const std::vector<SpecField>& prediction_facies_fields() {
    static const std::vector<SpecField> fields = {
        F("facies_name", "相名", "text", {}, Json("")),
        F("facies", "相", "text", {}, Json("")),
    };
    return fields;
}

const std::vector<SpecField>& constraint_base_fields() {
    static const std::vector<SpecField> fields = {
        F("name", "名称", "text", {}, Json("")),
        F("active", "参与插值", "bool", {}, Json(true)),
        F("note", "备注", "text", {}, Json("")),
    };
    return fields;
}

std::vector<SpecField> concat(std::vector<SpecField> a,
                             const std::vector<SpecField>& b) {
    a.insert(a.end(), b.begin(), b.end());
    return a;
}

struct PolicyOverrides {
    std::optional<SnappingPolicy> snapping;
    std::optional<TopologyPolicy> topology;
    std::optional<ProvenancePolicy> provenance;
    std::optional<MaturityPolicy> maturity;
};

GeologicalLayerSpec make_spec(std::string spec_id, std::string role,
                              std::string geometry_kind, std::string title,
                              std::vector<SpecField> fields,
                              std::optional<RendererBinding> renderer,
                              std::optional<LabelBinding> label,
                              std::optional<std::string> constraint_kind,
                              std::optional<std::string> factor_child,
                              PolicyOverrides overrides) {
    const bool editable = role_is_editable(role);
    const bool raw = role_is_raw_protected(role);

    GeologicalLayerSpec spec;
    spec.spec_id = std::move(spec_id);
    spec.role = role;
    spec.geometry_kind = std::move(geometry_kind);
    spec.title = std::move(title);
    spec.fields = std::move(fields);

    spec.edit_policy = EditPolicy{
        .editable = editable,
        .raw_protected = raw,
        .allow_geometry_edit = editable,
        .allow_attribute_edit = true,
    };

    if (overrides.snapping.has_value()) {
        spec.snapping_policy = *overrides.snapping;
    } else if (editable) {
        spec.snapping_policy = SnappingPolicy{
            .enabled = editable && role != layer_role::kUserGeneral,
            .modes = {"vertex", "segment"},
        };
    }

    if (overrides.topology.has_value()) {
        spec.topology_policy = *overrides.topology;
    } else {
        const bool topo = role.rfind("initial", 0) == 0 ||
                          role.rfind("integrated", 0) == 0 ||
                          role.rfind("factor_class", 0) == 0;
        spec.topology_policy =
            topo ? TopologyPolicy{}
                 : TopologyPolicy{.validate_on_flush = false, .rules = {}};
    }

    StagePolicy stage;
    for (MappingStage s : stages_for_role(role)) {
        stage.visible_stages.push_back(s);
    }
    spec.stage_policy = std::move(stage);

    if (overrides.maturity.has_value()) {
        spec.maturity_policy = *overrides.maturity;
    } else {
        spec.maturity_policy = MaturityPolicy{
            .track = role == layer_role::kInitialFaciesDraft ||
                     role == layer_role::kIntegratedFacies ||
                     role == layer_role::kIntegratedBoundary,
            .initial = "draft",
        };
    }

    if (overrides.provenance.has_value()) {
        spec.provenance_policy = *overrides.provenance;
    } else {
        static const std::set<std::string> catalog_roles = {
            std::string(layer_role::kFactorGrid),
            std::string(layer_role::kFactorContour),
            std::string(layer_role::kFactorClassification),
            std::string(layer_role::kFactorUncertainty),
            std::string(layer_role::kFactorQc),
        };
        if (catalog_roles.count(role)) {
            spec.provenance_policy = ProvenancePolicy{
                .mode = "catalog_version_pinned", .pins_inputs = true};
        } else {
            spec.provenance_policy = ProvenancePolicy{};
        }
    }

    spec.renderer_binding = std::move(renderer);
    spec.label_binding = std::move(label);
    spec.constraint_kind = std::move(constraint_kind);
    spec.factor_child = std::move(factor_child);
    return spec;
}

using constraint_kind::kDistributionLine;
using constraint_kind::kFaciesBoundary;
using constraint_kind::kFault;
using constraint_kind::kInterpolationBoundary;
using constraint_kind::kMask;
using constraint_kind::kPaleoShoreline;
using constraint_kind::kProvenanceLine;
using constraint_kind::kSourceDirection;

}  // namespace

Json SpecField::to_dict() const {
    Json data = {
        {"name", name},
        {"label", label},
        {"kind", kind},
        {"required", required},
        {"default", default_value.is_null() ? Json("") : default_value},
    };
    if (length.has_value()) {
        data["length"] = *length;
    }
    if (precision.has_value()) {
        data["precision"] = *precision;
    }
    if (!choices.empty()) {
        data["choices"] = choices;
    }
    if (value_range.has_value()) {
        data["value_range"] = {value_range->first, value_range->second};
    }
    if (unique) {
        data["unique"] = true;
    }
    if (!expression.empty()) {
        data["expression"] = expression;
    }
    if (editor_widget.has_value()) {
        data["editor_widget"] = *editor_widget;
    }
    return data;
}

SpecField SpecField::from_dict(const Json& data) {
    SpecField field;
    field.name = str_or(data, "name");
    field.label = str_or(data, "label");
    field.kind = str_or(data, "kind", "text");
    const Json* length = find(data, "length");
    if (length != nullptr && length->is_number_integer()) {
        field.length = length->get<int>();
    }
    const Json* precision = find(data, "precision");
    if (precision != nullptr && precision->is_number_integer()) {
        field.precision = precision->get<int>();
    }
    field.choices = str_list(data, "choices");
    const Json* range = find(data, "value_range");
    if (range != nullptr && range->is_array() && range->size() >= 2 &&
        (*range)[0].is_number() && (*range)[1].is_number()) {
        field.value_range =
            std::make_pair((*range)[0].get<double>(),
                           (*range)[1].get<double>());
    }
    const Json* default_value = find(data, "default");
    field.default_value =
        default_value != nullptr ? *default_value : Json("");
    field.required = bool_or(data, "required", false);
    field.unique = bool_or(data, "unique", false);
    field.expression = str_or(data, "expression");
    field.editor_widget = opt_str(data, "editor_widget");
    return field;
}

Json EditPolicy::to_dict() const {
    return {
        {"editable", editable},
        {"raw_protected", raw_protected},
        {"allow_geometry_edit", allow_geometry_edit},
        {"allow_attribute_edit", allow_attribute_edit},
    };
}

EditPolicy EditPolicy::from_dict(const Json& data) {
    return {
        .editable = bool_or(data, "editable", false),
        .raw_protected = bool_or(data, "raw_protected", false),
        .allow_geometry_edit = bool_or(data, "allow_geometry_edit", true),
        .allow_attribute_edit = bool_or(data, "allow_attribute_edit", true),
    };
}

Json SnappingPolicy::to_dict() const {
    return {
        {"enabled", enabled},
        {"modes", modes},
        {"tolerance", tolerance},
        {"unit", unit},
        {"topological", topological},
    };
}

SnappingPolicy SnappingPolicy::from_dict(const Json& data) {
    SnappingPolicy policy;
    policy.enabled = bool_or(data, "enabled", false);
    policy.modes = str_list(data, "modes");
    if (policy.modes.empty()) {
        policy.modes = {"vertex"};
    }
    policy.tolerance = num_or(data, "tolerance", 10.0);
    policy.unit = str_or(data, "unit", "pixels");
    policy.topological = bool_or(data, "topological", false);
    return policy;
}

Json TopologyPolicy::to_dict() const {
    return {{"validate_on_flush", validate_on_flush}, {"rules", rules}};
}

TopologyPolicy TopologyPolicy::from_dict(const Json& data) {
    TopologyPolicy policy;
    policy.validate_on_flush = bool_or(data, "validate_on_flush", true);
    policy.rules = str_list(data, "rules");
    if (policy.rules.empty() &&
        !bool_or(data, "validate_on_flush", true)) {
        policy.rules = {};
    } else if (policy.rules.empty()) {
        policy.rules = {"ring_closure"};
    }
    return policy;
}

Json RendererBinding::to_dict() const {
    return {
        {"style_id", style_id},
        {"fallback_style", fallback_style},
        {"renderer_kind", renderer_kind},
        {"field", field.has_value() ? Json(*field) : Json(nullptr)},
    };
}

RendererBinding RendererBinding::from_dict(const Json& data) {
    RendererBinding binding;
    binding.style_id = str_or(data, "style_id");
    binding.fallback_style = str_or(data, "fallback_style");
    binding.renderer_kind = str_or(data, "renderer_kind", "single");
    binding.field = opt_str(data, "field");
    return binding;
}

Json LabelBinding::to_dict() const {
    auto opt = [](const std::optional<std::string>& value) {
        return value.has_value() ? Json(*value) : Json(nullptr);
    };
    return {
        {"enabled", enabled},
        {"field", opt(field)},
        {"size_field", opt(size_field)},
        {"color_field", opt(color_field)},
        {"rotation_field", opt(rotation_field)},
    };
}

LabelBinding LabelBinding::from_dict(const Json& data) {
    LabelBinding binding;
    binding.enabled = bool_or(data, "enabled", false);
    binding.field = opt_str(data, "field");
    binding.size_field = opt_str(data, "size_field");
    binding.color_field = opt_str(data, "color_field");
    binding.rotation_field = opt_str(data, "rotation_field");
    return binding;
}

Json ScaleVisibility::to_dict() const {
    return {
        {"min_scale",
         min_scale.has_value() ? Json(*min_scale) : Json(nullptr)},
        {"max_scale",
         max_scale.has_value() ? Json(*max_scale) : Json(nullptr)},
    };
}

ScaleVisibility ScaleVisibility::from_dict(const Json& data) {
    ScaleVisibility scale;
    const Json* lo = find(data, "min_scale");
    if (lo != nullptr && lo->is_number_integer()) {
        scale.min_scale = lo->get<int>();
    }
    const Json* hi = find(data, "max_scale");
    if (hi != nullptr && hi->is_number_integer()) {
        scale.max_scale = hi->get<int>();
    }
    return scale;
}

Json GeologicalLayerSpec::to_dict() const {
    Json data = {
        {"spec_id", spec_id},
        {"role", role},
        {"geometry_kind", geometry_kind},
        {"title", title},
    };
    Json field_list = Json::array();
    for (const SpecField& field : fields) {
        field_list.push_back(field.to_dict());
    }
    data["fields"] = std::move(field_list);
    if (edit_policy.has_value()) {
        data["edit_policy"] = edit_policy->to_dict();
    }
    if (snapping_policy.has_value()) {
        data["snapping_policy"] = snapping_policy->to_dict();
    }
    if (topology_policy.has_value()) {
        data["topology_policy"] = topology_policy->to_dict();
    }
    if (stage_policy.has_value()) {
        data["stage_policy"] = {
            {"visible_stages",
             stage_list_json(stage_policy->visible_stages)},
            {"locked_stages",
             stage_list_json(stage_policy->locked_stages)},
        };
    }
    if (maturity_policy.has_value()) {
        data["maturity_policy"] = {
            {"track", maturity_policy->track},
            {"initial", maturity_policy->initial},
        };
    }
    if (provenance_policy.has_value()) {
        data["provenance_policy"] = {
            {"mode", provenance_policy->mode},
            {"pins_inputs", provenance_policy->pins_inputs},
        };
    }
    if (renderer_binding.has_value()) {
        data["renderer_binding"] = renderer_binding->to_dict();
    }
    if (label_binding.has_value()) {
        data["label_binding"] = label_binding->to_dict();
    }
    if (scale_visibility.has_value()) {
        data["scale_visibility"] = scale_visibility->to_dict();
    }
    if (constraint_kind.has_value()) {
        data["constraint_kind"] = *constraint_kind;
    }
    if (factor_child.has_value()) {
        data["factor_child"] = *factor_child;
    }
    return data;
}

GeologicalLayerSpec GeologicalLayerSpec::from_dict(const Json& data) {
    GeologicalLayerSpec spec;
    spec.spec_id = str_or(data, "spec_id");
    spec.role = str_or(data, "role");
    spec.geometry_kind = str_or(data, "geometry_kind");
    spec.title = str_or(data, "title");
    const Json* field_list = find(data, "fields");
    if (field_list != nullptr && field_list->is_array()) {
        for (const Json& entry : *field_list) {
            spec.fields.push_back(SpecField::from_dict(entry));
        }
    }
    const Json* edit = find(data, "edit_policy");
    if (edit != nullptr && edit->is_object()) {
        spec.edit_policy = EditPolicy::from_dict(*edit);
    }
    const Json* snap = find(data, "snapping_policy");
    if (snap != nullptr && snap->is_object()) {
        spec.snapping_policy = SnappingPolicy::from_dict(*snap);
    }
    const Json* topo = find(data, "topology_policy");
    if (topo != nullptr && topo->is_object()) {
        spec.topology_policy = TopologyPolicy::from_dict(*topo);
    }
    const Json* stage = find(data, "stage_policy");
    if (stage != nullptr && stage->is_object()) {
        spec.stage_policy = StagePolicy{
            .visible_stages = stage_list_parse(*stage, "visible_stages"),
            .locked_stages = stage_list_parse(*stage, "locked_stages"),
        };
    }
    const Json* maturity = find(data, "maturity_policy");
    if (maturity != nullptr && maturity->is_object()) {
        spec.maturity_policy = MaturityPolicy{
            .track = bool_or(*maturity, "track", true),
            .initial = str_or(*maturity, "initial", "draft"),
        };
    }
    const Json* provenance = find(data, "provenance_policy");
    if (provenance != nullptr && provenance->is_object()) {
        spec.provenance_policy = ProvenancePolicy{
            .mode = str_or(*provenance, "mode", "session_only"),
            .pins_inputs = bool_or(*provenance, "pins_inputs", false),
        };
    }
    const Json* renderer = find(data, "renderer_binding");
    if (renderer != nullptr && renderer->is_object()) {
        spec.renderer_binding = RendererBinding::from_dict(*renderer);
    }
    const Json* label = find(data, "label_binding");
    if (label != nullptr && label->is_object()) {
        spec.label_binding = LabelBinding::from_dict(*label);
    }
    const Json* scale = find(data, "scale_visibility");
    if (scale != nullptr && scale->is_object()) {
        spec.scale_visibility = ScaleVisibility::from_dict(*scale);
    }
    spec.constraint_kind = opt_str(data, "constraint_kind");
    spec.factor_child = opt_str(data, "factor_child");
    return spec;
}

Json GeologicalLayerSpec::to_template_schema() const {
    Json field_list = Json::array();
    for (const SpecField& field : fields) {
        field_list.push_back({
            {"name", field.name},
            {"label", field.label.empty() ? field.name : field.label},
            {"kind",
             !field.choices.empty()
                 ? "choice"
                 : (field.kind == "int" || field.kind == "real"
                        ? "number"
                        : "text")},
            {"choices", field.choices},
            {"default",
             field.default_value.is_null() ? Json("")
                                           : field.default_value},
            {"required", field.required},
        });
    }
    return {{"fields", std::move(field_list)}};
}

const std::map<std::string, GeologicalLayerSpec>&
geological_layer_specs() {
    static const std::map<std::string, GeologicalLayerSpec> specs = [] {
        std::map<std::string, GeologicalLayerSpec> map;
        auto add = [&map](GeologicalLayerSpec spec) {
            map.emplace(spec.role, std::move(spec));
        };
        auto spec = [](std::string id, std::string role,
                       std::string geometry, std::string title,
                       std::vector<SpecField> fields = {},
                       std::optional<RendererBinding> renderer =
                           std::nullopt,
                       std::optional<LabelBinding> label = std::nullopt,
                       std::optional<std::string> kind = std::nullopt,
                       std::optional<std::string> child = std::nullopt,
                       PolicyOverrides overrides = {}) {
            return make_spec(std::move(id), std::move(role),
                             std::move(geometry), std::move(title),
                             std::move(fields), std::move(renderer),
                             std::move(label), std::move(kind),
                             std::move(child), std::move(overrides));
        };

        // -- Phase 1 -----------------------------------------------------
        add(spec("initial-facies-source-v2",
                 std::string(layer_role::kInitialFaciesSource), "polygon",
                 "初始沉积相（RAW）", facies_fields(),
                 RendererBinding{"facies_v1", "facies", "categorized",
                                 std::string("facies_name")},
                 LabelBinding{.enabled = true,
                              .field = std::string("facies_name")}));
        add(spec("initial-facies-draft-v2",
                 std::string(layer_role::kInitialFaciesDraft), "polygon",
                 "初始相校正草稿（DERIVED）",
                 concat(facies_fields(),
                        {F("facies", "相", "text", {}, Json("")),
                         F("probability", "概率", "real", {}, Json(0.0),
                           false, std::make_pair(0.0, 1.0))}),
                 RendererBinding{"facies_v1", "facies", "categorized",
                                 std::string("facies_name")},
                 LabelBinding{.enabled = true,
                              .field = std::string("facies_name")},
                 std::nullopt, std::nullopt,
                 PolicyOverrides{
                     .provenance = ProvenancePolicy{
                         .mode = "content_fingerprint",
                         .pins_inputs = true}}));

        struct PredictionRow {
            std::string role;
            const char* style_id;
            const char* kind;
        };
        const PredictionRow prediction_rows[] = {
            {std::string(layer_role::kWellFaciesPrediction),
             "prediction_overlay_v1", "categorized"},
            {std::string(layer_role::kWellFaciesConfidence),
             "confidence_band_v1", "graduated"},
            {std::string(layer_role::kSeismicFaciesPrediction),
             "prediction_overlay_v1", "categorized"},
            {std::string(layer_role::kSeismicFaciesConfidence),
             "confidence_band_v1", "graduated"},
        };
        for (const PredictionRow& row : prediction_rows) {
            const bool graduated = std::string(row.kind) == "graduated";
            add(spec(row.role + "-v2", row.role, "polygon",
                     role_label(row.role),
                     concat(prediction_facies_fields(),
                            {F("probability", "概率", "real", {},
                               Json(0.0), false,
                               std::make_pair(0.0, 1.0))}),
                     RendererBinding{row.style_id, "facies", row.kind,
                                     graduated
                                         ? std::optional<std::string>(
                                               "probability")
                                         : std::nullopt}));
        }
        add(spec("interpretation-annotation-v2",
                 std::string(layer_role::kInterpretationAnnotation),
                 "point", "解释标注",
                 {F("text", "内容", "text", {}, Json(""), true)},
                 RendererBinding{"annotation_v1", "annotation",
                                 "single"},
                 LabelBinding{.enabled = true,
                              .field = std::string("text")}));

        // -- Phase 2 constraints ------------------------------------------
        add(spec("fault-constraint-v2",
                 std::string(layer_role::kFaultConstraint), "line", "断层",
                 concat(fault_fields(), constraint_base_fields()),
                 RendererBinding{"fault_v2", "fault", "categorized",
                                 std::string("fault_type")},
                 std::nullopt, std::string(kFault), std::nullopt,
                 PolicyOverrides{
                     .snapping = SnappingPolicy{
                         .enabled = true,
                         .modes = {"vertex", "endpoint", "segment"},
                         .topological = false}}));
        add(spec("provenance-line-v2",
                 std::string(layer_role::kProvenanceLine), "line", "物源线",
                 constraint_base_fields(),
                 RendererBinding{"provenance_line_v1", "line", "single"},
                 std::nullopt, std::string(kProvenanceLine)));
        add(spec("provenance-direction-v2",
                 std::string(layer_role::kProvenanceDirection), "line",
                 "物源方向",
                 concat(constraint_base_fields(),
                        {F("azimuth_deg", "方位角", "real", {}, Json(""),
                           false, std::make_pair(0.0, 360.0)),
                         F("semi_major", "长半轴", "real", {}, Json(""),
                           false, std::make_pair(0.0, 1e9)),
                         F("semi_minor", "短半轴", "real", {}, Json(""),
                           false, std::make_pair(0.0, 1e9))}),
                 RendererBinding{"provenance_direction_v1", "line",
                                 "single"},
                 LabelBinding{.enabled = true,
                              .field = std::string("azimuth_deg")},
                 std::string(kSourceDirection)));
        add(spec("distribution-line-v2",
                 std::string(layer_role::kDistributionLine), "line",
                 "沉积体系展布线", constraint_base_fields(),
                 RendererBinding{"distribution_line_v1", "line",
                                 "single"},
                 std::nullopt, std::string(kDistributionLine)));
        add(spec("paleo-shoreline-v2",
                 std::string(layer_role::kPaleoShoreline), "line", "古岸线",
                 concat(constraint_base_fields(),
                        {F("shoreline_type", "岸线类型", "text",
                           {"marine", "lacustrine", "deltaic",
                            "unclassified"},
                           Json("unclassified"))}),
                 RendererBinding{"shoreline_v1", "formation_boundary",
                                 "single"},
                 std::nullopt, std::string(kPaleoShoreline)));
        add(spec("facies-boundary-v2",
                 std::string(layer_role::kFaciesBoundary), "line",
                 "相带边界", constraint_base_fields(),
                 RendererBinding{"facies_boundary_v1",
                                 "formation_boundary", "single"},
                 std::nullopt, std::string(kFaciesBoundary)));
        add(spec("interpolation-boundary-v2",
                 std::string(layer_role::kInterpolationBoundary),
                 "polygon", "插值限制边界（成图范围）",
                 constraint_base_fields(),
                 RendererBinding{"interpolation_boundary_v1", "line",
                                 "single"},
                 std::nullopt, std::string(kInterpolationBoundary)));
        add(spec("mask-boundary-v2",
                 std::string(layer_role::kMaskBoundary), "polygon",
                 "掩膜/排除区",
                 concat(constraint_base_fields(),
                        {F("mask_kind", "类型", "text",
                           {"mask", "exclusion"}, Json("mask"))}),
                 RendererBinding{"mask_v1", "polygon", "single"},
                 std::nullopt, std::string(kMask)));

        // -- Phase 2 factor family ----------------------------------------
        add(spec("factor-input-v2",
                 std::string(layer_role::kFactorInput), "point",
                 "单因素输入井点",
                 {F("well_id", "井号", "text", {}, Json(""), true),
                  F("value", "值", "real"),
                  F("qc_flag", "QC", "text",
                    {"ok", "outlier", "invalid_ratio", "missing"},
                    Json("ok"))},
                 RendererBinding{"well_v1", "well", "single"},
                 LabelBinding{.enabled = true,
                              .field = std::string("value")},
                 std::nullopt, std::string("input")));
        add(spec("factor-grid-v2", std::string(layer_role::kFactorGrid),
                 "raster", "单因素栅格", {},
                 RendererBinding{"factor_scalar_v1", "grid",
                                 "pseudocolor"},
                 std::nullopt, std::nullopt, std::string("grid")));
        add(spec("factor-contour-v2",
                 std::string(layer_role::kFactorContour), "line",
                 "单因素等值线",
                 {F("level", "等值线值", "real", {}, Json(""), true),
                  F("is_index_contour", "计曲线", "bool", {},
                    Json(false)),
                  F("unit", "单位", "text", {}, Json(""))},
                 RendererBinding{"contour_v1", "contour", "single"},
                 LabelBinding{.enabled = true,
                              .field = std::string("level")},
                 std::nullopt, std::string("contour")));
        add(spec("factor-classification-v2",
                 std::string(layer_role::kFactorClassification),
                 "polygon", "单因素分级区",
                 {facies_class_field(), F("area", "面积", "real"),
                  F("area_unit", "面积单位", "text", {}, Json(""))},
                 RendererBinding{"facies_v1", "facies", "categorized",
                                 std::string("facies_name")},
                 std::nullopt, std::nullopt,
                 std::string("classification")));
        add(spec("factor-uncertainty-v2",
                 std::string(layer_role::kFactorUncertainty), "raster",
                 "不确定性面", {},
                 RendererBinding{"uncertainty_band_v1", "grid",
                                 "pseudocolor"},
                 std::nullopt, std::nullopt, std::string("uncertainty")));
        add(spec("factor-qc-v2", std::string(layer_role::kFactorQc),
                 "point", "单因素 QC",
                 {F("rule", "规则", "text", {}, Json(""), true),
                  F("severity", "严重度", "text",
                    {"info", "warning", "error"}, Json("warning")),
                  F("reason", "原因", "text")},
                 RendererBinding{"qc_overlay_v1", "annotation",
                                 "categorized", std::string("severity")},
                 std::nullopt, std::nullopt, std::string("qc")));
        add(spec("analysis-aid-v2",
                 std::string(layer_role::kAnalysisAid), "point",
                 "分析辅助（残差/异常）",
                 {F("kind", "类型", "text",
                    {"residual", "outlier", "coverage"},
                    Json("residual")),
                  F("value", "值", "real")},
                 RendererBinding{"qc_overlay_v1", "annotation",
                                 "categorized", std::string("kind")}));

        // -- Phase 3 ------------------------------------------------------
        add(spec("integrated-facies-v2",
                 std::string(layer_role::kIntegratedFacies), "polygon",
                 "综合沉积相", facies_fields(),
                 RendererBinding{"facies_v1", "facies", "categorized",
                                 std::string("facies_name")},
                 LabelBinding{.enabled = true,
                              .field = std::string("facies_name")},
                 std::nullopt, std::nullopt,
                 PolicyOverrides{
                     .provenance = ProvenancePolicy{
                         .mode = "content_fingerprint",
                         .pins_inputs = true}}));
        add(spec("integrated-boundary-v2",
                 std::string(layer_role::kIntegratedBoundary), "line",
                 "综合相带边界", constraint_base_fields(),
                 RendererBinding{"facies_boundary_v1",
                                 "formation_boundary", "single"}));
        add(spec("map-annotation-v2",
                 std::string(layer_role::kMapAnnotation), "point",
                 "专题标注",
                 {F("text", "内容", "text", {}, Json(""), true)},
                 RendererBinding{"annotation_v1", "annotation",
                                 "single"},
                 LabelBinding{.enabled = true,
                              .field = std::string("text")}));
        add(spec("map-reference-v2",
                 std::string(layer_role::kMapReference), "vector",
                 "编图参考", {},
                 RendererBinding{"map_reference_v1", "line", "single"}));

        // -- base / user / QC ----------------------------------------------
        add(spec("base-reference-v2",
                 std::string(layer_role::kBaseReference), "vector",
                 "基础参考图层",
                 {F("name", "名称", "text", {}, Json(""))},
                 RendererBinding{"base_reference_v1", "line", "single"}));
        add(spec("user-general-v2",
                 std::string(layer_role::kUserGeneral), "vector",
                 "用户图层"));
        add(spec("qc-warning-v2", std::string(layer_role::kQcWarning),
                 "point", "QC 警告",
                 {F("rule", "规则", "text", {}, Json(""), true),
                  F("severity", "严重度", "text",
                    {"info", "warning", "error"}, Json("warning")),
                  F("reason", "原因", "text")},
                 RendererBinding{"qc_overlay_v1", "annotation",
                                 "categorized", std::string("severity")}));
        add(spec("qc-conflict-v2", std::string(layer_role::kQcConflict),
                 "point", "QC 冲突",
                 {F("rule", "规则", "text", {}, Json(""), true),
                  F("reason", "原因", "text")},
                 RendererBinding{"qc_overlay_v1", "annotation",
                                 "single"}));
        return map;
    }();
    return specs;
}

const GeologicalLayerSpec& spec_for_role(const std::string& role_value) {
    const std::string key =
        layer_role_from_value(role_value).value_or(role_value);
    auto it = geological_layer_specs().find(key);
    if (it == geological_layer_specs().end()) {
        throw std::out_of_range("no GeologicalLayerSpec registered for "
                                "role " +
                                key);
    }
    return it->second;
}

std::vector<std::string> specs_for_constraint_kind(
    const std::string& kind_value) {
    std::vector<std::string> out;
    const auto kind = constraint_kind_from_value(kind_value);
    for (const auto& [role, spec] : geological_layer_specs()) {
        if (kind.has_value() && spec.constraint_kind.has_value() &&
            *spec.constraint_kind == *kind) {
            out.push_back(role);
        }
    }
    return out;
}

std::string layer_type_for_role(const std::string& role_value) {
    static const std::map<std::string, std::string> map = {
        {std::string(layer_role::kInitialFaciesSource), "polygon"},
        {std::string(layer_role::kInitialFaciesDraft), "polygon"},
        {std::string(layer_role::kWellFaciesPrediction), "polygon"},
        {std::string(layer_role::kWellFaciesConfidence), "polygon"},
        {std::string(layer_role::kSeismicFaciesPrediction), "polygon"},
        {std::string(layer_role::kSeismicFaciesConfidence), "polygon"},
        {std::string(layer_role::kInterpretationAnnotation),
         "annotation"},
        {std::string(layer_role::kProvenanceDirection), "vector"},
        {std::string(layer_role::kProvenanceLine), "vector"},
        {std::string(layer_role::kDistributionLine), "vector"},
        {std::string(layer_role::kPaleoShoreline), "vector"},
        {std::string(layer_role::kFaciesBoundary), "vector"},
        {std::string(layer_role::kFaultConstraint), "vector"},
        {std::string(layer_role::kInterpolationBoundary), "polygon"},
        {std::string(layer_role::kMaskBoundary), "polygon"},
        {std::string(layer_role::kFactorInput), "well_point"},
        {std::string(layer_role::kFactorGrid), "scalar_grid"},
        {std::string(layer_role::kFactorContour), "contour"},
        {std::string(layer_role::kFactorClassification), "polygon"},
        {std::string(layer_role::kFactorUncertainty), "scalar_grid"},
        {std::string(layer_role::kFactorQc), "vector"},
        {std::string(layer_role::kAnalysisAid), "vector"},
        {std::string(layer_role::kIntegratedFacies), "polygon"},
        {std::string(layer_role::kIntegratedBoundary), "vector"},
        {std::string(layer_role::kMapAnnotation), "annotation"},
        {std::string(layer_role::kMapSymbol), "annotation"},
        {std::string(layer_role::kMapReference), "vector"},
        {std::string(layer_role::kQcWarning), "vector"},
        {std::string(layer_role::kQcConflict), "vector"},
        {std::string(layer_role::kUserGeneral), "vector"},
        {std::string(layer_role::kBaseReference), "vector"},
        {std::string(layer_role::kPendingReviewArea), "polygon"},
        {std::string(layer_role::kLegacyUnclassified), "vector"},
    };
    auto it = map.find(role_value);
    return it == map.end() ? std::string{} : it->second;
}

std::optional<std::string> role_for_layer_type(
    const std::string& layer_type) {
    static const std::map<std::string, std::string> map = {
        {"vector", std::string(layer_role::kUserGeneral)},
        {"grid", std::string(layer_role::kFactorGrid)},
        {"contour", std::string(layer_role::kFactorContour)},
        {"well_point", std::string(layer_role::kFactorInput)},
        {"polygon", std::string(layer_role::kInitialFaciesDraft)},
        {"facies", std::string(layer_role::kInitialFaciesSource)},
        {"raster", std::string(layer_role::kBaseReference)},
        {"scalar_grid", std::string(layer_role::kFactorGrid)},
        {"raster_source", std::string(layer_role::kBaseReference)},
        {"annotation", std::string(layer_role::kMapAnnotation)},
    };
    auto it = map.find(layer_type);
    if (it == map.end()) {
        return std::nullopt;
    }
    return it->second;
}

}  // namespace pwb::ui_composite
