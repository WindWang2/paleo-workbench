#include <pwb/ui_composite/attribute_schema.hpp>

#include <pwb/ui_composite/geological_layer_spec.hpp>
#include <pwb/ui_composite/qgis_layer_schema.hpp>
#include <pwb/ui_composite/templates.hpp>

#include <algorithm>
#include <set>
#include <sstream>

namespace pwb::ui_composite {
namespace {

// Re-derive the editor-widget inference from qgis_layer_schema.cpp —
// it's the single inference authority (与镜像 fields_json 同源).
std::string editor_widget_for_field(const SpecField& field) {
    if (field.editor_widget.has_value()) {
        return *field.editor_widget;
    }
    if (!field.choices.empty()) {
        return "ValueMap";
    }
    if (field.kind == "bool") {
        return "CheckBox";
    }
    if (field.kind == "datetime") {
        return "DateTime";
    }
    if ((field.kind == "int" || field.kind == "real") &&
        field.value_range.has_value()) {
        return "Range";
    }
    return "TextEdit";
}

// 角色 spec → 描述符；无角色/未知角色返回 nullopt（不猜）。
std::optional<std::vector<AttributeFieldMeta>> spec_descriptors(
    const std::string& role_value) {
    if (role_value.empty()) {
        return std::nullopt;
    }
    const GeologicalLayerSpec* spec = nullptr;
    try {
        spec = &spec_for_role(role_value);
    } catch (const std::out_of_range&) {
        return std::nullopt;
    }
    std::vector<AttributeFieldMeta> descriptors;
    for (const SpecField& field : spec->fields) {
        descriptors.push_back(AttributeFieldMeta{
            .key = field.name,
            .label = field.label.empty() ? field.name : field.label,
            .kind = field.kind,
            .choices = field.choices,
            .required = field.required,
            .unique = field.unique,
            .expression = field.expression,
            .value_range = field.value_range,
            .editor_widget = editor_widget_for_field(field),
            .origin = "spec",
        });
    }
    return descriptors;
}

}  // namespace

std::vector<AttributeFieldMeta> field_descriptors_for_layer(
    const AttributeLayerSource& source, const std::string& layer_id) {
    std::vector<AttributeFieldMeta> descriptors;
    std::set<std::string> seen;
    const std::string role =
        source.role_of_layer ? source.role_of_layer(layer_id)
                             : std::string{};
    if (auto spec_fields = spec_descriptors(role)) {
        for (const AttributeFieldMeta& meta : *spec_fields) {
            descriptors.push_back(meta);
            seen.insert(meta.key);
        }
    } else if (source.layer_schema) {
        for (const TemplateField& field :
             schema_fields(source.layer_schema(layer_id))) {
            descriptors.push_back(AttributeFieldMeta{
                .key = field.name,
                .label = field.label.empty() ? field.name : field.label,
                .kind = field.kind,
                .choices = field.choices,
                .required = field.required,
                .origin = "template",
            });
            seen.insert(field.name);
        }
    }
    const VectorLayer* layer =
        source.layer ? source.layer(layer_id) : nullptr;
    std::vector<VectorFeature> features;
    if (layer != nullptr) {
        const VectorEditSession* session = layer->edit_session();
        features = session != nullptr ? session->features()
                                      : layer->features();
    }
    for (const VectorFeature& feature : features) {
        if (!feature.attributes.is_object()) {
            continue;
        }
        for (const auto& [key, value] : feature.attributes.items()) {
            if (!seen.count(key)) {
                descriptors.push_back(AttributeFieldMeta{
                    .key = key,
                    .label = key,
                    .kind = "text",
                    .origin = "extra",
                });
                seen.insert(key);
            }
        }
    }
    if (descriptors.empty()) {
        descriptors.push_back(AttributeFieldMeta{
            .key = "id",
            .label = "ID",
            .kind = "text",
            .origin = "extra",
        });
    }
    return descriptors;
}

std::pair<std::string, std::string> qgis_schema_parity(
    const MirrorSchemaProbe& probe, const std::string& layer_id,
    const std::vector<AttributeFieldMeta>& descriptors) {
    if (!probe) {
        return {"unavailable",
                "QGIS provider 自省面不可用（旧桥或回退画布）"};
    }
    Json reported;
    try {
        reported = probe(layer_id);
    } catch (const std::exception& exc) {
        return {"unavailable",
                std::string("QGIS provider 自省失败：") + exc.what()};
    }
    if (!reported.is_object() || !reported.value("exists", false)) {
        return {"unavailable",
                "图层尚未镜像到 QGIS（无 provider schema）"};
    }
    std::vector<std::string> got_names;
    auto fields_it = reported.find("fields");
    if (fields_it != reported.end() && fields_it->is_array()) {
        for (const Json& field : *fields_it) {
            if (field.is_object()) {
                auto name = field.find("name");
                got_names.push_back(
                    name != field.end() && name->is_string()
                        ? name->get<std::string>()
                        : std::string{});
            } else {
                got_names.emplace_back();
            }
        }
    }
    std::vector<std::string> want_names;
    for (const AttributeFieldMeta& meta : descriptors) {
        if (meta.origin != "extra") {
            want_names.push_back(meta.key);
        }
    }
    if (got_names == want_names) {
        return {"synced",
                "字段 schema 与 QGIS provider 一致（" +
                    std::to_string(got_names.size()) + " 字段）"};
    }
    std::vector<std::string> missing, extra;
    for (const std::string& name : want_names) {
        if (std::find(got_names.begin(), got_names.end(), name) ==
            got_names.end()) {
            missing.push_back(name);
        }
    }
    for (const std::string& name : got_names) {
        if (std::find(want_names.begin(), want_names.end(), name) ==
            want_names.end()) {
            extra.push_back(name);
        }
    }
    auto join = [](const std::vector<std::string>& items) {
        std::ostringstream out;
        out << "[";
        for (size_t i = 0; i < items.size(); ++i) {
            if (i > 0) {
                out << ", ";
            }
            out << "'" << items[i] << "'";
        }
        out << "]";
        return out.str();
    };
    std::string detail = "QGIS provider schema 漂移：";
    bool first = true;
    if (!missing.empty()) {
        detail += "缺 " + join(missing);
        first = false;
    }
    if (!extra.empty()) {
        if (!first) {
            detail += "，";
        }
        detail += "多 " + join(extra);
    }
    return {"drift", detail};
}

}  // namespace pwb::ui_composite
