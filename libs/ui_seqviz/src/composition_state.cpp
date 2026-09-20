#include <pwb/ui_seqviz/composition_state.hpp>

#include <algorithm>
#include <cstdio>
#include <utility>

#include <pwb/ui_data_core/json_util.hpp>
#include <pwb/ui_data_core/sequence_helpers.hpp>

namespace pwb::ui_seqviz {

namespace {

std::string prop_string(const domain::Json& prop, const char* key,
                        const std::string& fallback = "") {
    return ui_data_core::json_get_string(prop, key, fallback);
}

double prop_number(const domain::Json& prop, const char* key,
                   double fallback) {
    return ui_data_core::json_get_opt_double(prop, key).value_or(fallback);
}

std::string py_g(double value) {
    // f"{x:g}" — Python's %g default precision is 6 significant digits.
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%.6g", value);
    return buf;
}

}  // namespace

// ---------------------------------------------------------------------------
// Element list
// ---------------------------------------------------------------------------

std::vector<CompositionElementRow> composition_element_rows(
    const Composition& document, const ElementLabelFn& label_fn) {
    std::vector<CompositionElementRow> rows;
    rows.reserve(document.elements.size());
    for (auto it = document.elements.rbegin(); it != document.elements.rend();
         ++it) {
        const ComposerElement& element = *it;
        std::string label = label_fn ? label_fn(element.element_type)
                                     : element.element_type;
        // 前向兼容载体：显示真实（未知）类型名。
        if (element.carried_raw_type) {
            const std::string raw = ui_data_core::json_get_string(
                element.properties, "_raw_element_type");
            if (!raw.empty()) {
                label = raw + "（未支持）";
            }
        }
        if (element.locked) {
            label += "（锁定）";
        }
        if (!element.visible) {
            label += "（隐藏）";
        }
        rows.push_back({element.id, std::move(label), element.visible});
    }
    return rows;
}

// ---------------------------------------------------------------------------
// Property editor
// ---------------------------------------------------------------------------

GeometryView property_geometry_state(const ComposerElement* element) {
    GeometryView view;
    if (element == nullptr) {
        return view;
    }
    view.x = element->x_mm;
    view.y = element->y_mm;
    view.w = element->width_mm;
    view.h = element->height_mm;
    view.editable = !element->locked;
    view.lock_hint_visible = element->locked;
    return view;
}

const std::set<std::string>& table_series_chart_types() {
    static const std::set<std::string> types = {
        "bar", "hbar", "line", "scatter", "pie", "donut",
    };
    return types;
}

bool series_is_label_value(const domain::Json& series) {
    if (!series.is_array()) {
        return false;
    }
    for (const auto& entry : series) {
        if (!entry.is_object()) {
            return false;
        }
        for (const auto& [key, _] : entry.items()) {
            if (key != "label" && key != "value") {
                return false;
            }
        }
    }
    return true;
}

SchemaEditorDesc schema_editor_desc(
    const domain::Json& prop, const ComposerElement& element,
    const std::map<std::string, std::string>& chart_series_schemas) {
    SchemaEditorDesc desc;
    desc.name = prop_string(prop, "name");
    const std::string ptype =
        prop_string(prop, "type", "str").empty()
            ? "str"
            : prop_string(prop, "type", "str");
    desc.label = prop_string(prop, "label").empty() ? desc.name
                                                    : prop_string(prop, "label");
    const domain::Json* value = nullptr;
    if (element.properties.is_object()) {
        const auto it = element.properties.find(desc.name);
        if (it != element.properties.end()) {
            value = &*it;
        }
    }
    if (ptype == "number") {
        desc.kind = SchemaEditorKind::Number;
        desc.min = prop_number(prop, "min", -1e9);
        desc.max = prop_number(prop, "max", 1e9);
        return desc;
    }
    if (ptype == "bool") {
        desc.kind = SchemaEditorKind::Bool;
        return desc;
    }
    if (ptype == "choices") {
        desc.kind = SchemaEditorKind::Choices;
        const auto it = prop.find("choices");
        if (it != prop.end() && it->is_array()) {
            for (const auto& choice : *it) {
                desc.choices.push_back(ui_data_core::json_str(choice));
            }
        }
        return desc;
    }
    if (ptype == "text") {
        desc.kind = SchemaEditorKind::Text;
        return desc;
    }
    if (ptype == "list") {
        const std::string chart_type = ui_data_core::json_get_string(
            element.properties, "chart_type", "bar");
        const domain::Json series =
            value != nullptr ? *value : domain::Json::array();
        if (element.element_type == "stat_chart" && desc.name == "series" &&
            table_series_chart_types().count(chart_type) != 0U &&
            series_is_label_value(series)) {
            desc.kind = SchemaEditorKind::SeriesTable;
        } else {
            desc.kind = SchemaEditorKind::Json;
            desc.json_text =
                (value != nullptr ? *value : domain::Json::array()).dump();
        }
        // 动态形态提示 (chart_type → CHART_SERIES_SCHEMAS description).
        if (element.element_type == "stat_chart" && desc.name == "series") {
            const auto it = chart_series_schemas.find(chart_type);
            if (it != chart_series_schemas.end() && !it->second.empty()) {
                desc.tooltip = "数据系列形态：" + it->second;
            }
        }
        return desc;
    }
    // str + unknown → single-line text.
    desc.kind = SchemaEditorKind::Str;
    return desc;
}

std::vector<SchemaEditorDesc> schema_editor_descs(
    const domain::Json& property_schema, const ComposerElement& element,
    const std::map<std::string, std::string>& chart_series_schemas) {
    std::vector<SchemaEditorDesc> descs;
    if (!property_schema.is_array()) {
        return descs;
    }
    for (const auto& prop : property_schema) {
        descs.push_back(
            schema_editor_desc(prop, element, chart_series_schemas));
    }
    return descs;
}

domain::Json series_collect(
    const std::vector<std::pair<std::string, std::string>>& rows) {
    domain::Json items = domain::Json::array();
    for (const auto& [label_raw, raw] : rows) {
        const std::string label = ui_data_core::strip_copy(label_raw);
        const std::string value_text = ui_data_core::strip_copy(raw);
        if (label.empty() && value_text.empty()) {
            continue;
        }
        double number = 0.0;
        try {
            number = std::stod(value_text.empty() ? "0" : value_text);
        } catch (...) {
            number = 0.0;  // float(raw) ValueError -> 0.0
        }
        items.push_back(domain::Json{{"label", label}, {"value", number}});
    }
    return items;
}

std::optional<domain::Json> schema_json_value(const std::string& text) {
    const std::string stripped = ui_data_core::strip_copy(text);
    if (stripped.empty()) {
        return domain::Json::array();
    }
    try {
        return domain::Json::parse(stripped);
    } catch (...) {
        return std::nullopt;  // ValueError -> warn + ignore
    }
}

bool schema_bool_value(const domain::Json& value) {
    // Python bool(value): null/false/0/0.0/""/[]/{} → false.
    switch (value.type()) {
    case domain::Json::value_t::boolean:
        return value.get<bool>();
    case domain::Json::value_t::number_integer:
    case domain::Json::value_t::number_unsigned:
    case domain::Json::value_t::number_float:
        return value.get<double>() != 0.0;
    case domain::Json::value_t::string:
        return !value.get<std::string>().empty();
    case domain::Json::value_t::array:
    case domain::Json::value_t::object:
        return !value.empty();
    case domain::Json::value_t::null:
    default:
        return false;
    }
}

double schema_float_value(const domain::Json& value) {
    // float(0.0 if value is None else value); TypeError/ValueError → 0.0.
    if (value.is_null()) {
        return 0.0;
    }
    if (value.is_boolean()) {
        return value.get<bool>() ? 1.0 : 0.0;
    }
    if (value.is_number()) {
        return value.get<double>();
    }
    if (value.is_string()) {
        try {
            return std::stod(value.get<std::string>());
        } catch (...) {
            return 0.0;
        }
    }
    return 0.0;  // array/object → TypeError parity
}

std::string schema_text_value(const domain::Json& value) {
    // str(value if value is not None else "").
    if (value.is_null()) {
        return {};
    }
    if (value.is_boolean()) {
        return value.get<bool>() ? "True" : "False";
    }
    if (value.is_number_integer()) {
        return std::to_string(value.get<long long>());
    }
    if (value.is_number()) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%.17g", value.get<double>());
        return buf;
    }
    if (value.is_string()) {
        return value.get<std::string>();
    }
    return value.dump();  // array/object → json text
}

// ---------------------------------------------------------------------------
// Session-level edits
// ---------------------------------------------------------------------------

bool apply_composition_title(CompositionEditSession& session,
                             Composition& document,
                             const std::string& title) {
    const std::string trimmed = ui_data_core::strip_copy(title);
    document.title = trimmed;  // direct attribute write (Python parity)
    // Unlocked TITLE element mirrors the text into properties["text"].
    for (auto& element : document.elements) {
        if (element.element_type == "title") {
            if (!element.locked) {
                try {
                    session.configure_element(
                        element.id,
                        domain::Json{{"text", trimmed}});
                } catch (const mapping_document::ComposerError&) {
                    // Python swallows ComposerError here.
                }
            }
            break;  // next(...) finds only the first TITLE element
        }
    }
    return true;
}

bool apply_element_geometry(CompositionEditSession& session,
                            Composition& document,
                            const std::string& element_id,
                            const std::string& field, double value) {
    ComposerElement* element =
        mapping_document::find_element(document, element_id);
    if (element == nullptr || element->locked) {
        return false;
    }
    try {
        if (field == "x" || field == "y") {
            session.move_element(element_id,
                                 field == "x" ? value : element->x_mm,
                                 field == "y" ? value : element->y_mm);
        } else if (field == "w" || field == "h") {
            session.scale_element(
                element_id,
                field == "w" ? std::max(1.0, value) : element->width_mm,
                field == "h" ? std::max(1.0, value) : element->height_mm);
        } else {
            return false;
        }
    } catch (const mapping_document::ComposerError&) {
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// History + misc
// ---------------------------------------------------------------------------

HistoryState history_state(const CompositionEditSession* session) {
    if (session == nullptr) {
        return {};
    }
    return {session->can_undo(), session->can_redo()};
}

CatalogExportPlan catalog_export_plan(bool project_available) {
    CatalogExportPlan plan;
    plan.should_register = project_available;
    return plan;
}

}  // namespace pwb::ui_seqviz
