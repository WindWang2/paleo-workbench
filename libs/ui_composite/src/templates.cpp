#include <pwb/ui_composite/templates.hpp>

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

bool default_is_empty(const Json& value) {
    return value.is_null() ||
           (value.is_string() && value.get<std::string>().empty());
}

TemplateField F(std::string name, std::string label,
                std::string kind = "text",
                std::vector<std::string> choices = {},
                Json default_value = Json(""), bool required = false) {
    return TemplateField{
        .name = std::move(name),
        .label = std::move(label),
        .kind = std::move(kind),
        .choices = std::move(choices),
        .default_value = std::move(default_value),
        .required = required,
    };
}

const std::vector<std::string>& confidence_choices() {
    static const std::vector<std::string> choices = {"高", "中", "低"};
    return choices;
}

}  // namespace

const std::map<std::string, std::string>& geometry_kind_labels() {
    static const std::map<std::string, std::string> labels = {
        {"point", "点"}, {"line", "线"}, {"polygon", "面"},
    };
    return labels;
}

Json TemplateField::to_dict() const {
    Json data = {
        {"name", name},
        {"label", label.empty() ? name : label},
        {"kind", kind},
        {"required", required},
    };
    if (!choices.empty()) {
        data["choices"] = choices;
    }
    if (!default_is_empty(default_value)) {
        data["default"] = default_value;
    }
    return data;
}

TemplateField TemplateField::from_dict(const Json& data) {
    if (!data.is_object()) {
        throw std::invalid_argument("template field requires a name");
    }
    const Json* name = find(data, "name");
    if (name == nullptr || !name->is_string() ||
        name->get<std::string>().empty()) {
        throw std::invalid_argument("template field requires a name");
    }
    TemplateField field;
    field.name = name->get<std::string>();
    const Json* label = find(data, "label");
    field.label = label != nullptr && label->is_string()
                      ? label->get<std::string>()
                      : field.name;
    const Json* kind = find(data, "kind");
    field.kind = kind != nullptr && kind->is_string()
                     ? kind->get<std::string>()
                     : "text";
    if (field.kind != "text" && field.kind != "number" &&
        field.kind != "choice") {
        field.kind = "text";
    }
    const Json* choices = find(data, "choices");
    if (choices != nullptr && choices->is_array()) {
        for (const Json& item : *choices) {
            if (item.is_string() && !item.get<std::string>().empty()) {
                field.choices.push_back(item.get<std::string>());
            }
        }
    }
    if (field.kind == "choice" && field.choices.empty()) {
        field.kind = "text";
    }
    const Json* default_value = find(data, "default");
    field.default_value =
        default_value != nullptr ? *default_value : Json("");
    if (field.kind == "number") {
        // Python coerces numeric defaults to float; unparsable → "".
        if (!default_is_empty(field.default_value) &&
            !field.default_value.is_number()) {
            if (field.default_value.is_string()) {
                try {
                    field.default_value =
                        std::stod(field.default_value.get<std::string>());
                } catch (...) {
                    field.default_value = "";
                }
            } else {
                field.default_value = "";
            }
        }
    }
    const Json* required = find(data, "required");
    field.required = required != nullptr && required->is_boolean() &&
                     required->get<bool>();
    return field;
}

Json fields_to_schema(const std::vector<TemplateField>& fields) {
    Json list = Json::array();
    for (const TemplateField& field : fields) {
        list.push_back(field.to_dict());
    }
    return {{"fields", std::move(list)}};
}

std::vector<TemplateField> schema_fields(const Json& schema) {
    std::vector<TemplateField> fields;
    const Json* raw = find(schema, "fields");
    if (raw == nullptr || !raw->is_array()) {
        return fields;
    }
    for (const Json& item : *raw) {
        try {
            fields.push_back(TemplateField::from_dict(item));
        } catch (const std::invalid_argument&) {
            continue;
        }
    }
    return fields;
}

Json GeoTemplate::field_defaults() const {
    Json defaults = Json::object();
    for (const TemplateField& field : fields) {
        if (!default_is_empty(field.default_value)) {
            defaults[field.name] = field.default_value;
        }
    }
    return defaults;
}

const std::vector<GeoTemplate>& geo_templates() {
    static const std::vector<GeoTemplate> templates = [] {
        std::vector<GeoTemplate> out;

        VectorStyle source_style;
        source_style.fill = "transparent";
        source_style.stroke = "#ff6b6b";  // CANVAS_EDIT
        source_style.stroke_width = 2.5;

        VectorStyle spreading_style;
        spreading_style.fill = "transparent";
        spreading_style.stroke = "#53d8fb";  // CANVAS_SNAP
        spreading_style.stroke_width = 2.0;
        spreading_style.line_pattern = line_pattern::kDash;

        VectorStyle break_style;
        break_style.fill = "transparent";
        break_style.stroke = "#343a40";  // CANVAS_INK
        break_style.stroke_width = 1.5;
        break_style.line_pattern = line_pattern::kDash;

        VectorStyle direction_style;
        direction_style.fill = "transparent";
        direction_style.stroke = "#7c3aed";  // CANVAS_CURSOR
        direction_style.stroke_width = 2.0;

        const std::vector<TemplateField> facies_fields = {
            // 三级相字段：choices 留空——词表驱动，属性表/检查器/选择对话
            // 框从 FaciesTaxonomy 级联生成选项。
            F("facies", "相", "choice"),
            F("sub_facies", "亚相", "choice"),
            F("micro_facies", "微相", "choice"),
            F("lithology", "岩性"),
            F("confidence", "可信度", "choice", confidence_choices(),
              Json("中")),
            F("horizon", "层位", "text", {}, Json(""), true),
            F("level", "解释级别", "choice",
              {"facies", "sub_facies", "micro_facies"}),
            F("parent_id", "父级要素"),
            F("source", "资料来源"),
        };

        out.push_back(GeoTemplate{
            "well_point", "测井点", "point", default_style_for("well"),
            {F("name", "井名", "text", {}, Json(""), true),
             F("operator", "作业者"),
             F("purpose", "井别", "choice",
               {"探井", "评价井", "开发井", "参数井"}),
             F("spud_date", "开钻日期"), F("source", "资料来源")}});
        out.push_back(GeoTemplate{
            "fault", "断层线", "line",
            style_library().at("fault"),
            {F("name", "断层名称", "text", {}, Json(""), true),
             F("fault_type", "断层性质", "choice",
               {"正断层", "逆断层", "走滑断层", "逆掩断层", "未定"}),
             F("confidence", "可信度", "choice", confidence_choices(),
               Json("中")),
             F("strike", "走向（°）", "number"),
             F("throw", "断距（m）", "number"), F("horizon", "层位"),
             F("interpreter", "解释人"), F("source", "资料来源")}});
        out.push_back(GeoTemplate{"facies", "相带（相图）", "polygon",
                                  default_style_for("facies"),
                                  facies_fields});
        out.push_back(GeoTemplate{"facies_sub", "相带（亚相图）",
                                  "polygon", default_style_for("facies"),
                                  facies_fields});
        out.push_back(GeoTemplate{"facies_micro", "相带（微相图）",
                                  "polygon", default_style_for("facies"),
                                  facies_fields});
        out.push_back(GeoTemplate{
            "source", "物源线", "line", source_style,
            {F("source_type", "物源类型", "choice",
               {"点物源", "多物源", "侧向物源", "未知"}),
             F("direction", "方向（如 NNE）"),
             F("confidence", "可信度", "choice", confidence_choices(),
               Json("中")),
             F("horizon", "层位")}});
        out.push_back(GeoTemplate{
            "spreading", "展布线", "line", spreading_style,
            {F("spreading_type", "展布类型", "choice",
               {"边界展布", "内部展布", "推测展布"}),
             F("horizon", "层位"),
             F("confidence", "可信度", "choice", confidence_choices(),
               Json("中"))}});
        out.push_back(GeoTemplate{
            "break", "打断线", "line", break_style,
            {F("break_type", "打断类型", "choice",
               {"剥蚀", "构造缺失", "资料缺失"}),
             F("horizon", "层位"), F("related", "关联层位")}});
        out.push_back(GeoTemplate{
            "direction", "方向线", "line", direction_style,
            {F("direction", "方向（如 NE45°）", "text", {}, Json(""),
               true),
             F("horizon", "层位"),
             F("confidence", "可信度", "choice", confidence_choices(),
               Json("中"))}});
        out.push_back(GeoTemplate{
            "extent", "成图范围", "polygon",
            style_library().at("formation_boundary"),
            {F("name", "范围名称", "text", {}, Json(""), true),
             F("phase", "编制阶段", "choice",
               {"普查", "详查", "精查"}),
             F("remark", "备注")}});
        return out;
    }();
    return templates;
}

const GeoTemplate* template_by_key(const std::string& key) {
    for (const GeoTemplate& tpl : geo_templates()) {
        if (tpl.key == key) {
            return &tpl;
        }
    }
    return nullptr;
}

const std::set<std::string>& facies_template_keys() {
    static const std::set<std::string> keys = {"facies", "facies_sub",
                                               "facies_micro"};
    return keys;
}

std::optional<std::string> facies_template_level(
    const std::string& template_key) {
    static const std::map<std::string, std::string> levels = {
        {"facies", "facies"},
        {"facies_sub", "sub_facies"},
        {"facies_micro", "micro_facies"},
    };
    auto it = levels.find(template_key);
    if (it == levels.end()) {
        return std::nullopt;
    }
    return it->second;
}

bool is_facies_template_layer(
    const std::map<std::string, std::string>& templates,
    const std::string& layer_id) {
    auto it = templates.find(layer_id);
    return it != templates.end() && facies_template_keys().count(it->second);
}

bool is_facies_family_layer(
    const std::map<std::string, std::string>& templates,
    const std::string& layer_id, const std::string& role_value) {
    if (is_facies_template_layer(templates, layer_id)) {
        return true;
    }
    return is_facies_family_role(role_value);
}

}  // namespace pwb::ui_composite
